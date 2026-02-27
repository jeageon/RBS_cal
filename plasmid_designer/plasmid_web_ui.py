from __future__ import annotations

import json
import base64
import re
import math
import tempfile
import io
import os
import socket
import subprocess
import sys
import threading
import time
import shutil
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Tuple
from Bio import SeqIO

try:
    from flask import Flask, jsonify, render_template, request
except ImportError as exc:
    raise RuntimeError(
        "Flask가 설치되어 있지 않습니다. pip install flask 를 먼저 실행한 뒤 다시 시작하세요."
    ) from exc

from plasmid_pipeline import (
    CloneParams,
    HostContext,
    InsertMetadata,
    _estimate_repeat_like,
    _normalize_mode,
    _normalize_strategy,
    run_pipeline,
)
from plasmid_safezone_engine import SafeZoneConfig, SafeZoneResult, build_safe_zones, parse_genbank


app = Flask(__name__)


_TOOL_LOCK = threading.Lock()
_TOOL_PROCESSES: dict[str, dict[str, Any]] = {}


@app.context_processor
def _plasmid_template_context():
    return {
        "script_root_path": request.script_root.rstrip("/"),
    }


def _tool_definitions() -> dict[str, dict[str, Any]]:
    return {
        "primer_maker": {
            "name": "PrimerMaker",
            "project_dir": Path("/Users/jg/Documents/prime_maker/pimer_maker"),
            "kind": "streamlit",
            "entry": "src/webui.py",
            "host": "127.0.0.1",
            "default_port": 8011,
            "command": ["-m", "streamlit", "run", "src/webui.py"],
            "env": {
                "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            },
            "description": "primer_maker 생성 Primer GB를 업로드하여 후보 프라이머군 생성·관리",
        },
        "rbs_cal": {
            "name": "RBS_cal",
            "project_dir": Path("/Users/jg/Documents/RBS_cal"),
            "kind": "flask",
            "entry": "app.py",
            "host": "127.0.0.1",
            "default_port": 8010,
            "command": ["app.py"],
            "env": {
                "RBS_AUTO_OPEN_BROWSER": "0",
            },
            "description": "RBS 설계 파라미터/작업 제출을 웹 UI에서 바로 수행",
        },
        "dh5a_utg": {
            "name": "DH5a-UTG",
            "project_dir": Path("/Users/jg/Documents/New project"),
            "kind": "streamlit",
            "entry": "src/webui.py",
            "host": "127.0.0.1",
            "default_port": 8012,
            "command": ["-m", "streamlit", "run", "src/webui.py"],
            "env": {
                "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            },
            "description": "UTG/DH5a 벡터 검색 및 변이 구역 분석",
        },
    }


TOOL_DEFS = _tool_definitions()


def _resolve_python_executable(project_dir: Path) -> str:
    for candidate in (
        project_dir / ".venv" / "bin" / "python3",
        project_dir / ".venv" / "bin" / "python",
    ):
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("python3") or shutil.which("python") or sys.executable


def _is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def _next_available_port(start: int, host: str = "127.0.0.1", max_scan: int = 40) -> int:
    for candidate in range(start, start + max_scan):
        if _is_port_available(candidate, host=host):
            return candidate
    raise RuntimeError(f"사용 가능한 포트를 찾지 못했습니다. 시작={start}, 최대={start + max_scan - 1}")


def _tool_is_running(runtime: dict[str, Any] | None) -> bool:
    return bool(runtime and runtime.get("process") and runtime["process"].poll() is None)


def _cleanup_dead_tools() -> None:
    with _TOOL_LOCK:
        dead = [
            key for key, runtime in _TOOL_PROCESSES.items() if not _tool_is_running(runtime)
        ]
        for key in dead:
            _close_tool_handles(_TOOL_PROCESSES.pop(key, None))


def _close_tool_handles(runtime: dict[str, Any] | None) -> None:
    if not runtime:
        return
    process = runtime.get("process")
    log_handle = runtime.get("log_handle")
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    if log_handle is not None:
        try:
            log_handle.close()
        except Exception:
            pass


def _safe_kill_tool(name: str) -> bool:
    with _TOOL_LOCK:
        runtime = _TOOL_PROCESSES.pop(name, None)
    if runtime is None:
        return False
    _close_tool_handles(runtime)
    return True


def _tool_url(cfg: dict[str, Any], port: int) -> str:
    return f"{cfg['host']}:{port}"


def _start_tool(name: str) -> dict[str, Any]:
    cfg = TOOL_DEFS.get(name)
    if not cfg:
        raise KeyError(f"지원하지 않는 도구: {name}")

    project_dir = Path(cfg.get("project_dir"))
    if not project_dir.exists():
        raise RuntimeError(f"도구 폴더를 찾을 수 없습니다: {project_dir}")

    entry = str(cfg.get("entry", ""))
    if entry and not (project_dir / entry).exists() and cfg["kind"] == "flask":
        raise RuntimeError(f"도구 실행 파일을 찾을 수 없습니다: {project_dir / entry}")

    with _TOOL_LOCK:
        existing = _TOOL_PROCESSES.get(name)
        if _tool_is_running(existing):
            return {
                "ok": True,
                "name": name,
                "running": True,
                "port": int(existing["port"]),
                "pid": int(existing["process"].pid),
                "status": "running",
                "url": f"http://{_tool_url(cfg, int(existing['port']))}",
                "message": "already-running",
            }

        _cleanup_dead_tools()

        port = _next_available_port(int(cfg.get("default_port", 8080)), host=cfg.get("host", "127.0.0.1"))
        python_bin = _resolve_python_executable(project_dir)
        host = cfg.get("host", "127.0.0.1")

        if cfg["kind"] == "flask":
            command = [python_bin] + list(cfg.get("command", []))
        else:
            command = [python_bin] + list(cfg.get("command", []))

        env = os.environ.copy()
        env.update(cfg.get("env", {}))
        if cfg["kind"] == "flask":
            env["HOST"] = host
            env["PORT"] = str(port)
        else:
            env["STREAMLIT_SERVER_ADDRESS"] = host
            env["STREAMLIT_SERVER_PORT"] = str(port)
            command.extend(["--server.address", host, "--server.port", str(port), "--server.headless", "true"])

        log_path = project_dir / f".{name}_webui_server.log"
        log_handle = log_path.open("a", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=str(project_dir),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )

        runtime = {
            "name": name,
            "process": process,
            "port": port,
            "started_at": time.time(),
            "log_path": str(log_path),
            "log_handle": log_handle,
        }
        _TOOL_PROCESSES[name] = runtime

    # blocking check는 짧게, 10초 내 응답성 위해 소요 시간을 제한
    deadline = time.time() + 8
    while time.time() < deadline:
        if _tool_is_running(runtime):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.2)
                if sock.connect_ex((host, port)) == 0:
                    break
        time.sleep(0.4)

    return {
        "ok": True,
        "name": name,
        "running": _tool_is_running(runtime),
        "port": port,
        "pid": int(process.pid),
        "status": "running" if _tool_is_running(runtime) else "starting",
        "url": f"http://{_tool_url(cfg, port)}",
        "log": str(log_path),
        "message": "started",
    }


def _parse_float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return float(value)


def _parse_bool_flag(form: Dict[str, str], key: str) -> bool:
    return bool(form.get(key))


def _normalize_insert_seq(raw: str | None) -> str:
    if raw is None:
        return ""
    return "".join(ch for ch in raw.upper() if ch.isalpha())


def _parse_sequence_text(raw: str | None) -> Tuple[str, list[str]]:
    text = (raw or "").strip()
    if not text:
        return "", ["삽입 서열 텍스트가 비어 있습니다."]

    normalized = _normalize_insert_seq(text)
    if not normalized:
        return "", ["입력 텍스트에서 유효한 염기 문자열을 추출하지 못했습니다."]

    if any(ch not in "ACGTU" for ch in normalized):
        if text.startswith(">"):
            # FASTA-like header-only input is likely malformed
            warnings = ["FASTA 헤더만 입력되었거나 유효 염기가 없습니다."]
            return "", warnings
        # 유효하지 않은 문자를 제외하고 진행
        filtered = "".join(ch for ch in normalized if ch in "ACGTU")
        if not filtered:
            return "", ["ACGT/U 이외의 문자만 존재합니다. 삽입 서열을 다시 입력하세요."]
        warnings = ["비염기 문자는 자동 제거되어 계산됩니다."]
        normalized = filtered
    else:
        warnings = []

    return normalized.replace("U", "T"), warnings


def _parse_fasta_text(raw: str) -> Tuple[str, list[str]]:
    text = (raw or "").strip()
    if not text:
        return "", ["빈 FASTA 텍스트입니다."]

    lines = text.splitlines()
    has_header = any(line.strip().startswith(">") for line in lines)
    if not has_header:
        return _parse_sequence_text(text)

    seq_parts: list[str] = []
    for line in lines:
        l = line.strip()
        if not l or l.startswith(">"):
            continue
        seq_parts.append(_normalize_insert_seq(l))
    seq = "".join(seq_parts)
    if not seq:
        return "", ["FASTA에서 염기서열을 추출하지 못했습니다."]

    return _parse_sequence_text(seq)


def _parse_insert_file(raw_bytes: bytes, filename: str) -> Tuple[str, list[str]]:
    ext = Path(filename or "").suffix.lower()
    text = ""
    try:
        text = raw_bytes.decode("utf-8", errors="ignore")
    except Exception:
        pass

    if ext in {".gb", ".gbk", ".genbank"}:
        try:
            records = list(SeqIO.parse(StringIO(text), "genbank"))
            if not records:
                return "", ["GenBank 파일에서 레코드를 찾지 못했습니다."]
            seq = str(records[0].seq).upper().replace("U", "T")
            if not seq:
                return "", ["GenBank 파일에서 서열이 비어 있습니다."]
            return _parse_sequence_text(seq)
        except Exception:
            # GenBank 파싱 실패 시 FASTA/텍스트로 fallback
            pass

    if ext in {".fa", ".fasta", ".fas", ".fna"} or text.strip().startswith(">"):
        return _parse_fasta_text(text)

    return _parse_sequence_text(text)


def _validate_insert_sequence(seq: str) -> tuple[float | None, float | None, float]:
    if not seq:
        return None, None, 0.0

    if not re.fullmatch(r"[ACGT]+", seq):
        # allow only canonical bases for reliable 통계
        seq = "".join(ch for ch in seq if ch in {"A", "C", "G", "T"})
    if not seq:
        return None, None, 0.0

    gc = (seq.count("G") + seq.count("C")) / max(1, len(seq))
    window = 20 if len(seq) >= 20 else len(seq)
    extreme = gc
    if window > 1:
        local_max_deviation = 0.0
        if len(seq) <= window:
            local_max_deviation = abs(gc - 0.5)
        else:
            for i in range(0, len(seq) - window + 1):
                w = seq[i : i + window]
                if not w:
                    continue
                w_gc = (w.count("G") + w.count("C")) / len(w)
                local_max_deviation = max(local_max_deviation, abs(w_gc - 0.5))
            extreme = local_max_deviation
    repeat_like = _estimate_repeat_like(seq)
    return gc, extreme, repeat_like


def _build_insert_metadata(form: Dict[str, str], insert_file) -> tuple[InsertMetadata, list[str], dict[str, Any]]:
    mode = (form.get("insert_input_mode") or "sequence").strip().lower()
    raw_seq = (form.get("insert_sequence") or "").strip()
    warnings: list[str] = []
    parsed = ""
    source = "manual_input"

    if mode == "file":
        if insert_file is not None and insert_file.filename:
            parsed, w = _parse_insert_file(insert_file.read(), insert_file.filename)
            insert_file.seek(0)
            warnings.extend(w)
            source = "file"
        elif raw_seq:
            # mode=파일인데 텍스트가 들어온 경우 fallback
            parsed, w = _parse_fasta_text(raw_seq)
            warnings.extend(w)
            source = "sequence"
        else:
            warnings.append("삽입 파일이 없고 서열도 비어 있습니다.")
    else:
        parsed, w = _parse_fasta_text(raw_seq) if (raw_seq.startswith(">") or "\n" in raw_seq) else _parse_sequence_text(raw_seq)
        warnings.extend(w)
        source = "sequence"

    gc_content: float | None
    gc_extreme: float | None
    repeat_like: float
    if parsed:
        gc_content, gc_extreme, repeat_like = _validate_insert_sequence(parsed)
        if gc_extreme is None:
            gc_extreme = gc_content
    else:
        try:
            parsed_len = int(form.get("insert_length", 0) or 0)
        except ValueError:
            parsed_len = 0
        gc_content = _parse_float_or_none(form.get("insert_gc"))
        gc_extreme = _parse_float_or_none(form.get("insert_extreme_gc"))
        repeat_like = _parse_float_or_none(form.get("insert_repeat_like")) or 0.0
        return (
            InsertMetadata(
                length_bp=max(0, parsed_len),
                gc_content=gc_content,
                gc_extreme=gc_extreme,
                toxic_gene=_parse_bool_flag(form, "toxic"),
                repeat_like=repeat_like,
            ),
            warnings,
            {
                "source": source,
                "length_bp": max(0, parsed_len),
                "gc_content": gc_content,
                "gc_extreme": gc_extreme,
                "repeat_like": repeat_like,
                "raw_input": raw_seq,
                "parsed_sequence": parsed,
                "parsed_success": False,
            },
        )

    return (
        InsertMetadata(
            length_bp=len(parsed),
            gc_content=gc_content,
            gc_extreme=gc_extreme,
            toxic_gene=_parse_bool_flag(form, "toxic"),
            repeat_like=repeat_like,
        ),
        warnings,
        {
            "source": source,
            "length_bp": len(parsed),
            "gc_content": gc_content,
            "gc_extreme": gc_extreme,
            "repeat_like": repeat_like,
            "raw_input": raw_seq,
            "parsed_sequence": parsed,
            "parsed_success": True,
        },
    )


def _parse_manual_tags(raw: str | None) -> Tuple[Dict[str, str], list[str]]:
    tags: Dict[str, str] = {}
    warnings: list[str] = []
    if not raw:
        return tags, warnings

    for line in raw.splitlines():
        item = line.strip()
        if not item:
            continue
        if item.startswith("#"):
            continue
        if "=" not in item:
            warnings.append(f"manual-tag '{item}' is ignored (expected key=value)")
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip().lower()
        if not key:
            warnings.append(f"manual-tag '{item}' is ignored (key empty)")
            continue
        if not value:
            warnings.append(f"manual-tag '{item}' is ignored (value empty)")
            continue
        tags[key] = value
    return tags, warnings


def _build_payload_with_visualization(result: Any) -> dict:
    payload = json.loads(result.to_json())
    payload["candidate_count"] = len(result.candidates)
    payload["top_candidate"] = _format_candidate_payload(result.candidates[:3])
    payload["backbone_preview"] = _build_backbone_preview_payload(result.safe_result, candidates=result.candidates[:3])

    if result.safe_result is not None:
        payload["visualization"] = _build_interactive_visualization_payload(
            record_id=result.record_id,
            safe_result=result.safe_result,
            candidates=result.candidates,
            top_candidates=6,
        )
    return payload


def _build_safezone_from_request(
    form: Dict[str, str],
    uploaded_file,
    manual_tags: Dict[str, str] | None = None,
) -> SafeZoneResult:
    if uploaded_file is None or not uploaded_file.filename:
        raise ValueError("plasmid file is required")

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".gb", delete=False) as fp:
        fp.write(uploaded_file.read())
        gb_path = Path(fp.name)

    try:
        record = parse_genbank(gb_path)
        cfg = SafeZoneConfig(
            buffer_bp=max(0, int(form.get("buffer", 100) or 100)),
            target_mode=_normalize_mode(form.get("mode", "neutral")),
            include_disruptable=not bool(form.get("exclude_disruptable")),
            include_neutral=not bool(form.get("exclude_neutral")),
            topology=form.get("topology_override") or None,
        )
        return build_safe_zones(record, cfg=cfg, manual_labels=manual_tags)
    finally:
        uploaded_file.seek(0)
        try:
            gb_path.unlink(missing_ok=True)
        except Exception:
            pass


