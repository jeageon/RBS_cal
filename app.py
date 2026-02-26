from __future__ import annotations

import csv
import logging
import io
import inspect
import os
import sys
import random
import re
import shutil
import subprocess
import tempfile
import json
import threading
import time
import traceback
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
import math

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB
app.logger.setLevel(logging.INFO)
OSTIR_BIN = os.environ.get("OSTIR_BIN", "ostir")
TASKS_TTL_SECONDS = int(os.environ.get("RBS_TASK_TTL_SECONDS", "3600"))
RBS_DESIGN_ITERATION_DEFAULT = int(os.environ.get("RBS_DESIGN_ITERATIONS", "500"))
RBS_DESIGN_CANDIDATES_DEFAULT = int(os.environ.get("RBS_DESIGN_TOP_CANDIDATES", "10"))
RBS_DESIGN_PRESEQ_MAX_BP = int(os.environ.get("RBS_DESIGN_PRESEQ_MAX_BP", "50"))
RBS_DESIGN_CDS_MAX_BP = int(os.environ.get("RBS_DESIGN_CDS_MAX_BP", "50"))
RBS_DESIGN_FULL_REFINEMENT_MULTIPLIER = max(1, int(os.environ.get("RBS_DESIGN_FULL_REFINEMENT_MULTIPLIER", "2")))
RBS_OSTIR_API_CACHE_SIZE = int(os.environ.get("RBS_OSTIR_API_CACHE_SIZE", "1024"))
RBS_DEFAULT_ASYNC = os.environ.get("RBS_DEFAULT_ASYNC", "1") == "1"
RBS_DEBUG_ERROR = os.environ.get("RBS_DEBUG_ERROR", "0") == "1"

DEFAULT_ASD = "ACCTCCTTA"
START_CODONS = ("ATG", "GTG", "TTG")
RBS_NUCLEOTIDES = ("A", "C", "G", "T")
DESIGN_RANDOM_SEED = os.environ.get("RBS_DESIGN_RANDOM_SEED", "")
DESIGN_SD_CORE = "AGGAGG"
DESIGN_SD_CORES = [
    core.strip().upper().replace("U", "T")
    for core in os.environ.get("RBS_DESIGN_SD_CORES", DESIGN_SD_CORE).split(",")
    if core.strip()
]
if not DESIGN_SD_CORES:
    DESIGN_SD_CORES = [DESIGN_SD_CORE]
DESIGN_SD_SPACING_MIN = int(os.environ.get("RBS_DESIGN_SD_SPACING_MIN", "5"))
DESIGN_SD_SPACING_MAX = int(os.environ.get("RBS_DESIGN_SD_SPACING_MAX", "9"))
DESIGN_RESTART_PATIENCE = int(os.environ.get("RBS_DESIGN_RESTART_PATIENCE", "100"))
DESIGN_ACCEPT_WINDOW = int(os.environ.get("RBS_DESIGN_ACCEPT_WINDOW", "20"))
DESIGN_TEMPERATURE_INIT = float(os.environ.get("RBS_DESIGN_TEMPERATURE_INIT", "1.0"))
DESIGN_TEMPERATURE_MIN = float(os.environ.get("RBS_DESIGN_TEMPERATURE_MIN", "1e-4"))
DESIGN_TEMPERATURE_MAX = float(os.environ.get("RBS_DESIGN_TEMPERATURE_MAX", "8.0"))
OSTIR_TIMEOUT_SECONDS = int(os.environ.get("OSTIR_TIMEOUT_SECONDS", "120"))
OSTIR_MODULE_HINT_RNA = "No module named 'RNA'"
VIENNARNA_PATH_HINT = "ViennaRNA is not properly installed or in PATH"
VIENNARNA_MISSING_HINT = "RBS Calculator Vienna is missing dependency ViennaRNA"
VIENNARNA_BINARIES = ("RNAfold", "RNAsubopt", "RNAeval")
_VIENNARNA_READY: Optional[bool] = None
_OSTIR_RUN = None
_BACKGROUND_TASKS: Dict[str, Dict[str, Any]] = {}
_TASK_LOCK = threading.Lock()

try:
    from ostir import run_ostir as _OSTIR_RUN  # type: ignore
except Exception:
    try:
        from ostir.ostir import run_ostir as _OSTIR_RUN  # type: ignore
    except Exception:
        _OSTIR_RUN = None


def _error_payload(message: str, status: int = 500, detail: Optional[str] = None):
    # Keep API responses production-safe: avoid leaking internals by default.
    payload = {"ok": False, "error": message}
    if RBS_DEBUG_ERROR and detail:
        payload["detail"] = detail
    return payload, status


def _now_timestamp() -> float:
    return time.time()


def _normalize_task(task: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(task)
    normalized.pop("result", None)
    normalized.pop("error_detail", None)
    return normalized


def _task_cleanup() -> None:
    cutoff = _now_timestamp() - TASKS_TTL_SECONDS
    with _TASK_LOCK:
        remove = [
            task_id
            for task_id, task in _BACKGROUND_TASKS.items()
            if task.get("updated_at", 0) < cutoff
        ]
        for task_id in remove:
            _BACKGROUND_TASKS.pop(task_id, None)


def _task_create(task_type: str) -> str:
    task_id = uuid.uuid4().hex
    now = _now_timestamp()
    with _TASK_LOCK:
        _BACKGROUND_TASKS[task_id] = {
            "id": task_id,
            "type": task_type,
            "status": "queued",
            "progress": 0.0,
            "message": "Queued",
            "result": None,
            "error": None,
            "error_detail": None,
            "created_at": now,
            "updated_at": now,
        }
    _task_cleanup()
    return task_id


def _task_update(task_id: str, **updates: Any) -> None:
    with _TASK_LOCK:
        current = _BACKGROUND_TASKS.get(task_id)
        if current is None:
            return
        current.update(updates)
        current["updated_at"] = _now_timestamp()


def _task_finish(task_id: str, result: Optional[Dict[str, Any]], error: Optional[str], error_detail: Optional[str] = None) -> None:
    _task_update(
        task_id,
        status="failed" if error else "completed",
        progress=1.0,
        message="Failed" if error else "Completed",
        result=result,
        error=error,
        error_detail=error_detail,
    )


def _run_in_background(task_id: str, func: Callable[..., Dict[str, Any]], *args: Any, **kwargs: Any) -> None:
    def _runner() -> None:
        _task_update(task_id, status="running", message="Running")
        try:
            result = func(*args, **kwargs)
            if not isinstance(result, dict):
                result = {"ok": False, "error": "Invalid worker result format."}
                _task_finish(task_id, result, "Invalid worker result format.")
                return
            _task_finish(task_id, result, None, None)
        except Exception as exc:
            app.logger.exception("Background task failed (id=%s)", task_id)
            debug_detail: Optional[str] = traceback.format_exc()[:1000] if RBS_DEBUG_ERROR else None
            error_text = str(exc) if RBS_DEBUG_ERROR else "Background task failed."
            _task_finish(task_id, None, error_text, debug_detail)


def _safe_ostir_result_to_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, (bytes, bytearray)):
        try:
            return bytes(result).decode("utf-8")
        except Exception:
            return ""
    if isinstance(result, str):
        return result

    rows: List[Dict[str, Any]] = []
    if isinstance(result, dict):
        nested = result.get("rows")
        if isinstance(nested, list):
            rows.extend(_normalize_ostir_row(row) for row in nested)
        elif any(k in result for k in ("start_position", "start_codon", "expression")):
            rows.append(_normalize_ostir_row(result))
        elif result:
            for value in result.values():
                if isinstance(value, list):
                    for row in value:
                        rows.append(_normalize_ostir_row(row))
                    break
    elif isinstance(result, (list, tuple, set)):
        rows.extend(_normalize_ostir_row(row) for row in result)

    if rows:
        return _serialize_ostir_rows_to_csv(rows)
    return ""


def _build_ostir_api_kwargs(
    signature: inspect.Signature,
    sequence: str,
    start: int,
    end: int,
    asd: str,
    threads: int,
    input_type: str,
) -> Dict[str, Any]:
    parameter_names = set(signature.parameters.keys())
    kwargs: Dict[str, Any] = {}

    input_candidates = ("seq", "sequence", "sequence_text", "input_sequence", "input", "seq_txt", "fasta", "path")
    asd_candidates = ("aSD", "asd", "anti_sd", "anti_sd_sequence", "sd")
    thread_candidates = ("threads", "n_threads", "n_jobs", "jobs", "njobs", "num_threads")
    start_candidates = ("start", "start_position", "start_codon", "s")
    end_candidates = ("end", "end_position", "e")
    output_candidates = ("otype", "output_type", "type", "fmt", "format", "output", "out")

    def pick(candidates: Tuple[str, ...]) -> Optional[str]:
        for name in candidates:
            if name in parameter_names:
                return name
        return None

    input_key = pick(input_candidates)
    if input_key is None and len(signature.parameters) == 0:
        input_key = None
    if input_key is not None:
        kwargs[input_key] = sequence

    asd_key = pick(asd_candidates)
    if asd_key is not None and asd:
        kwargs[asd_key] = asd

    thread_key = pick(thread_candidates)
    if thread_key is not None and threads > 0:
        kwargs[thread_key] = max(1, threads)

    if start > 0:
        start_key = pick(start_candidates)
        if start_key is not None:
            kwargs[start_key] = start

    if end > 0:
        end_key = pick(end_candidates)
        if end_key is not None:
            kwargs[end_key] = end

    if input_type:
        output_key = pick(output_candidates)
        if output_key is not None:
            kwargs[output_key] = "string"

    if ("otype" in parameter_names) and "otype" not in kwargs and input_type:
        kwargs["otype"] = "string"

    if ("format" in parameter_names) and "format" not in kwargs and input_type:
        kwargs["format"] = "string"

    if ("output" in parameter_names) and "output" not in kwargs:
        kwargs["output"] = None

    return kwargs


