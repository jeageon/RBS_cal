from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import Flask
from werkzeug.middleware.dispatcher import DispatcherMiddleware


def _normalize_mount_path(mount_path: str) -> str:
    normalized = (mount_path or "/plasmid_designer").rstrip("/") or "/plasmid_designer"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _load_plasmid_designer_app(project_dir: Path) -> Tuple[Optional[Flask], Optional[str]]:
    webui_file = project_dir / "plasmid_web_ui.py"
    if not webui_file.exists():
        return None, f"plasmid_web_ui.py not found in {project_dir}"

    restore_sys_path = False
    added = str(project_dir)
    if added not in sys.path:
        sys.path.insert(0, added)
        restore_sys_path = True

    namespace: Dict[str, Any] = {}
    try:
        spec = importlib.util.spec_from_file_location("plasmid_designer_embedded", webui_file)
        if spec is None or spec.loader is None:
            return None, "Unable to create import spec for plasmid_web_ui.py"

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]

        app = getattr(module, "app", None)
        if not isinstance(app, Flask):
            return None, "plasmid_web_ui.py did not expose a Flask app object"
        return app, None
    except Exception as exc:
        return None, f"Failed to import plasmid_web_ui.py: {exc}"
    finally:
        if restore_sys_path:
            try:
                sys.path.remove(added)
            except ValueError:
                pass


def register_plasmid_designer(
    app: Flask,
    project_dir: str,
    mount_path: str = "/plasmid_designer",
) -> Dict[str, Any]:
    normalized_mount = _normalize_mount_path(mount_path)

    metadata: Dict[str, Any] = {
        "enabled": False,
        "mount_path": normalized_mount,
        "project_dir": str(project_dir),
        "error": None,
        "app_url": normalized_mount,
    }

    root = Path(project_dir)
    if not root.exists():
        metadata["error"] = f"plasmid_designer project not found: {root}"
        return metadata

    pd_app, err = _load_plasmid_designer_app(root)
    if err:
        metadata["error"] = err
        return metadata
    if pd_app is None:
        metadata["error"] = "Failed to build plasmid_designer app"
        return metadata

    wsgi = app.wsgi_app
    if isinstance(wsgi, DispatcherMiddleware):
        mounts = getattr(wsgi, "mounts", None) or getattr(wsgi, "mapping", None)
        if isinstance(mounts, dict) and normalized_mount in mounts:
            metadata["enabled"] = True
            metadata["mounted"] = True
            return metadata

    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {normalized_mount: pd_app})
    metadata["enabled"] = True
    metadata["mounted"] = True
    return metadata