def _arc_path(cx: float, cy: float, r: float, start_pos: int, end_pos: int, length: int) -> str:
    if length <= 0 or r <= 0:
        return ""
    if end_pos <= start_pos:
        return ""
    if end_pos - start_pos >= length:
        # full circle
        x0 = cx + r
        y0 = cy
        x1 = cx + r - 0.0001
        return f"M {x0:.2f} {y0:.2f} A {r:.2f} {r:.2f} 0 1 1 {x1:.2f} {y0:.2f}"

    a0 = (start_pos / max(1, length)) * 360.0 - 90.0
    a1 = (end_pos / max(1, length)) * 360.0 - 90.0
    if a1 <= a0:
        a1 += 360.0
    span = a1 - a0
    if span <= 0.0:
        return ""
    p0x = cx + math.cos(math.radians(a0)) * r
    p0y = cy + math.sin(math.radians(a0)) * r
    p1x = cx + math.cos(math.radians(a1)) * r
    p1y = cy + math.sin(math.radians(a1)) * r
    large_arc = 1 if span > 180 else 0
    return (
        f"M {p0x:.2f} {p0y:.2f} "
        f"A {r:.2f} {r:.2f} 0 {large_arc} 1 {p1x:.2f} {p1y:.2f}"
    )


def _arc_paths_from_interval(cx: float, cy: float, r: float, start: int, end: int, length: int) -> list[str]:
    if length <= 0:
        return []
    if end < 0 or start < 0:
        return []
    start = int(start) % length
    end = int(end) % length
    if end == start:
        return [_arc_path(cx, cy, r, 0, length, length)]
    if end > start:
        return [_arc_path(cx, cy, r, start, end, length)]
    return [_arc_path(cx, cy, r, start, length, length), _arc_path(cx, cy, r, 0, end, length)]