def _shorten_list(values: List[str], max_items: int = 12) -> List[str]:
    return values[:max_items]


def _serialize_ostir_rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return ""
    preferred = [
        "start_codon",
        "start_position",
        "expression",
        "RBS_distance_bp",
        "dG_total",
        "dG_rRNA:mRNA",
        "dG_mRNA",
        "dG_spacing",
        "dG_standby",
        "dG_start_codon",
    ]
    extra: List[str] = []
    for key in rows[0].keys():
        if key not in preferred and key not in extra:
            extra.append(key)
    fieldnames = [name for name in preferred if name in rows[0]] + extra
    if not fieldnames:
        return ""

    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        row_values = {
            key: "" if row.get(key) is None else row.get(key)
            for key in fieldnames
        }
        writer.writerow(row_values)

    return csv_buffer.getvalue().strip()


def _normalize_ostir_row(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    return {"expression": row}


@lru_cache(maxsize=RBS_OSTIR_API_CACHE_SIZE)
def _run_ostir_api_cached(sequence: str, start: int, end: int, asd: str, threads: int, input_type: str) -> str:
    if _OSTIR_RUN is None:
        return ""

    asd = asd or DEFAULT_ASD
    thread_count = max(1, threads)
    signature = inspect.signature(_OSTIR_RUN)
    kwargs = _build_ostir_api_kwargs(signature, sequence, start, end, asd, thread_count, input_type)

    # Try canonical keyword invocation.
    last_error: Optional[Exception] = None
    try:
        api_results = _OSTIR_RUN(**kwargs)
        text_result = _safe_ostir_result_to_text(api_results)
        if text_result:
            return text_result
    except TypeError as exc:
        last_error = exc

    # Try positional fallback variants. Different OSTIR versions expose slightly
    # different signatures, so we attempt a conservative set of call shapes.
    input_types = ("string", "txt", "fasta", "csv")
    canonical_output = input_type if input_type in input_types else "string"

    positional_variants: List[Tuple[Tuple[Any, ...], Dict[str, Any]]] = [
        ((sequence,), {}),
        ((sequence,), {"threads": thread_count}),
        ((sequence,), {"start": start, "end": end}),
        ((sequence,), {"start": start, "end": end, "threads": thread_count}),
    ]

    named_variants: List[Dict[str, Any]] = [
        {"sequence": sequence, "threads": thread_count, "start": start, "end": end, "output": canonical_output},
        {"sequence": sequence, "threads": thread_count, "output": canonical_output},
        {"seq": sequence, "threads": thread_count, "start": start, "end": end},
        {"seq": sequence, "threads": thread_count},
        {"input": sequence, "threads": thread_count, "start": start, "end": end},
        {"path": sequence, "threads": thread_count, "start": start, "end": end},
    ]
    named_variants.append({"input_sequence": sequence, "threads": thread_count, "start": start, "end": end})

    asd_names = ("aSD", "asd", "anti_sd", "anti_sd_sequence")
    asd_keys = [name for name in asd_names if name in signature.parameters]
    asd_name: Optional[str] = asd_keys[0] if asd_keys else None

    if asd_name:
        for variant in named_variants:
            variant.setdefault(asd_name, asd)

    for args, extra_kwargs in positional_variants:
        try:
            api_results = _OSTIR_RUN(*args, **{k: v for k, v in extra_kwargs.items() if v not in (None, "", 0)})
            text_result = _safe_ostir_result_to_text(api_results)
            if text_result:
                return text_result
        except Exception as exc:
            last_error = exc

    for variant in named_variants:
        try:
            candidate = dict(kwargs)
            candidate.update({key: value for key, value in variant.items() if value not in (None, "", 0)})
            if asd:
                candidate.setdefault("aSD", asd)
                candidate.setdefault("asd", asd)
            candidate.setdefault("otype", canonical_output)
            api_results = _OSTIR_RUN(**candidate)
            text_result = _safe_ostir_result_to_text(api_results)
            if text_result:
                return text_result
        except Exception as exc:
            last_error = exc

    # As a final fallback, pass only sequence as positional argument.
    try:
        api_results = _OSTIR_RUN(sequence)
        text_result = _safe_ostir_result_to_text(api_results)
        if text_result:
            return text_result
    except Exception as exc:
        last_error = exc

    if last_error is not None:
        raise RuntimeError(f"OSTIR Python API execution failed: {last_error}") from last_error
    raise RuntimeError("OSTIR Python API execution failed: empty output returned.")

    return ""


def _path_prefix_values(path_value: str, max_items: int = 12) -> List[str]:
    entries: List[str] = []
    for item in path_value.split(os.pathsep):
        item = item.strip().strip('"')
        if item:
            entries.append(item)
        if len(entries) >= max_items:
            break
    return entries


def _command_locations(command_names: Tuple[str, ...]) -> Dict[str, str]:
    return {name: (shutil.which(name) or "<missing>") for name in _normalize_command_names(command_names)}


def _log_viennarna_startup_context(candidate_dirs: List[Path]) -> None:
    print(
        "[Startup] Python executable: {}".format(sys.executable),
        file=sys.stderr,
        flush=True,
    )
    print(
        "[Startup] Python prefix/base_prefix: {}/{}".format(
            sys.prefix, sys.base_prefix
        ),
        file=sys.stderr,
        flush=True,
    )
    print(
        "[Startup] Environment OSTIR_BIN: {}".format(os.environ.get("OSTIR_BIN", "<unset>")),
        file=sys.stderr,
        flush=True,
    )
    print(
        "[Startup] Environment CONDA_PREFIX: {}".format(os.environ.get("CONDA_PREFIX", "<unset>")),
        file=sys.stderr,
        flush=True,
    )
    print(
        "[Startup] Environment CONDA_ENV_DIR: {}".format(os.environ.get("CONDA_ENV_DIR", "<unset>")),
        file=sys.stderr,
        flush=True,
    )
    print(
        "[Startup] Environment RBS_CAL_CONDA_ENV: {}".format(os.environ.get("RBS_CAL_CONDA_ENV", "<unset>")),
        file=sys.stderr,
        flush=True,
    )
    print(
        "[Startup] Environment RBS_CAL_VENV: {}".format(os.environ.get("RBS_CAL_VENV", "<unset>")),
        file=sys.stderr,
        flush=True,
    )
    print(
        "[Startup] PATH preview: {}".format(" | ".join(_path_prefix_values(os.environ.get("PATH", "")))),
        file=sys.stderr,
        flush=True,
    )
    print(
        "[Startup] ViennaRNA candidate dirs (limit 20):",
        file=sys.stderr,
        flush=True,
    )
    for index, directory in enumerate(_shorten_list([str(p) for p in candidate_dirs], 20), start=1):
        print(f"  [{index:02d}] {directory}", file=sys.stderr, flush=True)

    module_status = "ok" if _has_vienna_module() else "missing RNA module"
    print(f"[Startup] ViennaRNA Python module: {module_status}", file=sys.stderr, flush=True)
    for binary, resolved in _command_locations(VIENNARNA_BINARIES).items():
        print(f"[Startup] ViennaRNA command on PATH: {binary} -> {resolved}", file=sys.stderr, flush=True)


def _normalize_command_names(names: Tuple[str, ...]) -> List[str]:
    normalized: List[str] = []
    seen = set()
    for value in names:
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def _candidate_viennarna_dirs() -> List[Path]:
    venv_dir = Path(__file__).resolve().parent
    python_dir = Path(sys.executable).resolve().parent
    python_root = python_dir.parent
    repo_dir = venv_dir.resolve()
    base_prefix = Path(sys.base_prefix)
    candidates: List[Path] = [
        repo_dir,
        repo_dir / "bin",
        repo_dir / "libs",
        repo_dir / "libs" / "ViennaRNA",
        repo_dir / "libs" / "ViennaRNA" / "bin",
        python_dir,
        python_root,
        python_root / "Scripts",
        python_root / "bin",
        base_prefix,
        base_prefix / "Scripts",
        base_prefix / "bin",
        base_prefix / "Lib" / "site-packages",
        base_prefix / "lib" / "site-packages",
        venv_dir / ".venv" / "Lib" / "site-packages",
        venv_dir / ".venv" / "Lib" / "site-packages" / "RNA" / "bin",
    ]

    if os.name == "nt":
        candidates.extend(
            [
                Path(os.environ.get("APPDATA", "")) / "Python",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python",
                Path(os.environ.get("ProgramW6432", "")),
                Path(os.environ.get("ProgramFiles", "")),
                Path(os.environ.get("ProgramFiles(x86)", "")),
            ]
        )

    try:
        import RNA  # type: ignore

        if RNA.__file__:
            root = Path(RNA.__file__).resolve().parent
            candidates.extend(
                [
                    root,
                    root.parent,
                    root / "bin",
                    root.parent / "bin",
                    root.parent / "Scripts",
                    root.parent / "Scripts" / "bin",
                ]
            )
    except Exception:
        pass

    for env_var in ("CONDA_PREFIX", "CONDA_ENV_DIR", "RBS_CAL_CONDA_ENV", "RBS_CAL_VENV"):
        env_dir = Path(os.environ.get(env_var, ""))
        if not str(env_dir):
            continue
        candidates.extend(
            [
                env_dir,
                env_dir / "bin",
                env_dir / "Scripts",
                env_dir / "Library" / "bin",
            ]
        )

    uniq: List[Path] = []
    seen = set()
    for value in candidates:
        try:
            value_str = str(value)
        except Exception:
            continue
        if not value_str:
            continue
        if value_str in seen:
            continue
        seen.add(value_str)
        if value.exists():
            uniq.append(value)
    return uniq


def _missing_viennarna_bins() -> List[str]:
    missing: List[str] = []
    for binary in _normalize_command_names(VIENNARNA_BINARIES):
        if shutil.which(binary) is None:
            missing.append(binary)
    return missing


def _has_vienna_module() -> bool:
    try:
        import RNA  # type: ignore
    except Exception:
        return False
    return True


def _ensure_viennarna_in_path(candidate_dirs: Optional[List[Path]] = None) -> List[str]:
    missing = _missing_viennarna_bins()
    if not missing:
        return []

    current_parts = {
        p.strip().strip('"')
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p.strip()
    }
    if candidate_dirs is None:
        candidate_dirs = _candidate_viennarna_dirs()

    added_dirs: List[str] = []
    for base in candidate_dirs:
        for candidate_dir in (base, base / "bin"):
            if not candidate_dir.is_dir():
                continue
            candidate = str(candidate_dir)
            if candidate in current_parts:
                continue
            os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
            added_dirs.append(candidate)
            current_parts.add(candidate)

    if added_dirs:
        sample = _shorten_list(added_dirs, 12)
        print(
            "[Startup] Added PATH candidates for ViennaRNA scan: {}".format(" | ".join(sample)),
            file=sys.stderr,
            flush=True,
        )

    missing = _missing_viennarna_bins()
    return missing


def _vienna_dependency_hint() -> str:
    if os.name == "nt":
        return (
            "Install ViennaRNA CLI into the same environment and ensure the bin dir is on PATH. "
            "Example (conda): conda install -y -p <env> -c conda-forge -c bioconda viennarna. "
            "For Windows conda env, <env>\\Library\\bin is typically required. "
            "If bundled binaries are shipped with this package, place RNAfold, RNAsubopt, "
            "RNAeval in a local `bin` directory."
        )
    return (
        "Install ViennaRNA CLI (RNAfold, RNAsubopt, RNAeval) in the active environment. "
        "Example (conda): conda install -y -c conda-forge -c bioconda viennarna. "
        "Example (Homebrew): brew install viennarna."
    )


def _check_viennarna_dependencies() -> None:
    global _VIENNARNA_READY
    if _VIENNARNA_READY is True:
        return

    candidate_dirs = _candidate_viennarna_dirs()
    _log_viennarna_startup_context(candidate_dirs)

    missing = _ensure_viennarna_in_path(candidate_dirs)
    if not missing:
        for binary, resolved in _command_locations(VIENNARNA_BINARIES).items():
            print(
                f"[Startup] ViennaRNA command available: {binary} -> {resolved}",
                file=sys.stderr,
                flush=True,
            )
        _VIENNARNA_READY = True
        return

    _VIENNARNA_READY = False
    module_status = "ok" if _has_vienna_module() else "missing RNA module"
    hint = _vienna_dependency_hint()
    for binary, resolved in _command_locations(VIENNARNA_BINARIES).items():
        print(
            f"[Startup] ViennaRNA command still missing or unresolved: {binary} -> {resolved}",
            file=sys.stderr,
            flush=True,
        )
    raise RuntimeError(
        "ViennaRNA command dependencies are missing in PATH. "
        f"Missing: {', '.join(missing)}. "
        "Expected: RNAfold, RNAsubopt, RNAeval. "
        f"Python RNA module status: {module_status}. "
        f"{hint}"
    )


def _humanize_ostir_error(stderr: str, stdout: str, returncode: int) -> str:
    text = "\n".join(part.strip() for part in [stderr, stdout] if part and part.strip())
    if not text:
        return f"OSTIR execution failed (exit={returncode})."

    if OSTIR_MODULE_HINT_RNA in text:
        return (
            "OSTIR dependency missing: ViennaRNA Python module (RNA) not found. "
            "Install in the same environment with: pip install ViennaRNA "
            "and then restart this app."
        )
    if (
        VIENNARNA_PATH_HINT in text
        or VIENNARNA_MISSING_HINT in text
        or "viennarn" in text.lower()
    ):
        locations = []
        for binary in _normalize_command_names(VIENNARNA_BINARIES):
            which = shutil.which(binary)
            if which:
                locations.append(f"{binary}: {which}")
            else:
                locations.append(f"{binary}: <missing>")
        return (
            "OSTIR runtime dependency issue: ViennaRNA command-line binaries are not ready in PATH. "
            "Ensure RNAfold, RNAsubopt, RNAeval are installed and discoverable. "
            + " ".join(locations) +
            " " +
            _vienna_dependency_hint()
        )

    return f"OSTIR failed (exit={returncode}): {text}"


def _coerce_cell(value: str) -> Any:
    if value == "":
        return value

    if value.lower() in {"nan", "na", "none", "null"}:
        return value

    try:
        if re.fullmatch(r"[+-]?\d+", value):
            return int(value)
        return float(value)
    except ValueError:
        return value


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(raw: Optional[str]) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_csv_output(raw: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    sio = io.StringIO(raw)
    # Skip blank lines so DictReader gets a valid header.
    lines = [line for line in sio if line.strip()]
    if not lines:
        return [], []

    text = "".join(lines)
    sio = io.StringIO(text)

    sample = lines[0].strip()
    if "," not in sample:
        return [], []

    reader = csv.DictReader(sio)
    rows = [dict(row) for row in reader if any(v.strip() for v in row.values())]
    if not reader.fieldnames:
        return [], []

    required_columns = {"start_codon", "start_position"}
    if required_columns.intersection(reader.fieldnames):
        columns = list(reader.fieldnames)
        for row in rows:
            for key, value in row.items():
                row[key] = _coerce_cell(value.strip())
        return columns, rows

    # If headers are not recognized as CSV output, ignore.
    return [], []


def parse_table_output(raw: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    lines = [line.rstrip() for line in raw.splitlines()]
    header_line_index: Optional[int] = None
    headers: List[str] = []

    for idx, line in enumerate(lines):
        normalized = re.sub(r"\s+", " ", line).strip()
        if not normalized:
            continue
        if normalized.replace("_", "") == "":
            continue
        tokens = normalized.split(" ")
        has_header = "start_codon" in tokens and "start_position" in tokens
        if has_header:
            header_line_index = idx
            headers = [h for h in tokens if h]
            break

    if header_line_index is None:
        return [], []

    rows: List[Dict[str, Any]] = []
    for line in lines[header_line_index + 1 :]:
        cleaned = re.sub(r"\s{2,}", " ", line).strip()
        if not cleaned:
            continue
        if re.fullmatch(r"[-_]+", cleaned):
            continue

        parts = cleaned.split(" ")
        if len(parts) < len(headers):
            continue

        row_values = parts[: len(headers)]
        row = {headers[i]: _coerce_cell(row_values[i]) for i in range(len(headers))}
        rows.append(row)

    return headers, rows


def parse_ostir_output(raw: str) -> Tuple[List[str], List[Dict[str, Any]]]:
    csv_columns, csv_rows = parse_csv_output(raw)
    if csv_columns:
        return csv_columns, csv_rows

    table_columns, table_rows = parse_table_output(raw)
    return table_columns, table_rows


def normalize_sequence(raw: str) -> str:
    return re.sub(r"[^ACGTUNRYSWKMBDHVNacgtunryswkmbdvh]", "", raw).upper()


def _looks_like_sequence_text(value: str, min_length: int = 8) -> bool:
    normalized = normalize_sequence(value)
    if len(normalized) < min_length:
        return False
    return bool(re.fullmatch(r"[ACGTUNRYSWKMBDHVN]+", normalized))


def extract_first_csv_sequence(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""

    if not text.strip():
        return ""

    try:
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except Exception:
        dialect = csv.excel

    try:
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    except Exception:
        # Fallback: extract from raw token pattern.
        matches = re.findall(r"[ACGTUNRYSWKMBDHVN]{8,}", text, flags=re.IGNORECASE)
        for match in matches:
            candidate = normalize_sequence(match)
            if _looks_like_sequence_text(candidate, min_length=8):
                return candidate
        return ""

    preferred = {
        "sequence",
        "seq",
        "dna",
        "nucleotide",
        "nt",
        "cds",
        "cdssequence",
        "codingsequence",
    }

    if not reader.fieldnames:
        matches = re.findall(r"[ACGTUNRYSWKMBDHVN]{8,}", text, flags=re.IGNORECASE)
        for match in matches:
            candidate = normalize_sequence(match)
            if _looks_like_sequence_text(candidate, min_length=8):
                return candidate
        return ""

    for row in reader:
        for key in reader.fieldnames:
            raw_key = (key or "").strip()
            if not raw_key:
                continue
            value = normalize_sequence(str(row.get(raw_key, "")))
            if _looks_like_sequence_text(value, min_length=8):
                return value

            normalized_key = raw_key.lower().replace("-", "").replace("_", "")
            if normalized_key in preferred and _looks_like_sequence_text(value, min_length=8):
                return value

        fallback_candidates: List[str] = []
        for value in row.values():
            normalized = normalize_sequence(str(value))
            if _looks_like_sequence_text(normalized, min_length=8):
                fallback_candidates.append(normalized)
        if fallback_candidates:
            return max(fallback_candidates, key=len)

    # As a final fallback, scan entire file content.
    matches = re.findall(r"[ACGTUNRYSWKMBDHVN]{8,}", text, flags=re.IGNORECASE)
    for match in matches:
        candidate = normalize_sequence(match)
        if _looks_like_sequence_text(candidate, min_length=8):
            return candidate
    return ""


def extract_first_fasta_sequence(path: Path) -> str:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    seq_parts: List[str] = []
    in_sequence = False

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if in_sequence:
                break
            in_sequence = True
            continue
        if in_sequence:
            seq_parts.append(re.sub(r"\s+", "", line))

    return normalize_sequence("".join(seq_parts))


def build_sequence_context(sequence: str, start_position: Any, flank_bp: int = 20) -> Dict[str, Any]:
    try:
        start = int(start_position)
    except (TypeError, ValueError):
        return {}

    if start <= 0 or not sequence:
        return {}

    start_idx = max(1, start - flank_bp)
    # Include full codon context after start codon start position.
    end_idx = min(len(sequence), start + flank_bp + 2)
    if start_idx > len(sequence) or end_idx < 1 or end_idx < start_idx:
        return {}

    return {
        "context_start_position": start_idx,
        "context_end_position": end_idx,
        "sequence_context": sequence[start_idx - 1 : end_idx],
    }


def _format_sequence(raw: str, keep_rna: bool = False) -> str:
    value = normalize_sequence(raw)
    if not keep_rna:
        return value.replace("U", "T")
    return value


def _truncate_design_sequences(
    pre_seq: str, post_seq: str
) -> Tuple[str, str, List[str], Dict[str, Any]]:
    pre_original_len = len(pre_seq)
    post_original_len = len(post_seq)

    warnings: List[str] = []
    truncation_info: Dict[str, Any] = {
        "pre": {
            "input_length": pre_original_len,
            "used_length": min(pre_original_len, RBS_DESIGN_PRESEQ_MAX_BP),
            "max_length": RBS_DESIGN_PRESEQ_MAX_BP,
            "truncated": pre_original_len > RBS_DESIGN_PRESEQ_MAX_BP,
        },
        "cds": {
            "input_length": post_original_len,
            "used_length": min(post_original_len, RBS_DESIGN_CDS_MAX_BP),
            "max_length": RBS_DESIGN_CDS_MAX_BP,
            "truncated": post_original_len > RBS_DESIGN_CDS_MAX_BP,
        },
    }

    if pre_original_len > RBS_DESIGN_PRESEQ_MAX_BP:
        pre_seq = pre_seq[-RBS_DESIGN_PRESEQ_MAX_BP :]
        warnings.append(
            f"Pre-sequence was longer than {RBS_DESIGN_PRESEQ_MAX_BP} bp. "
            f"Only the nearest {RBS_DESIGN_PRESEQ_MAX_BP} bp to RBS was kept "
            f"({pre_original_len} -> {len(pre_seq)})."
        )

    if post_original_len > RBS_DESIGN_CDS_MAX_BP:
        post_seq = post_seq[:RBS_DESIGN_CDS_MAX_BP]
        warnings.append(
            f"CDS sequence was longer than {RBS_DESIGN_CDS_MAX_BP} bp. "
            f"Only the first {RBS_DESIGN_CDS_MAX_BP} bp from the start codon was kept "
            f"({post_original_len} -> {len(post_seq)})."
        )

    return pre_seq, post_seq, warnings, truncation_info


def _evaluate_design_candidate_full_sequence(
    pre_seq: str,
    post_seq: str,
    rbs_seq: str,
    target_log: float,
    ostir_binary: str,
    asd: str = DEFAULT_ASD,
    threads: int = 1,
    start_codon: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not rbs_seq:
        return None

    expected_start = len(pre_seq) + len(rbs_seq) + 1
    expected_start_codon = (start_codon or post_seq[:3]).upper()
    full_seq = pre_seq + rbs_seq + post_seq

    row = run_ostir_for_start_position(
        sequence=full_seq,
        ostir_binary=ostir_binary,
        expected_start=expected_start,
        asd=asd,
        threads=threads,
        post_seq=post_seq,
    )

    if not row:
        return {
            "rbs_sequence": rbs_seq,
            "full_sequence": full_seq,
            "start_position": None,
            "start_codon": expected_start_codon,
            "predicted_expression": 0.0,
            "error": float("inf"),
            "row": {},
            "rejected": True,
            "reject_reason": "no_valid_ostir_row",
        }

    expr = _coerce_float(row.get("expression"))
    if expr is None or expr <= 0:
        return {
            "rbs_sequence": rbs_seq,
            "full_sequence": full_seq,
            "start_position": _coerce_float(row.get("start_position")),
            "start_codon": str(row.get("start_codon", "")).upper() or expected_start_codon,
            "predicted_expression": 0.0,
            "error": float("inf"),
            "row": row,
            "rejected": True,
            "reject_reason": "non_positive_expression",
        }

    observed_codon = str(row.get("start_codon", "")).upper()
    if observed_codon != expected_start_codon:
        return {
            "rbs_sequence": rbs_seq,
            "full_sequence": full_seq,
            "start_position": _coerce_float(row.get("start_position")),
            "start_codon": observed_codon,
            "predicted_expression": 0.0,
            "error": float("inf"),
            "row": row,
            "rejected": True,
            "reject_reason": "start_codon_mismatch",
        }

    observed_position = _coerce_float(row.get("start_position"))
    if observed_position is None or int(observed_position) != expected_start:
        return {
            "rbs_sequence": rbs_seq,
            "full_sequence": full_seq,
            "start_position": observed_position,
            "start_codon": observed_codon,
            "predicted_expression": 0.0,
            "error": float("inf"),
            "row": row,
            "rejected": True,
            "reject_reason": "start_position_mismatch",
        }

    predicted_expr = max(expr, 1e-12)
    err = abs(math.log10(predicted_expr) - target_log)
    return {
        "rbs_sequence": rbs_seq,
        "full_sequence": full_seq,
        "start_position": expected_start,
        "start_codon": expected_start_codon,
        "predicted_expression": predicted_expr,
        "error": err,
        "row": row,
        "rejected": False,
    }


def run_ostir_row_for_sequence(
    sequence: str,
    ostir_binary: str,
    asd: str = DEFAULT_ASD,
    threads: int = 1,
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> List[Dict[str, Any]]:
    cmd: List[str] = [ostir_binary, "-i", sequence, "-t", "string"]

    if asd:
        cmd += ["-a", asd]
    if threads > 0:
        cmd += ["-j", str(threads)]
    if start is not None and start > 0:
        cmd += ["-s", str(start)]
    if end is not None and end > 0:
        cmd += ["-e", str(end)]

    stdout = run_ostir_command(cmd)
    if not stdout:
        return []

    columns, rows = parse_ostir_output(stdout)
    if not columns:
        if "no binding sites were identified" in stdout.lower():
            return []
        raise RuntimeError("Failed to parse OSTIR output for design candidate.")

    return rows


def _iter_env_dirs() -> List[Path]:
    directories: List[Path] = []
    path_env = os.environ.get("PATH", "")
    for item in path_env.split(os.pathsep):
        item = item.strip()
        if item:
            directories.append(Path(item))
    for env_key in ("CONDA_PREFIX", "CONDA_ROOT"):
        root = os.environ.get(env_key)
        if root:
            directories.append(Path(root) / "Scripts")
            directories.append(Path(root) / "bin")
    return directories


def _glob_candidate_paths(base: Path, pattern: str) -> List[Path]:
    try:
        return list(base.glob(pattern))
    except OSError:
        return []


def _candidate_paths() -> List[str]:
    configured = (OSTIR_BIN or "").strip().strip('"')
    if not configured:
        configured = "ostir"

    script_dir = Path(__file__).resolve().parent
    python_dir = Path(sys.executable).resolve().parent

    search_names = ["ostir", "ostir.py"]
    if os.name == "nt":
        search_names.extend(
            ["ostir.exe", "ostir.bat", "ostir.cmd", "ostir-script.py", "ostir-script.pyw"]
        )

    candidate_files: List[str] = []
    if configured not in ("", "ostir"):
        candidate_files.append(configured)

    search_dirs = [
        script_dir,
        script_dir / ".venv" / "Scripts",
        script_dir / ".venv" / "bin",
        python_dir,
        python_dir / "Scripts",
        python_dir / "bin",
    ]
    if os.name == "nt":
        search_dirs.extend([Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin"])
    else:
        search_dirs.extend([Path.home() / ".local" / "bin"])

    conda_prefix = os.environ.get("CONDA_PREFIX")
    if conda_prefix:
        search_dirs.append(Path(conda_prefix) / "Scripts")
        search_dirs.append(Path(conda_prefix) / "bin")
    conda_env_dir = (
        os.environ.get("CONDA_ENV_DIR")
        or os.environ.get("RBS_CAL_CONDA_ENV")
        or os.environ.get("RBS_CAL_VENV")
    )
    if conda_env_dir:
        search_dirs.append(Path(conda_env_dir) / "Scripts")
        search_dirs.append(Path(conda_env_dir) / "bin")
    if os.name == "nt":
        search_dirs.append(Path(__file__).resolve().parent / ".conda_venv" / "Scripts")

    for directory in search_dirs:
        for name in search_names:
            candidate_files.append(str(directory / name))

    for name in search_names:
        located = shutil.which(name)
        if located:
            candidate_files.append(located)

    for directory in _iter_env_dirs():
        for name in search_names:
            candidate_files.append(str(directory / name))

    if os.name == "nt":
        for base in (
            Path(os.environ.get("ProgramW6432", "")),
            Path(os.environ.get("ProgramFiles", "")),
            Path(os.environ.get("ProgramFiles(x86)", "")),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
            Path(os.environ.get("APPDATA", "")) / "Python",
        ):
            if str(base) and base.exists():
                candidate_files.extend(
                    str(candidate)
                    for candidate in _glob_candidate_paths(
                        base, "Python*/Scripts/ostir*"
                    )
                )
                for name in search_names:
                    candidate_files.extend(
                        str(candidate)
                        for candidate in _glob_candidate_paths(
                            base, "Python*/Scripts/" + name + ".*"
                        )
                    )

    # dedupe preserving order
    seen: set[str] = set()
    ordered: List[str] = []
    for value in candidate_files:
        if value and value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def get_ostir_binary() -> str:
    configured = (OSTIR_BIN or "").strip().strip('"')
    if not configured:
        configured = "ostir"

    for candidate in _candidate_paths():
        located = shutil.which(candidate)
        if located:
            candidate_path = Path(located)
            if candidate_path.is_file():
                return str(candidate_path)

        candidate_path = Path(candidate).expanduser()
        if candidate_path.is_file():
            return str(candidate_path)

    searched = ", ".join(_candidate_paths()[:20])
    raise RuntimeError(
        f"OSTIR executable not found: {configured}. "
        "Add to PATH or set OSTIR_BIN to a full executable path. "
        f"Searched: {searched}"
    )


def detect_input_type(path: Path) -> str:
    preview = ""
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        preview = handle.read(2048).lstrip()

    if preview.startswith(">"):
        return "fasta"

    first_line = preview.splitlines()[0] if preview else ""
    if re.search(r"\b(id|name|seq|sequence)\b", first_line, flags=re.I):
        return "csv"

    ext = path.suffix.lower()
    if ext in {".fasta", ".fa", ".fas", ".fna", ".ffn"}:
        return "fasta"
    if ext in {".csv", ".tsv", ".txt"}:
        return "csv"

    return "string"


def run_ostir_command(cmd: List[str]) -> str:
    _check_viennarna_dependencies()

    if _OSTIR_RUN is not None:
        params: Dict[str, Any] = {"start": 0, "end": 0, "asd": "", "threads": 1, "otype": "string"}
        path_or_seq = ""
        i = 0
        while i < len(cmd):
            token = cmd[i]
            if token == "-i" and i + 1 < len(cmd):
                path_or_seq = cmd[i + 1]
            elif token == "-s" and i + 1 < len(cmd):
                try:
                    params["start"] = int(cmd[i + 1])
                except ValueError:
                    params["start"] = 0
            elif token == "-e" and i + 1 < len(cmd):
                try:
                    params["end"] = int(cmd[i + 1])
                except ValueError:
                    params["end"] = 0
            elif token == "-a" and i + 1 < len(cmd):
                params["asd"] = cmd[i + 1]
            elif token == "-j" and i + 1 < len(cmd):
                try:
                    params["threads"] = int(cmd[i + 1])
                except ValueError:
                    params["threads"] = 1
            elif token == "-t" and i + 1 < len(cmd):
                params["otype"] = (cmd[i + 1] or "string").lower()
                if params["otype"] in {"fasta", "csv"}:
                    params["otype"] = params["otype"]
            i += 1

        if params.get("otype") != "string" and path_or_seq and os.path.isfile(path_or_seq):
            extracted_seq = ""
            if params["otype"] == "fasta":
                extracted_seq = extract_first_fasta_sequence(Path(path_or_seq))
            elif params["otype"] == "csv":
                extracted_seq = extract_first_csv_sequence(Path(path_or_seq))

            if extracted_seq:
                path_or_seq = extracted_seq
                params["otype"] = "string"

        if params.get("otype") == "string" and path_or_seq:
            cached = _run_ostir_api_cached(
                path_or_seq,
                params["start"],
                params["end"],
                params["asd"] or DEFAULT_ASD,
                params["threads"],
                params["otype"],
            )
            if cached:
                return cached

    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=OSTIR_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"OSTIR executable not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"OSTIR execution timed out after {OSTIR_TIMEOUT_SECONDS} seconds."
        ) from exc
    except OSError as exc:
        raise RuntimeError(f"Failed to execute OSTIR command: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise RuntimeError(_humanize_ostir_error(stderr=stderr, stdout=stdout, returncode=result.returncode))

    return result.stdout.strip()


def run_ostir_for_start_position(
    sequence: str,
    ostir_binary: str,
    expected_start: int,
    asd: str = DEFAULT_ASD,
    threads: int = 1,
    post_seq: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    rows = run_ostir_row_for_sequence(
        sequence=sequence,
        ostir_binary=ostir_binary,
        asd=asd,
        threads=threads,
        start=expected_start,
    )

    if not rows:
        return None

    if post_seq:
        expected_codon = post_seq[:3].upper()
        for row in rows:
            if (
                _coerce_float(row.get("start_position")) == expected_start
                and str(row.get("start_codon", "")).upper() == expected_codon
            ):
                return row
        return None

    for row in rows:
        if _coerce_float(row.get("start_position")) == expected_start:
            return row
    return None


def random_rbs(
    rnd: random.Random,
    min_length: int,
    max_length: int,
    seed: str = "",
    spacing_min: int = DESIGN_SD_SPACING_MIN,
    spacing_max: int = DESIGN_SD_SPACING_MAX,
    sd_cores: Optional[List[str]] = None,
) -> str:
    min_length = max(4, min_length)
    max_length = max(min_length, max_length)
    length = rnd.randint(min_length, max_length)
    if sd_cores is None:
        sd_cores = [DESIGN_SD_CORE]
    sd_cores = [core for core in sd_cores if core]
    if not sd_cores:
        sd_cores = [DESIGN_SD_CORE]

    feasible_spacings = [
        spacing
        for spacing in range(spacing_min, spacing_max + 1)
        if any(len(core) + spacing <= length for core in sd_cores)
    ]
    if feasible_spacings:
        spacing = rnd.choice(feasible_spacings)
        valid_cores = [core for core in sd_cores if len(core) + spacing <= length]
        if not valid_cores:
            valid_cores = [sd_cores[0]]
        sd_core = rnd.choice(valid_cores)
        core_start = length - len(sd_core) - spacing
        left = "".join(rnd.choice(RBS_NUCLEOTIDES) for _ in range(core_start))
        right = "".join(rnd.choice(RBS_NUCLEOTIDES) for _ in range(length - core_start - len(sd_core)))
        return left + sd_core + right

    if seed:
        canonical = (seed[:length]).ljust(length, "A")
        if len(canonical) > length:
            canonical = canonical[:length]
        return canonical

    canonical = sd_cores[0].ljust(length, "A")
    if len(canonical) > length:
        canonical = canonical[:length]
    return canonical


def mutate_rbs(
    rnd: random.Random,
    sequence: str,
    min_length: int,
    max_length: int,
    sub_weight: float = 1.0,
    ins_weight: float = 1.0,
    del_weight: float = 1.0,
) -> Tuple[str, str]:
    if not sequence:
        return random_rbs(rnd, min_length, max_length), "random"

    seq = list(sequence)
    choices = ["sub", "ins", "del"]
    weights = [sub_weight, ins_weight, del_weight]

    if len(seq) <= min_length:
        idx = choices.index("del")
        choices.pop(idx)
        weights.pop(idx)
    if len(seq) >= max_length:
        idx = choices.index("ins")
        choices.pop(idx)
        weights.pop(idx)
    if not choices:
        return "".join(seq), "noop"

    total_weight = sum(weights)
    if total_weight <= 0:
        action = choices[0]
    else:
        action = rnd.choices(choices, weights=weights, k=1)[0]

    if action == "sub":
        idx = rnd.randrange(len(seq))
        replacements = [nt for nt in RBS_NUCLEOTIDES if nt != seq[idx]]
        seq[idx] = rnd.choice(replacements)
        return "".join(seq), "sub"
    if action == "ins" and len(seq) < max_length:
        idx = rnd.randrange(len(seq) + 1)
        seq.insert(idx, rnd.choice(RBS_NUCLEOTIDES))
        return "".join(seq), "ins"
    if action == "del" and len(seq) > min_length:
        idx = rnd.randrange(len(seq))
        del seq[idx]
        return "".join(seq), "del"
    return "".join(seq), "noop"


def design_rbs_candidates(
    pre_seq: str,
    post_seq: str,
    target_expression: float,
    ostir_binary: str,
    asd: str = DEFAULT_ASD,
    threads: int = 1,
    min_length: int = 6,
    max_length: int = 12,
    iterations: int = 40,
    top_n: int = 10,
    random_seed: Optional[str] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]], Dict[str, Any]]:
    if iterations <= 0 or top_n <= 0:
        return [], None, {
            "trace": [],
            "restart_log": [],
            "move_type_attempts": {"sub": 0, "ins": 0, "del": 0, "noop": 0, "random": 0},
            "move_type_accepts": {"sub": 0, "ins": 0, "del": 0, "noop": 0, "random": 0},
            "restart_count": 0,
            "accept_window": DESIGN_ACCEPT_WINDOW,
            "iterations_requested": iterations,
            "temperature": {
                "init": DESIGN_TEMPERATURE_INIT,
                "min": DESIGN_TEMPERATURE_MIN,
                "max": DESIGN_TEMPERATURE_MAX,
            },
            "spacing_window": [DESIGN_SD_SPACING_MIN, DESIGN_SD_SPACING_MAX],
            "sd_cores": [core for core in DESIGN_SD_CORES if core],
            "early_exit": True,
        }

    rnd_seed = int(random_seed) if random_seed and random_seed.isdigit() else None
    rnd = random.Random(rnd_seed or random.randint(1, 2**31 - 1))

    min_length = max(4, min_length)
    max_length = max(min_length, max_length)
    if target_expression <= 0:
        raise ValueError("Target expression must be greater than 0")

    expected_start = len(pre_seq) + 1
    start_codon = post_seq[:3].upper()
    target_log = math.log10(target_expression)

    evaluated: Dict[str, Optional[Dict[str, Any]]] = {}
    top_candidates: List[Dict[str, Any]] = []
    best_candidate: Optional[Dict[str, Any]] = None
    best_error = float("inf")
    best_iteration: Optional[int] = None

    sd_cores = [core for core in DESIGN_SD_CORES if core]
    pool_size = max(4, min(12, max(4, iterations // 5)))
    seed_pool: List[str] = []
    for _ in range(pool_size):
        candidate = random_rbs(
            rnd,
            min_length=min_length,
            max_length=max_length,
            sd_cores=sd_cores,
            spacing_min=DESIGN_SD_SPACING_MIN,
            spacing_max=DESIGN_SD_SPACING_MAX,
        )
        if candidate not in seed_pool:
            seed_pool.append(candidate)
        if len(seed_pool) >= pool_size:
            break
    if not seed_pool:
        seed_pool = [random_rbs(rnd, min_length, max_length)]
    pool_index = 0

    temperature = DESIGN_TEMPERATURE_INIT
    current_error = float("inf")
    current_rbs = ""
    stagnation_count = 0
    restart_patience = max(1, DESIGN_RESTART_PATIENCE)
    accept_window = max(4, min(DESIGN_ACCEPT_WINDOW, iterations))
    accept_history: List[bool] = []
    trace_interval = max(10, min(50, max(1, iterations // 10)))
    restart_count = 0
    move_type_attempts = {"sub": 0, "ins": 0, "del": 0, "noop": 0, "random": 0}
    move_type_accepts = {"sub": 0, "ins": 0, "del": 0, "noop": 0, "random": 0}
    diagnostics = {
        "trace": [],
        "restart_log": [],
        "move_type_attempts": move_type_attempts,
        "move_type_accepts": move_type_accepts,
        "restart_count": 0,
        "accept_window": accept_window,
        "iterations_requested": iterations,
        "temperature": {
            "init": DESIGN_TEMPERATURE_INIT,
            "min": DESIGN_TEMPERATURE_MIN,
            "max": DESIGN_TEMPERATURE_MAX,
        },
        "spacing_window": [DESIGN_SD_SPACING_MIN, DESIGN_SD_SPACING_MAX],
        "sd_cores": sd_cores,
        "early_exit": False,
        "best_iteration": None,
    }

    def build_invalid_candidate(
        rbs_seq: str,
        full_seq: str,
        reason: str,
        row: Optional[Dict[str, Any]] = None,
        observed_position: Optional[float] = None,
        observed_codon: str = "",
    ) -> Dict[str, Any]:
        return {
            "rbs_sequence": rbs_seq,
            "full_sequence": full_seq,
            "start_position": observed_position if observed_position is not None else None,
            "start_codon": observed_codon if observed_codon else post_seq[:3].upper(),
            "predicted_expression": 0.0,
            "error": float("inf"),
            "row": row or {},
            "rejected": True,
            "reject_reason": reason,
        }

    def infer_spacing_from_sequence(sequence: str) -> Optional[int]:
        for core in sd_cores:
            core_len = len(core)
            for idx in range(max(0, len(sequence) - core_len), -1, -1):
                if sequence[idx : idx + core_len] == core:
                    spacing = len(sequence) - (idx + core_len)
                    if DESIGN_SD_SPACING_MIN <= spacing <= DESIGN_SD_SPACING_MAX:
                        return spacing
        return None

    def ensure_cache(rbs_seq: str) -> Optional[Dict[str, Any]]:
        if rbs_seq in evaluated:
            return evaluated[rbs_seq]

        full_seq = pre_seq + rbs_seq + post_seq
        row = run_ostir_for_start_position(
            sequence=full_seq,
            ostir_binary=ostir_binary,
            expected_start=expected_start + len(rbs_seq),
            asd=asd,
            threads=threads,
            post_seq=post_seq,
        )
        if not row:
            invalid = build_invalid_candidate(
                rbs_seq=rbs_seq,
                full_seq=full_seq,
                reason="no_valid_ostir_row",
            )
            evaluated[rbs_seq] = invalid
            return invalid

        expr = _coerce_float(row.get("expression"))
        if expr is None or expr <= 0:
            invalid = build_invalid_candidate(
                rbs_seq=rbs_seq,
                full_seq=full_seq,
                reason="non_positive_expression",
                row=row,
                observed_position=_coerce_float(row.get("start_position")),
                observed_codon=str(row.get("start_codon", "")).upper(),
            )
            evaluated[rbs_seq] = invalid
            return invalid

        observed_codon = str(row.get("start_codon", "")).upper()
        if observed_codon != start_codon:
            invalid = build_invalid_candidate(
                rbs_seq=rbs_seq,
                full_seq=full_seq,
                reason="start_codon_mismatch",
                row=row,
                observed_position=_coerce_float(row.get("start_position")),
                observed_codon=observed_codon,
            )
            evaluated[rbs_seq] = invalid
            return invalid

        expected_pos = expected_start + len(rbs_seq)
        observed_pos = _coerce_float(row.get("start_position"))
        if observed_pos is None or int(observed_pos) != expected_pos:
            invalid = build_invalid_candidate(
                rbs_seq=rbs_seq,
                full_seq=full_seq,
                reason="start_position_mismatch",
                row=row,
                observed_position=observed_pos,
                observed_codon=observed_codon,
            )
            evaluated[rbs_seq] = invalid
            return invalid

        predicted_expr = max(expr, 1e-12)
        err = abs(math.log10(predicted_expr) - target_log)
        result = {
            "rbs_sequence": rbs_seq,
            "full_sequence": full_seq,
            "start_position": expected_pos,
            "start_codon": start_codon,
            "predicted_expression": predicted_expr,
            "error": err,
            "rejected": False,
            "row": row,
        }
        evaluated[rbs_seq] = result
        top_candidates.append(result)
        return result

    def current_move_weights(step: int, total_steps: int, current_temperature: float) -> Tuple[float, float, float]:
        ratio = 0.0
        if total_steps > 1:
            ratio = min(1.0, (step - 1) / max(1, total_steps - 1))
        sub_weight = 1.0 + 7.0 * ratio
        max_temp = max(DESIGN_TEMPERATURE_MAX, DESIGN_TEMPERATURE_INIT)
        temp_factor = (current_temperature - DESIGN_TEMPERATURE_MIN) / max(
            1e-12,
            max_temp - DESIGN_TEMPERATURE_MIN,
        )
        temp_factor = max(0.0, min(1.0, temp_factor))
        exploration_scale = 1.0 + 2.0 * temp_factor
        ins_weight = max(0.2, exploration_scale * (1.0 - 0.3 * ratio))
        del_weight = max(0.2, exploration_scale * (1.0 - 0.3 * ratio))
        return sub_weight, ins_weight, del_weight

    def restart_from_pool(restart_index: int) -> None:
        nonlocal current_rbs, current_error, stagnation_count, temperature, pool_index
        if pool_index < len(seed_pool):
            current_rbs = seed_pool[pool_index]
            pool_index += 1
        else:
            current_rbs = random_rbs(
                rnd,
                min_length=min_length,
                max_length=max_length,
                spacing_min=DESIGN_SD_SPACING_MIN,
                spacing_max=DESIGN_SD_SPACING_MAX,
                sd_cores=sd_cores,
            )

        result = ensure_cache(current_rbs)
        if result is not None and not result.get("rejected"):
            current_error = result["error"]
        else:
            current_error = float("inf")

        stagnation_count = 0
        spacing = infer_spacing_from_sequence(current_rbs)
        log_line = (
            f"[Restart {restart_index}] Initial sequence: {current_rbs} "
            f"(len={len(current_rbs)}, spacing={spacing if spacing is not None else 'N/A'})"
        )
        print(log_line)
        diagnostics["restart_log"].append(log_line)
        temperature = max(DESIGN_TEMPERATURE_MIN, min(DESIGN_TEMPERATURE_MAX, DESIGN_TEMPERATURE_INIT))
        diagnostics["restart_count"] = restart_index

    def accept_probability(delta: float, temp: float) -> float:
        if temp <= 0 or not math.isfinite(delta) or math.isinf(temp):
            return 0.0
        if delta <= 0:
            return 1.0
        return math.exp(-delta / temp)

    max_iter = max(1, iterations)
    iteration = 0
    while iteration < max_iter:
        restart_count += 1
        restart_from_pool(restart_count)
        inner_limit = min(restart_patience, max_iter - iteration)

        for _ in range(inner_limit):
            iteration += 1
            step = iteration

            if current_rbs:
                sub_weight, ins_weight, del_weight = current_move_weights(step, max_iter, temperature)
                candidate, move_type = mutate_rbs(
                    rnd,
                    current_rbs,
                    min_length=min_length,
                    max_length=max_length,
                    sub_weight=sub_weight,
                    ins_weight=ins_weight,
                    del_weight=del_weight,
                )
            else:
                candidate = random_rbs(
                    rnd,
                    min_length=min_length,
                    max_length=max_length,
                    spacing_min=DESIGN_SD_SPACING_MIN,
                    spacing_max=DESIGN_SD_SPACING_MAX,
                    sd_cores=sd_cores,
                )
                move_type = "random"

            move_type_attempts[move_type] = move_type_attempts.get(move_type, 0) + 1

            if candidate == current_rbs:
                accepted = False
                accept_history.append(False)
            else:
                result = ensure_cache(candidate)
                candidate_error = result["error"] if result else float("inf")
                rejected = bool(result is None or result.get("rejected"))
                if current_error == float("inf"):
                    accepted = (math.isfinite(candidate_error) and not rejected)
                else:
                    delta = candidate_error - current_error
                    acceptance_prob = accept_probability(delta, temperature)
                    accepted = acceptance_prob >= rnd.random() and not rejected

                if accepted:
                    current_rbs = candidate
                    current_error = candidate_error
                    move_type_accepts[move_type] = move_type_accepts.get(move_type, 0) + 1
                    if result is not None and not result.get("rejected") and candidate_error < best_error:
                        best_candidate = result
                        best_error = candidate_error
                        best_iteration = iteration
                        stagnation_count = 0
                    else:
                        stagnation_count += 1
                else:
                    stagnation_count += 1

                accept_history.append(accepted)

            if len(accept_history) > accept_window:
                accept_history.pop(0)
            accept_ratio = (
                sum(1 for value in accept_history if value) / float(len(accept_history))
                if accept_history
                else 0.0
            )
            if len(accept_history) == accept_window:
                if accept_ratio > 0.5:
                    temperature = max(DESIGN_TEMPERATURE_MIN, temperature * 0.5)
                elif accept_ratio < 0.05:
                    temperature = min(DESIGN_TEMPERATURE_MAX, temperature * 2.0)

            if best_candidate is None and not math.isinf(current_error):
                current_best = ensure_cache(current_rbs)
                if current_best is not None and not current_best.get("rejected"):
                    best_candidate = current_best
                    best_error = best_candidate["error"]
                    best_iteration = iteration

            if iteration % trace_interval == 0 or step == 1 or iteration == max_iter:
                trace = {
                    "iteration": iteration,
                    "temperature": temperature,
                    "accept_ratio": accept_ratio,
                    "current_error": current_error if math.isfinite(current_error) else float("inf"),
                    "best_error": best_error if math.isfinite(best_error) else float("inf"),
                    "current_rbs_length": len(current_rbs),
                    "restarts": restart_count,
                    "last_move": move_type,
                    "accepted": accepted,
                }
                diagnostics["trace"].append(trace)
                if progress_callback:
                    try:
                        progress_callback({
                            "status": "running",
                            "phase": "search",
                            "progress": iteration / max_iter if max_iter else 1.0,
                            "iteration": iteration,
                            "max_iteration": max_iter,
                            "temperature": temperature,
                            "accept_ratio": accept_ratio,
                            "current_error": trace["current_error"],
                            "best_error": trace["best_error"],
                            "move": move_type,
                        })
                    except Exception:
                        app.logger.debug("Progress callback failed.", exc_info=True)
                print(
                    "[iter {iteration:>4}] temp={temperature:.6f} accept_ratio={accept_ratio:.3f} "
                    "energy={current_error:.6f} best={best_error:.6f} move={last_move} accepted={accepted}".format(
                        **trace
                    )
                )

            if stagnation_count >= restart_patience:
                break

    unique_candidates = []
    seen = set()
    for item in sorted(top_candidates, key=lambda item: (item["error"], -item["predicted_expression"])):
        if item["rbs_sequence"] in seen:
            continue
        if not item["rbs_sequence"]:
            continue
        if item.get("rejected") or item["predicted_expression"] <= 0:
            continue
        unique_candidates.append(item)
        seen.add(item["rbs_sequence"])
        if len(unique_candidates) >= top_n:
            break

    diagnostics["best_error"] = best_error if math.isfinite(best_error) else float("inf")
    diagnostics["best_iteration"] = best_iteration
    return unique_candidates, best_candidate, diagnostics


def _coerce_non_negative_int(value: Optional[str], default: int, field_name: str) -> int:
    text = (value or "").strip()
    if not text:
        return default
    try:
        parsed = int(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    return parsed


def _parse_design_request(form_data: Dict[str, str]) -> Dict[str, Any]:
    pre_seq = (form_data.get("preSequence", "") or "").strip().replace("\r", "")
    post_seq = (form_data.get("postSequence", "") or "").strip().replace("\r", "")
    target = (form_data.get("targetExpression", "") or "").strip()
    asd = (form_data.get("antiSd", DEFAULT_ASD) or "").strip()
    threads = (form_data.get("threads", "1") or "1").strip()
    min_len = (form_data.get("rbsMinLength", "6") or "").strip()
    max_len = (form_data.get("rbsMaxLength", "12") or "").strip()
    iterations = (form_data.get("iterations", str(RBS_DESIGN_ITERATION_DEFAULT)) or "").strip()
    top_n = (form_data.get("topCandidates", str(RBS_DESIGN_CANDIDATES_DEFAULT)) or "").strip()
    random_seed = (form_data.get("randomSeed", DESIGN_RANDOM_SEED) or "").strip()

    full_pre_seq = _format_sequence(pre_seq)
    full_post_seq = _format_sequence(post_seq)
    pre_seq, post_seq, truncation_warnings, truncation_info = _truncate_design_sequences(
        full_pre_seq,
        full_post_seq,
    )

    if not pre_seq:
        raise ValueError("Pre-sequence input is required")
    if len(post_seq) < 3:
        raise ValueError("postSequence must include a start codon and CDS")
    if post_seq[:3].upper() not in START_CODONS:
        raise ValueError("postSequence must start with ATG, GTG, or TTG")

    if not target:
        raise ValueError("targetExpression must be a number")
    try:
        target_expression = float(target)
    except ValueError as exc:
        raise ValueError("targetExpression must be a number") from exc
    if target_expression <= 0:
        raise ValueError("targetExpression must be greater than 0")

    min_len_i = _coerce_non_negative_int(min_len, 6, "rbsMinLength")
    max_len_i = _coerce_non_negative_int(max_len, 12, "rbsMaxLength")
    if min_len_i < 3 or max_len_i < min_len_i:
        raise ValueError("Invalid RBS length range")

    iterations_i = _coerce_non_negative_int(iterations, RBS_DESIGN_ITERATION_DEFAULT, "iterations")
    top_n_i = _coerce_non_negative_int(top_n, RBS_DESIGN_CANDIDATES_DEFAULT, "topCandidates")
    if iterations_i <= 0 or top_n_i <= 0:
        raise ValueError("iterations and topCandidates must be positive")

    try:
        threads_count = int(threads)
    except ValueError as exc:
        raise ValueError("Threads must be an integer") from exc
    if threads_count <= 0:
        threads_count = 1

    return {
        "full_pre_seq": full_pre_seq,
        "full_post_seq": full_post_seq,
        "pre_seq": pre_seq,
        "post_seq": post_seq,
        "truncation_warnings": truncation_warnings,
        "truncation_info": truncation_info,
        "target_expression": target_expression,
        "asd": asd or DEFAULT_ASD,
        "threads_count": threads_count,
        "min_len_i": min_len_i,
        "max_len_i": max_len_i,
        "iterations_i": iterations_i,
        "top_n_i": top_n_i,
        "random_seed": random_seed,
    }


def _run_design_core(payload: Dict[str, Any], task_id: Optional[str] = None) -> Dict[str, Any]:
    pre_seq = str(payload["pre_seq"])
    post_seq = str(payload["post_seq"])
    full_pre_seq = str(payload["full_pre_seq"])
    full_post_seq = str(payload["full_post_seq"])
    truncation_warnings = payload["truncation_warnings"]
    truncation_info = payload["truncation_info"]
    target_expression = float(payload["target_expression"])
    asd = str(payload["asd"])
    threads_count = int(payload["threads_count"])
    min_len_i = int(payload["min_len_i"])
    max_len_i = int(payload["max_len_i"])
    iterations_i = int(payload["iterations_i"])
    top_n_i = int(payload["top_n_i"])
    random_seed = str(payload.get("random_seed", DESIGN_RANDOM_SEED))

    total_iterations = max(1, iterations_i)

    def _progress(progress_data: Dict[str, Any]) -> None:
        if task_id:
            progress = float(progress_data.get("progress", 0.0))
            status_msg = progress_data.get("status", "running")
            _task_update(
                task_id,
                progress=min(1.0, max(0.0, 0.65 * progress)),
                message=f"{status_msg} (phase={progress_data.get('phase', 'search')}, iter={progress_data.get('iteration', 0)}/{progress_data.get('max_iteration', total_iterations)})",
            )

    try:
        ostir_binary = get_ostir_binary()
    except RuntimeError as exc:
        raise

    candidates, _, design_diagnostics = design_rbs_candidates(
        pre_seq=pre_seq,
        post_seq=post_seq,
        target_expression=target_expression,
        ostir_binary=ostir_binary,
        asd=asd,
        threads=threads_count,
        min_length=min_len_i,
        max_length=max_len_i,
        iterations=iterations_i,
        top_n=top_n_i,
        random_seed=random_seed,
        progress_callback=_progress if task_id else None,
    )

    target_log = math.log10(target_expression)
    do_full_refinement = (
        truncation_info["pre"]["truncated"] or truncation_info["cds"]["truncated"]
    )
    refinement_multiplier = max(1, RBS_DESIGN_FULL_REFINEMENT_MULTIPLIER)
    refinement_limit = min(len(candidates), top_n_i * refinement_multiplier)
    if do_full_refinement:
        if task_id:
            _task_update(task_id, progress=0.65, message="Running full-length reevaluation")

    if do_full_refinement:
        refinement_summary = {
            "requested": refinement_limit,
            "requested_top_n": top_n_i,
            "multiplier": refinement_multiplier,
            "attempted": 0,
            "accepted": 0,
            "rejected": 0,
        }

        refined_candidates: List[Dict[str, Any]] = []
        start_codon_expected = full_post_seq[:3].upper() if full_post_seq else post_seq[:3].upper()

        for index, candidate in enumerate(candidates[:refinement_limit], start=1):
            if not candidate:
                continue
            rbs_seq = candidate.get("rbs_sequence", "")
            if not rbs_seq:
                continue

            refinement_summary["attempted"] += 1
            evaluated = _evaluate_design_candidate_full_sequence(
                pre_seq=full_pre_seq,
                post_seq=full_post_seq,
                rbs_seq=rbs_seq,
                target_log=target_log,
                ostir_binary=ostir_binary,
                asd=asd,
                threads=threads_count,
                start_codon=start_codon_expected,
            )
            if evaluated is None:
                continue

            if evaluated.get("rejected"):
                refinement_summary["rejected"] += 1
                continue

            refinement_summary["accepted"] += 1
            refined_candidates.append(evaluated)

            if task_id and refinement_limit:
                _task_update(
                    task_id,
                    progress=0.65 + 0.35 * (index / refinement_limit),
                    message=f"Full-length reevaluation {index}/{refinement_limit}",
                )

        candidates = sorted(
            refined_candidates,
            key=lambda item: (item["error"], -item["predicted_expression"]),
        )
        design_diagnostics["refinement"] = refinement_summary
    else:
        design_diagnostics["refinement"] = {
            "requested": top_n_i,
            "attempted": 0,
            "accepted": len(candidates),
            "rejected": 0,
        }

    ranked = []
    for index, candidate in enumerate(candidates, start=1):
        if not candidate:
            continue
        predicted = _coerce_float(candidate.get("predicted_expression"))
        err = _coerce_float(candidate.get("error"))
        fold = None
        if predicted is not None and predicted > 0 and target_expression > 0:
            fold = predicted / target_expression
        ranked.append(
            {
                "rank": index,
                "rbs_sequence": candidate.get("rbs_sequence", ""),
                "predicted_expression": predicted,
                "target_expression": target_expression,
                "error": err,
                "fold_ratio": fold,
                "start_position": candidate.get("start_position"),
                "start_codon": candidate.get("start_codon"),
                "full_sequence": candidate.get("full_sequence", ""),
            }
        )

    return {
        "columns": [
            "rank",
            "rbs_sequence",
            "predicted_expression",
            "error",
            "fold_ratio",
            "start_position",
            "start_codon",
            "full_sequence",
        ],
        "ok": True,
        "target_expression": target_expression,
        "iterations": iterations_i,
        "pre_length_input": truncation_info.get("pre", {}).get("input_length", len(pre_seq)),
        "cds_length_input": truncation_info.get("cds", {}).get("input_length", len(post_seq)),
        "pre_length": len(pre_seq),
        "cds_length": len(post_seq),
        "full_length_pre": len(full_pre_seq),
        "full_length_cds": len(full_post_seq),
        "candidates": ranked,
        "count": len(ranked),
        "diagnostics": design_diagnostics,
        "truncation": truncation_info,
        "warnings": truncation_warnings,
        "full_refinement": {
            "enabled": do_full_refinement,
            "full_pre_len": len(full_pre_seq),
            "full_cds_len": len(full_post_seq),
            "analysis_pre_len": len(pre_seq),
            "analysis_cds_len": len(post_seq),
            "requested_candidates": refinement_limit if do_full_refinement else top_n_i,
            "refinement_multiplier": max(1, RBS_DESIGN_FULL_REFINEMENT_MULTIPLIER),
        },
        "best": ranked[0] if ranked else None,
    }


def _run_estimate_core(
    cmd: List[str],
    command_text: str,
    sequence_for_context: Optional[str] = None,
    temporary_path: Optional[Path] = None,
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    if task_id:
        _task_update(task_id, status="running", progress=0.05, message="Running OSTIR")

    try:
        if task_id:
            _task_update(task_id, progress=0.15, message="Executing OSTIR core")

        stdout = run_ostir_command(cmd)
        if not stdout:
            raise RuntimeError("No output from ostir")

        if task_id:
            _task_update(task_id, progress=0.75, message="Parsing results")

        columns, rows = parse_ostir_output(stdout)
        if not columns:
            normalized_output = stdout.lower()
            if "no binding sites were identified" in normalized_output:
                result = {
                    "ok": True,
                    "command": command_text,
                    "count": 0,
                    "columns": [],
                    "rows": [],
                }
                if task_id:
                    _task_update(task_id, progress=0.95, message="완료(바인딩 자리 없음)")
                return result

            raise RuntimeError("Failed to parse OSTIR output")

        if sequence_for_context:
            for row in rows:
                start_position = row.get("start_position")
                row.update(build_sequence_context(sequence_for_context, start_position))

        result = {
            "ok": True,
            "command": command_text,
            "count": len(rows),
            "columns": columns,
            "rows": rows,
        }
        if task_id:
            _task_update(task_id, progress=1.0, message="Completed", status="completed")

        return result
    finally:
        if temporary_path and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                app.logger.debug("Failed to remove temporary input file: %s", temporary_path)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"ok": True, "status": "ready"})


@app.route("/run", methods=["POST"])
def run_estimate():
    temporary_path: Optional[Path] = None
    sequence_for_context: Optional[str] = None
    command_text = ""
    cleanup_temporary = True
    try:
        input_mode = request.form.get("inputMode", "sequence")
        start = request.form.get("start", "").strip()
        end = request.form.get("end", "").strip()
        asd = request.form.get("antiSd", DEFAULT_ASD).strip()
        threads = request.form.get("threads", "1").strip()
        print_seq = bool(request.form.get("printSequence"))
        print_asd = bool(request.form.get("printASD"))

        prefer_async = _coerce_bool(request.form.get("async")) or _coerce_bool(request.form.get("asyncMode"))
        try:
            ostir_binary = get_ostir_binary()
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500

        cmd: List[str] = [ostir_binary]

        if input_mode == "sequence":
            sequence = request.form.get("sequenceText", "").strip().replace("\r", "")
            if not sequence:
                return jsonify({"ok": False, "error": "Sequence input is empty"}), 400
            sequence_for_context = normalize_sequence(sequence)
            cmd += ["-i", sequence, "-t", "string"]
        elif input_mode == "file":
            upload = request.files.get("sequenceFile")
            if upload is None or upload.filename == "":
                return jsonify({"ok": False, "error": "No file uploaded"}), 400

            suffix = Path(upload.filename).suffix or ".txt"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                upload.save(tmp.name)
                temporary_path = Path(tmp.name)

            detected_type = detect_input_type(temporary_path)
            if detected_type == "fasta":
                sequence_for_context = extract_first_fasta_sequence(temporary_path)
            cmd += ["-i", str(temporary_path), "-t", detected_type]
        else:
            return jsonify({"ok": False, "error": "Invalid input mode"}), 400

        if start:
            try:
                cmd += ["-s", str(int(start))]
            except ValueError:
                return jsonify({"ok": False, "error": "Start must be an integer"}), 400

        if end:
            try:
                cmd += ["-e", str(int(end))]
            except ValueError:
                return jsonify({"ok": False, "error": "End must be an integer"}), 400

        if asd:
            cmd += ["-a", asd]

        try:
            threads_count = int(threads)
            if threads_count > 0:
                cmd += ["-j", str(threads_count)]
        except ValueError:
            return jsonify({"ok": False, "error": "Threads must be an integer"}), 400

        if print_seq:
            cmd.append("-p")
        if print_asd:
            cmd.append("-q")

        if not prefer_async and RBS_DEFAULT_ASYNC:
            input_length = 0
            if sequence_for_context:
                input_length = len(sequence_for_context)
            elif temporary_path and temporary_path.exists():
                try:
                    input_length = temporary_path.stat().st_size
                except OSError:
                    input_length = 0
            prefer_async = input_length > 5000

        command_text = " ".join(cmd)
        if prefer_async:
            task_id = _task_create("run")
            if not task_id:
                return jsonify({"ok": False, "error": "Failed to create task"}), 500

            _run_in_background(
                task_id,
                _run_estimate_core,
                cmd,
                command_text,
                sequence_for_context,
                temporary_path,
                task_id,
            )
            cleanup_temporary = False
            return jsonify({"ok": True, "task_id": task_id, "status": "queued"}), 202

        result = _run_estimate_core(
            cmd=cmd,
            command_text=command_text,
            sequence_for_context=sequence_for_context,
            temporary_path=temporary_path,
        )
        return jsonify(result)

    except RuntimeError as exc:
        app.logger.warning("OSTIR runtime error in /run: %s", exc)
        payload, status = _error_payload(
            "OSTIR runtime error" if not RBS_DEBUG_ERROR else f"OSTIR runtime error: {exc}"
        )
        return jsonify(payload), status
    except Exception as exc:
        app.logger.error("Unhandled error in /run: %s", exc)
        app.logger.exception("Full traceback for /run")
        payload, status = _error_payload("Internal server error in run endpoint")
        return jsonify(payload), status
    finally:
        if cleanup_temporary and temporary_path and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                app.logger.debug("Failed to remove temporary input file: %s", temporary_path)


@app.route("/design", methods=["POST"])
def run_design():
    use_async = _coerce_bool(request.form.get("async"))
    async_mode_requested = _coerce_bool(request.form.get("asyncMode"))
    prefer_async = use_async or async_mode_requested

    try:
        payload = _parse_design_request(dict(request.form))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    if prefer_async:
        task_id = _task_create("design")
        if task_id:
            _run_in_background(task_id, _run_design_core, payload, task_id)
            return jsonify({"ok": True, "task_id": task_id, "status": "queued"}), 202

    try:
        payload_result = _run_design_core(payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        app.logger.warning("Runtime error in /design: %s", exc)
        payload, status = _error_payload("Design runtime error")
        return jsonify(payload), status
    except Exception as exc:
        app.logger.exception("Unhandled error in design flow")
        payload, status = _error_payload("Internal server error in design endpoint")
        return jsonify(payload), status

    return jsonify(payload_result)


@app.route("/tasks/<task_id>", methods=["GET"])
def get_task(task_id: str):
    _task_cleanup()
    with _TASK_LOCK:
        task = _BACKGROUND_TASKS.get(task_id)
        if task is None:
            return jsonify({"ok": False, "error": "Task not found"}), 404
        response = dict(task)

    public_task = _normalize_task(response)
    public_task["ok"] = True
    if public_task.get("status") in {"completed", "failed"}:
        if response.get("status") == "completed":
            public_task["result"] = response.get("result")
        if response.get("status") == "failed":
            if "error_detail" in response:
                public_task["error_detail"] = (
                    response["error_detail"] if RBS_DEBUG_ERROR else None
                )

    return jsonify(public_task)


@app.errorhandler(Exception)
def _handle_runtime_error(error):
    if request.path in {"/run", "/design"}:
        app.logger.exception("Unhandled exception in %s: %s", request.path, error)
        payload, status = _error_payload("Internal server error in API endpoint")
        return jsonify(payload), status
    raise error


if __name__ == "__main__":
    try:
        _check_viennarna_dependencies()
    except RuntimeError as exc:
        print(f"Startup dependency check failed: {exc}", file=sys.stderr, flush=True)
        raise

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))

    if os.environ.get("RBS_AUTO_OPEN_BROWSER", "1").lower() not in {
        "0", "false", "off", "no"
    }:
        try:
            import webbrowser

            def _open_ui():
                try:
                    webbrowser.open(f"http://{host}:{port}", new=2)
                except Exception as exc:
                    print(
                        f"[webbrowser] Failed to open browser: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

            threading.Timer(1.2, _open_ui).start()
        except Exception as exc:
            print(
                f"[webbrowser] Not available: {exc}",
                file=sys.stderr,
                flush=True,
            )

    app.run(
        host=host,
        port=port,
        debug=False,
        use_reloader=False,
    )