def _importance_color(importance: str) -> str:
    imp = (importance or "").lower()
    if imp == "protected":
        return "#1f5fa8"
    if imp == "disruptable":
        return "#d97706"
    if imp == "neutral":
        return "#2e7d32"
    return "#6b7280"


def _short_feature_label(raw: str, limit: int = 16) -> str:
    text = (raw or "").strip()
    if not text:
        return "feature"
    if len(text) <= limit:
        return text
    return f"{text[: max(1, limit - 1)]}…"


def _feature_label_from_hit(feature: Any) -> str:
    qualifiers = getattr(feature, "qualifiers", {}) or {}
    for key in ("gene", "label", "product", "note", "locus_tag"):
        values = qualifiers.get(key) or []
        if not isinstance(values, (list, tuple)):
            values = [values]
        for raw in values:
            value = str(raw).strip()
            if not value:
                continue
            if _is_unknown_label(value):
                continue
            return value

    fallback = (getattr(feature, "label", "") or "").strip()
    if fallback and not _is_unknown_label(fallback):
        return fallback

    feature_type = (getattr(feature, "feature_type", "") or "").replace("_", " ").strip()
    return feature_type


def _feature_score_for_preview(feature: Any) -> float:
    imp = _normalize_importance(getattr(feature, "importance", None))
    feature_type = (getattr(feature, "feature_type", "") or "").lower()
    label = _feature_label_from_hit(feature).lower()
    start = int(getattr(feature, "start", 0) or 0)
    end = int(getattr(feature, "end", 0) or 0)
    length = max(0, end - start)

    core_keywords = ("ori", "rep_origin", "replication", "cds", "gene", "promoter", "terminator")
    score = float(length)
    if any(keyword in feature_type for keyword in core_keywords):
        score += 250.0
    if any(keyword in label for keyword in core_keywords):
        score += 120.0
    if imp == "protected":
        score += 220.0
    elif imp == "disruptable":
        score += 110.0
    elif imp == "neutral":
        score += 20.0

    if _is_unknown_label(_feature_label_from_hit(feature)):
        score -= 140.0
    return max(0.0, score)


def _select_preview_features(safe_result: Any, max_features: int = 18) -> list[tuple[Any, float]]:
    selected = []
    for feature in getattr(safe_result, "features", []):
        start = int(getattr(feature, "start", 0))
        end = int(getattr(feature, "end", 0))
        if end <= start:
            continue
        imp = _normalize_importance(getattr(feature, "importance", None))
        length = end - start
        label = _feature_label_from_hit(feature)
        has_label = bool(label and not _is_unknown_label(label))
        if imp == "neutral" and not has_label and length < 80:
            # 방해가 되는 초미세/라벨없는 neutral 구간은 플롯에서 제외
            continue
        selected.append((feature, _feature_score_for_preview(feature)))

    selected.sort(key=lambda item: item[1], reverse=True)

    protected = [item for item in selected if _normalize_importance(getattr(item[0], "importance", None)) == "protected"]
    others = [item for item in selected if _normalize_importance(getattr(item[0], "importance", None)) != "protected"]

    ordered: list[tuple[Any, float]] = []
    ordered.extend(protected)
    ordered.extend(others)
    return ordered[:max_features]


def _feature_color_for_preview(feature: Any) -> str:
    imp = _normalize_importance(getattr(feature, "importance", None))
    feature_type = (getattr(feature, "feature_type", "") or "").lower()
    label = _feature_label_from_hit(feature).lower()

    if "origin" in feature_type or "ori" in feature_type or "origin" in label:
        return "#facc15"
    if feature_type in {"promoter", "enhancer"} or "promoter" in label:
        return "#ffffff"
    if "cds" in feature_type or feature_type == "gene":
        return "#86efac"
    if imp == "protected":
        return "#60a5fa"
    if imp == "disruptable":
        return "#f97316"
    if imp == "neutral":
        return "#34d399"
    return "#9ca3af"


def _build_dna_features_viewer_payload(safe_result: Any, candidates: list[Any] | None = None, width: int = 760, height: int = 760, max_features: int = 18) -> dict[str, Any]:
    if safe_result is None:
        return {"image": None}

    from dna_features_viewer import CircularGraphicRecord, GraphicFeature
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    L = int(getattr(safe_result, "length", 0) or 0)
    if L <= 0:
        return {"image": None}

    candidates = candidates or []
    selected_features: list[Any] = []
    for feature, _ in _select_preview_features(safe_result, max_features=max_features):
        start = int(getattr(feature, "start", 0))
        end = int(getattr(feature, "end", 0))
        if end <= start:
            continue

        raw_label = _feature_label_from_hit(feature)
        length = end - start
        imp = _normalize_importance(getattr(feature, "importance", None))
        display = _short_feature_label(raw_label or _importance_abbr(imp), 12)
        # 핵심(feature 중심)만 라벨 표시
        label = display if (length >= 40 or imp == "protected") else None

        selected_features.append(
            GraphicFeature(
                start=start,
                end=end,
                strand=int(getattr(feature, "strand", 0) or 0),
                color=_feature_color_for_preview(feature),
                label=label,
            )
        )

    for idx, (start, end) in enumerate(sorted(getattr(safe_result, "safe_zones", []), key=lambda x: (x[1] - x[0]), reverse=True)[:2]):
        if end <= start:
            continue
        selected_features.append(
            GraphicFeature(
                start=int(start),
                end=int(end),
                strand=0,
                color="#dbeafe",
                label=None if idx else "safe",
            )
        )

    for idx, candidate in enumerate(candidates[:3]):
        start = int(getattr(candidate, "start", 0))
        end = int(getattr(candidate, "end", 0))
        if end <= start:
            continue
        selected_features.append(
            GraphicFeature(
                start=start,
                end=end,
                strand=0,
                color="#7c3aed",
                label=f"R{idx + 1}",
            )
        )

    if not selected_features:
        selected_features.append(
            GraphicFeature(
                start=0,
                end=max(1, min(40, L)),
                strand=0,
                color="#e5e7eb",
                label="plasmid",
            )
        )

    circular = CircularGraphicRecord(
        sequence_length=L,
        features=selected_features,
    )

    fig, ax = plt.subplots(figsize=(width / 96.0, height / 96.0), dpi=96)
    plot_return = circular.plot(ax=ax)
    if isinstance(plot_return, tuple) and plot_return:
        ax = plot_return[0] if plot_return[0] is not None else ax
    ax.set_title(f"{getattr(safe_result, 'sequence_id', 'plasmid')} ({L} bp)")
    ax.set_aspect("equal")
    ax.set_axis_off()
    fig.tight_layout(pad=0.2)

    buffer = io.BytesIO()
    fig.savefig(buffer, format="svg", bbox_inches="tight")
    plt.close(fig)
    svg_text = buffer.getvalue().decode("utf-8", errors="ignore")
    encoded = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")

    return {
        "image": f"data:image/svg+xml;base64,{encoded}",
        "length": L,
        "topology": (getattr(safe_result, "topology", "") or "").strip() or "circular",
        "sequence_id": getattr(safe_result, "sequence_id", ""),
        "renderer": "dna_features_viewer",
    }


def _build_legacy_backbone_preview_payload(safe_result: Any, width: int = 640, height: int = 640) -> dict[str, Any]:
    if safe_result is None:
        return {"image": None}
    L = int(getattr(safe_result, "length", 0) or 0)
    if L <= 0:
        return {"image": None}

    cx = width / 2
    cy = height / 2
    ring = min(cx, cy) - 24
    r_feature = ring * 0.72
    r_safe = ring * 0.58
    r_protected = ring * 0.50
    labels: list[str] = []
    paths: list[str] = []

    bg_circle = (
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{ring:.2f}" fill="none" '
        'stroke="#0f172a" stroke-width="6" opacity="0.95" />'
    )
    paths.append(bg_circle)
    paths.append(
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{ring * 0.14:.2f}" fill="#ffffff" stroke="#0f172a" stroke-width="1.5" />'
    )
    center_text = f'<text x="{cx:.2f}" y="{cy:.2f}" text-anchor="middle" dominant-baseline="middle" '
    center_text += f'font-family="Arial" font-size="12" fill="#374151">{getattr(safe_result, "sequence_id", "plasmid")} (len={L})</text>'
    paths.append(center_text)

    for start, end in getattr(safe_result, "safe_zones", []):
        for d in _arc_paths_from_interval(cx, cy, r_safe, start, end, L):
            if not d:
                continue
            paths.append(
                f'<path d="{d}" fill="none" stroke="#0f766e" stroke-width="8" stroke-linecap="round" opacity="0.35" />'
            )

    for start, end in getattr(safe_result, "protected_plus_buffer", []):
        for d in _arc_paths_from_interval(cx, cy, r_protected, start, end, L):
            if not d:
                continue
            paths.append(
                f'<path d="{d}" fill="none" stroke="#b91c1c" stroke-width="8" stroke-linecap="round" opacity="0.55" />'
            )

    for feature in getattr(safe_result, "features", []):
        start = int(getattr(feature, "start", 0))
        end = int(getattr(feature, "end", 0))
        if end <= start:
            continue
        imp = _normalize_importance(getattr(feature, "importance", None))
        color = _importance_color(imp)
        for d in _arc_paths_from_interval(cx, cy, r_feature, start, end, L):
            if not d:
                continue
            paths.append(
                f'<path d="{d}" fill="none" stroke="{color}" stroke-width="9" stroke-linecap="round" '
                f'opacity="0.95" />'
            )
        mid = (start + end) / 2.0
        a = (mid / max(1, L)) * 360.0 - 90.0
        tx = cx + math.cos(math.radians(a)) * (r_feature + 18)
        ty = cy + math.sin(math.radians(a)) * (r_feature + 18)
        if len(labels) < 24:
            label = _short_feature_label(getattr(feature, "label", "") or getattr(feature, "feature_type", ""), 14)
            labels.append(
                f'<text x="{tx:.2f}" y="{ty:.2f}" text-anchor="middle" font-size="9" '
                f'font-family="Arial" fill="#0f172a" opacity="0.85">{label}</text>'
            )

    # origin mark + direction marker
    for a, cls in ((0, "#0f172a"), (120, "#64748b"), (240, "#64748b")):
        x0 = cx + math.cos(math.radians(a - 90)) * (r_feature + 22)
        y0 = cy + math.sin(math.radians(a - 90)) * (r_feature + 22)
        x1 = cx + math.cos(math.radians(a - 90)) * (ring + 8)
        y1 = cy + math.sin(math.radians(a - 90)) * (ring + 8)
        paths.append(f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" stroke="{cls}" stroke-width="2.2" />')

    origin_angle = -90.0
    arrow_r = ring * 1.05
    arrow_x = cx + math.cos(math.radians(origin_angle)) * arrow_r
    arrow_y = cy + math.sin(math.radians(origin_angle)) * arrow_r
    paths.append(
        f'<line x1="{cx:.2f}" y1="{cy:.2f}" x2="{arrow_x:.2f}" y2="{arrow_y:.2f}" stroke="#0f172a" '
        f'stroke-width="1.8" stroke-linecap="round" />'
    )
    paths.append(
        f'<text x="{arrow_x:.2f}" y="{arrow_y - 8:.2f}" font-size="10" fill="#0f172a" '
        f'font-family="Arial" text-anchor="middle">0</text>'
    )

    topo = (getattr(safe_result, "topology", "") or "").strip().lower()
    if topo:
        paths.append(
            f'<text x="{14:.2f}" y="{22:.2f}" font-size="11" font-family="Arial" fill="#334155">'
            f'{topo}</text>'
        )

    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        "<g>",
        "".join(paths),
        "".join(labels),
        "</g>",
        "</svg>",
    ]
    svg_text = "".join(svg)
    encoded = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
    return {
        "image": f"data:image/svg+xml;base64,{encoded}",
        "length": L,
        "topology": topo,
        "sequence_id": getattr(safe_result, "sequence_id", ""),
        "renderer": "legacy",
    }


def _build_backbone_preview_payload(
    safe_result: Any,
    candidates: list[Any] | None = None,
    width: int = 640,
    height: int = 640,
) -> dict[str, Any]:
    try:
        return _build_dna_features_viewer_payload(
            safe_result=safe_result,
            candidates=candidates,
            width=width,
            height=height,
            max_features=18,
        )
    except Exception:
        payload = _build_legacy_backbone_preview_payload(safe_result=safe_result, width=width, height=height)
        payload["renderer"] = payload.get("renderer", "legacy")
        warnings = payload.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append("dna-features-viewer 렌더링을 사용할 수 없어 fallback SVG를 사용했습니다.")
        elif isinstance(warnings, str):
            payload["warnings"] = [warnings, "dna-features-viewer 렌더링을 사용할 수 없어 fallback SVG를 사용했습니다."]
        return payload


def _normalize_importance(value: Any) -> str:
    if value is None:
        return "neutral"
    if isinstance(value, str):
        return value.strip().lower()
    return str(getattr(value, "value", value)).strip().lower()


def _importance_abbr(value: str) -> str:
    value = (value or "").lower()
    if value == "protected":
        return "PROT"
    if value == "disruptable":
        return "DIS"
    if value == "neutral":
        return "NEU"
    return "OTH"


def _short_label(raw: str, limit: int = 14) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(1, limit - 1)]}…"


def _is_unknown_label(raw: str | None) -> bool:
    text = (raw or "").strip().lower()
    if not text:
        return True
    return (
        "unknown id" in text
        or "<unknown" in text
        or text == "unknown"
        or "hypothetical protein" in text
    )


def _normalize_label(raw: str, idx: int) -> tuple[str, str, bool]:
    raw_label = (raw or "").strip()
    is_unknown = _is_unknown_label(raw_label)
    if is_unknown:
        base = f"id:{idx:02d}"
    else:
        base = raw_label
    compact = _short_label(base, 13)
    return compact, base, is_unknown


def _build_feature_labels(safe_result: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared: list[dict[str, Any]] = []
    for idx, f in enumerate(safe_result.features, 1):
        raw_label = (getattr(f, "label", "") or "").strip()
        compact, full_label, is_unknown = _normalize_label(raw_label, idx)

        importance = _normalize_importance(getattr(f, "importance", None))
        abbr = _importance_abbr(importance)
        display = f"{abbr}:{compact}"
        prepared.append(
            {
                "start": int(f.start),
                "end": int(f.end),
                "importance": importance,
                "importance_abbr": abbr,
                "display": display,
                "full": full_label or display,
                "tooltip": f"{full_label or display} | {importance}",
                "count": 1,
                "kind": "feature",
                "feature_type": getattr(f, "feature_type", ""),
                "group_key": (
                    importance,
                    "unknown_neutral" if is_unknown and importance == "neutral" else full_label,
                ),
                "type": "FEATURE",
            }
        )

    prepared.sort(key=lambda x: (x["start"], x["end"]))
    aggregated: list[dict[str, Any]] = []
    for item in prepared:
        if (
            item["importance"] == "neutral"
            and item["group_key"] == ("neutral", "unknown_neutral")
            and aggregated
            and aggregated[-1]["importance"] == item["importance"]
            and aggregated[-1]["group_key"] == item["group_key"]
            and item["start"] <= aggregated[-1]["end"] + 1
        ):
            prev = aggregated[-1]
            prev["end"] = max(prev["end"], item["end"])
            prev["count"] += 1
            prev["display"] = f"{prev['display']} (x{prev['count']})"
            prev["tooltip"] = f"{prev['full']} (x{prev['count']}, contiguous region)"
            prev["type"] = "AGG"
            continue

        aggregated.append(item)

    labels: list[dict[str, Any]] = []
    for item in aggregated:
        item["label"] = f"{item['display']}" if item["count"] == 1 else f"{item['display']}×{item['count']}"
        item["id"] = f"feat-{item['start']}-{item['end']}"
        labels.append(item)

    intervals: list[dict[str, Any]] = []
    for interval in safe_result.features:
        intervals.append(
            {
                "start": int(interval.start),
                "end": int(interval.end),
                "kind": "feature",
                "id": f"feature-{interval.start}-{interval.end}",
                "label": (getattr(interval, "label", "") or interval.feature_type),
                "importance": _normalize_importance(getattr(interval, "importance", None)),
            }
        )

    return labels, intervals


def _build_track_intervals(intervals: list[tuple[int, int]], kind: str) -> list[dict[str, Any]]:
    out = []
    for idx, (start, end) in enumerate(intervals):
        s = int(start)
        e = int(end)
        if e <= s:
            continue
        out.append(
            {
                "start": s,
                "end": e,
                "kind": kind,
                "id": f"{kind}-{idx}-{s}-{e}",
            }
        )
    return out


def _build_interactive_visualization_payload(
    record_id: str,
    safe_result: Any,
    candidates: list[Any],
    top_candidates: int = 6,
) -> dict[str, Any]:
    top_candidates = max(1, int(top_candidates))

    feature_labels, feature_intervals = _build_feature_labels(safe_result)
    candidate_labels: list[dict[str, Any]] = []
    for idx, candidate in enumerate(candidates[:top_candidates]):
        start = int(candidate.start)
        end = int(candidate.end)
        if end <= start:
            continue
        score = float(getattr(candidate, "score", 0.0))
        label = f"C{idx+1}({score:.1f})"
        candidate_labels.append(
            {
                "start": start,
                "end": end,
                "importance": "candidate",
                "importance_abbr": "CAND",
                "display": label,
                "label": label,
                "full": f"C{idx+1} | score={score:.2f}, risk={float(candidate.risk):.2f}",
                "tooltip": f"Candidate {idx+1}: score={score:.2f}, risk={float(candidate.risk):.3f}",
                "count": 1,
                "kind": "candidate",
                "type": "CAND",
                "id": f"cand-{idx}",
            }
        )

    safe_intervals = _build_track_intervals(safe_result.safe_zones, "safe")
    protected_intervals = _build_track_intervals(safe_result.protected_plus_buffer, "protected")
    candidate_intervals = [
        {
            "start": int(c["start"]),
            "end": int(c["end"]),
            "kind": "candidate",
            "id": c["id"],
            "label": c["display"],
            "importance": "candidate",
            "importance_abbr": c["importance_abbr"],
            "tooltip": c["tooltip"],
        }
        for c in candidate_labels
    ]

    return {
        "record_id": record_id,
        "length": int(safe_result.length),
        "topology": safe_result.topology,
        "label_mode": "compact",
        "tracks": {
            "safe": safe_intervals,
            "protected": protected_intervals,
            "features": feature_intervals,
            "candidate": candidate_intervals,
        },
        "labels": feature_labels + candidate_labels,
        "stats": {
            "label_count": len(feature_labels) + len(candidate_labels),
            "feature_count": len(feature_intervals),
            "candidate_count": len(candidate_labels),
            "safe_count": len(safe_intervals),
            "protected_count": len(protected_intervals),
        },
    }


def _build_params(form: Dict[str, str], insert_meta: InsertMetadata | None = None) -> CloneParams:
    mode = _normalize_mode(form.get("mode", "neutral"))
    strategy = _normalize_strategy(form.get("strategy", "inverse_pcr"))
    target_mode = mode

    if insert_meta is None:
        insert_meta = InsertMetadata(
            length_bp=max(0, int(form.get("insert_length", 0) or 0)),
            gc_content=_parse_float_or_none(form.get("insert_gc")),
            gc_extreme=_parse_float_or_none(form.get("insert_extreme_gc")),
            toxic_gene=_parse_bool_flag(form, "toxic"),
            repeat_like=_parse_float_or_none(form.get("insert_repeat_like")) or 0.0,
        )

    params = CloneParams(
        target_mode=target_mode,
        cloning_strategy=strategy,
        insert=insert_meta,
        include_disruptable=not bool(form.get("exclude_disruptable")),
        include_neutral=not bool(form.get("exclude_neutral")),
        buffer_bp=max(0, int(form.get("buffer", 100) or 100)),
        top_k=max(1, int(form.get("top_k", 20) or 20)),
        candidate_per_zone=max(1, int(form.get("candidate_per_zone", 3) or 3)),
        flank_bp=max(80, int(form.get("flank", 350) or 350)),
        risk_ratio_cap=max(0.01, float(form.get("risk_ratio_cap", 0.25) or 0.25)),
        risk_weight=max(0.0, float(form.get("risk_weight", 1.0) or 1.0)),
        strategy_window_bp=max(1000, int(form.get("strategy_window", 7000) or 7000)),
        max_product_bp=max(1, int(form.get("max_product", 4000) or 4000)),
    )

    params.host_context = HostContext(
        host=form.get("host", "E. coli").strip() or "E. coli",
        dam_dcm_sensitive=_parse_bool_flag(form, "dam_dcm_sensitive"),
        methylation_sensitive=_parse_bool_flag(form, "dam_dcm_sensitive"),
        comments="",
    )
    return params


def _format_candidate_payload(candidates: list[Any]) -> list[dict]:
    return [c.as_1based() for c in candidates]


def _build_tools_payload() -> dict[str, Any]:
    _cleanup_dead_tools()
    items: list[dict[str, Any]] = []
    for name, cfg in TOOL_DEFS.items():
        project_dir = Path(cfg["project_dir"])
        available = project_dir.exists()
        runtime = _TOOL_PROCESSES.get(name)
        running = _tool_is_running(runtime)
        port = int(runtime.get("port")) if (running and runtime and runtime.get("port")) else int(cfg.get("default_port", 8080))
        items.append(
            {
                "key": name,
                "name": cfg.get("name", name),
                "host": cfg.get("host", "127.0.0.1"),
                "default_port": cfg.get("default_port", 8080),
                "port": port,
                "running": running,
                "pid": int(runtime.get("process").pid) if (running and runtime and runtime.get("process")) else None,
                "url": f"http://{cfg.get('host', '127.0.0.1')}:{port}",
                "log": str(project_dir / f".{name}_webui_server.log") if project_dir.exists() else "",
                "description": cfg.get("description", ""),
                "available": available,
            }
        )
    return {"ok": True, "tools": items}


@app.route("/api/tools/status", methods=["GET"])
def tools_status_api() -> tuple[str, int] | Any:
    try:
        return jsonify(_build_tools_payload())
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/tools/<name>/start", methods=["POST"])
def tools_start_api(name: str):
    cfg = TOOL_DEFS.get(name)
    if cfg is None:
        return jsonify({"ok": False, "error": f"지원하지 않는 도구: {name}"}), 404

    project_dir = Path(cfg.get("project_dir", Path("")))
    if not project_dir.exists():
        return jsonify({"ok": False, "error": f"도구 폴더가 없습니다: {project_dir}"}), 400

    try:
        payload = _start_tool(name)
        payload["tools"] = _build_tools_payload().get("tools", [])
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/tools/<name>/stop", methods=["POST"])
def tools_stop_api(name: str):
    if name not in TOOL_DEFS:
        return jsonify({"ok": False, "error": f"지원하지 않는 도구: {name}"}), 404

    stopped = _safe_kill_tool(name)
    status_payload = _build_tools_payload()
    status_payload["ok"] = True
    status_payload["stopped"] = stopped
    return jsonify(status_payload)


@app.route("/", methods=["GET"])
def index() -> str:
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run_view() -> str:
    uploaded = request.files.get("genbank_file")
    if uploaded is None or uploaded.filename == "":
        return render_template("index.html", error="GenBank 파일이 필요합니다. (.gb/.gbk)")

    insert_file = request.files.get("insert_file")
    form = request.form.to_dict()
    insert_meta, insert_warnings, insert_ctx = _build_insert_metadata(form, insert_file)
    params = _build_params(form, insert_meta=insert_meta)
    manual_tags, tag_warnings = _parse_manual_tags(request.form.get("manual_tags"))

    all_warnings = insert_warnings + tag_warnings

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".gb", delete=False) as fp:
        fp.write(uploaded.read())
        gb_path = Path(fp.name)

    try:
        result = run_pipeline(
            gb_path=gb_path,
            params=params,
            store=False,
            manual_tags=manual_tags,
        )
        result_payload = _build_payload_with_visualization(result)
        result_payload["manual_tag_warnings"] = all_warnings
        result_payload["manual_tags"] = manual_tags
        result_payload["insert_metadata"] = insert_ctx
        return render_template("index.html", result=result_payload)
    except Exception as exc:
        return render_template("index.html", error=str(exc), insert_metadata=insert_ctx, manual_tag_warnings=all_warnings)
    finally:
        try:
            gb_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.route("/api/run", methods=["POST"])
def run_api():
    uploaded = request.files.get("genbank_file")
    if uploaded is None or uploaded.filename == "":
        return jsonify({"ok": False, "error": "GenBank 파일이 필요합니다."}), 400

    insert_file = request.files.get("insert_file")
    form = request.form.to_dict()
    insert_meta, insert_warnings, insert_ctx = _build_insert_metadata(form, insert_file)
    params = _build_params(form, insert_meta=insert_meta)
    manual_tags, tag_warnings = _parse_manual_tags(request.form.get("manual_tags"))
    all_warnings = insert_warnings + tag_warnings

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".gb", delete=False) as fp:
        fp.write(uploaded.read())
        gb_path = Path(fp.name)

    try:
        result = run_pipeline(
            gb_path=gb_path,
            params=params,
            store=False,
            manual_tags=manual_tags,
        )
        payload = _build_payload_with_visualization(result)
        payload["ok"] = True
        payload["manual_tag_warnings"] = all_warnings
        payload["manual_tags"] = manual_tags
        payload["insert_metadata"] = insert_ctx
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "manual_tag_warnings": all_warnings}), 500
    finally:
        try:
            gb_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.route("/api/sanity", methods=["GET"])
def sanity_api():
    from sanity_checks import run_sanity_checks

    report = run_sanity_checks()
    return jsonify(report)


@app.route("/api/preview_backbone", methods=["POST"])
def preview_backbone_api():
    uploaded = request.files.get("genbank_file")
    if uploaded is None or uploaded.filename == "":
        return jsonify({"ok": False, "error": "GenBank 파일이 필요합니다."}), 400

    form = request.form.to_dict()
    manual_tags, tag_warnings = _parse_manual_tags(request.form.get("manual_tags"))
    all_warnings = list(tag_warnings)

    try:
        safe_result = _build_safezone_from_request(form, manual_tags=manual_tags, uploaded_file=uploaded)
        payload = _build_backbone_preview_payload(safe_result)
        payload["ok"] = True
        payload["warnings"] = all_warnings
        return jsonify(payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "warnings": all_warnings}), 500


@app.route("/api/analyze_insert", methods=["POST"])
def analyze_insert_api():
    form = request.form.to_dict()
    insert_file = request.files.get("insert_file")
    try:
        _, warnings, insert_ctx = _build_insert_metadata(form, insert_file)
        return jsonify({"ok": True, "insert_metadata": insert_ctx, "warnings": warnings})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=7860, debug=False, use_reloader=False)
