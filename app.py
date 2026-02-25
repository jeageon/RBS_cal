from __future__ import annotations

import csv
import logging
import io
import os
import sys
import random
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import math
import traceback

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB
app.logger.setLevel(logging.INFO)
OSTIR_BIN = os.environ.get("OSTIR_BIN", "ostir")
RBS_DESIGN_ITERATION_DEFAULT = int(os.environ.get("RBS_DESIGN_ITERATIONS", "500"))
RBS_DESIGN_CANDIDATES_DEFAULT = int(os.environ.get("RBS_DESIGN_TOP_CANDIDATES", "10"))

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


def _error_payload(message: str, status: int = 500, detail: Optional[str] = None):
    payload = {"ok": False, "error": message}
    if detail:
        payload["detail"] = detail
    return payload, status


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
    base_prefix = Path(sys.base_prefix)
    candidates: List[Path] = [
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
                ]
            )
    except Exception:
        pass

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


def _ensure_viennarna_in_path() -> List[str]:
    missing = _missing_viennarna_bins()
    if not missing:
        return []

    current_parts = {
        p.strip().strip('"')
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p.strip()
    }
    for base in _candidate_viennarna_dirs():
        for candidate_dir in (base, base / "bin"):
            if not candidate_dir.is_dir():
                continue
            candidate = str(candidate_dir)
            if candidate in current_parts:
                continue
            os.environ["PATH"] = candidate + os.pathsep + os.environ.get("PATH", "")
            current_parts.add(candidate)

    missing = _missing_viennarna_bins()
    return missing


def _check_viennarna_dependencies() -> None:
    global _VIENNARNA_READY
    if _VIENNARNA_READY is True:
        return

    missing = _ensure_viennarna_in_path()
    if not missing:
        _VIENNARNA_READY = True
        return

    _VIENNARNA_READY = False
    module_status = "ok" if _has_vienna_module() else "missing RNA module"
    raise RuntimeError(
        "ViennaRNA command dependencies are missing in PATH. "
        f"Missing: {', '.join(missing)}. "
        "Expected: RNAfold, RNAsubopt, RNAeval. "
        f"Python RNA module status: {module_status}. "
        "Install/add ViennaRNA bin directory to PATH (for example within this venv/site-packages/RNA/bin)."
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
            + " ".join(locations)
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/run", methods=["POST"])
def run_estimate():
    temporary_path: Optional[Path] = None
    sequence_for_context: Optional[str] = None
    command_text = ""
    try:
        input_mode = request.form.get("inputMode", "sequence")
        start = request.form.get("start", "").strip()
        end = request.form.get("end", "").strip()
        asd = request.form.get("antiSd", DEFAULT_ASD).strip()
        threads = request.form.get("threads", "1").strip()
        print_seq = bool(request.form.get("printSequence"))
        print_asd = bool(request.form.get("printASD"))

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

        command_text = " ".join(cmd)
        stdout = run_ostir_command(cmd)
        if not stdout:
            return jsonify({"ok": False, "error": "No output from ostir"}), 500

        columns, rows = parse_ostir_output(stdout)
        if not columns:
            normalized_output = stdout.lower()
            if "no binding sites were identified" in normalized_output:
                return jsonify(
                    {
                        "ok": True,
                        "command": command_text,
                        "count": 0,
                        "columns": [],
                        "rows": [],
                    }
                )
            return jsonify({"ok": False, "error": "Failed to parse OSTIR output", "raw": stdout}), 500

        if sequence_for_context:
            for row in rows:
                start = row.get("start_position")
                row.update(build_sequence_context(sequence_for_context, start))

        return jsonify(
            {
                "ok": True,
                "command": command_text,
                "count": len(rows),
                "columns": columns,
                "rows": rows,
            }
        )
    except RuntimeError as exc:
        app.logger.warning("OSTIR runtime error in /run: %s", exc)
        payload, status = _error_payload(
            f"OSTIR runtime error: {exc}", detail=traceback.format_exc()[:1000]
        )
        return jsonify(payload), status
    except Exception as exc:
        app.logger.error("Unhandled error in /run: %s", exc)
        app.logger.exception("Full traceback for /run")
        payload, status = _error_payload(
            "Internal server error in run endpoint",
            detail=traceback.format_exc()[:1000],
        )
        return jsonify(payload), status
    finally:
        if temporary_path and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


@app.route("/design", methods=["POST"])
def run_design():
    pre_seq = request.form.get("preSequence", "").strip().replace("\r", "")
    post_seq = request.form.get("postSequence", "").strip().replace("\r", "")
    target = request.form.get("targetExpression", "").strip()
    asd = request.form.get("antiSd", DEFAULT_ASD).strip()
    threads = request.form.get("threads", "1").strip()
    min_len = request.form.get("rbsMinLength", "6").strip()
    max_len = request.form.get("rbsMaxLength", "12").strip()
    iterations = request.form.get("iterations", str(RBS_DESIGN_ITERATION_DEFAULT)).strip()
    top_n = request.form.get("topCandidates", str(RBS_DESIGN_CANDIDATES_DEFAULT)).strip()
    random_seed = request.form.get("randomSeed", DESIGN_RANDOM_SEED).strip()

    pre_seq = _format_sequence(pre_seq)
    post_seq = _format_sequence(post_seq)
    if not pre_seq:
        return jsonify({"ok": False, "error": "Pre-sequence input is required"}), 400
    if len(post_seq) < 3:
        return jsonify({"ok": False, "error": "postSequence must include a start codon and CDS"}), 400
    if post_seq[:3].upper() not in START_CODONS:
        return jsonify({"ok": False, "error": "postSequence must start with ATG, GTG, or TTG"}), 400

    try:
        target_expression = float(target)
    except ValueError:
        return jsonify({"ok": False, "error": "targetExpression must be a number"}), 400
    if target_expression <= 0:
        return jsonify({"ok": False, "error": "targetExpression must be greater than 0"}), 400

    try:
        min_len_i = int(min_len)
        max_len_i = int(max_len)
        if min_len_i < 3 or max_len_i < min_len_i:
            return jsonify({"ok": False, "error": "Invalid RBS length range"}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "rbsMinLength and rbsMaxLength must be integers"}), 400

    try:
        iterations_i = int(iterations)
        top_n_i = int(top_n)
        if iterations_i <= 0 or top_n_i <= 0:
            return jsonify({"ok": False, "error": "iterations and topCandidates must be positive"}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "iterations and topCandidates must be integers"}), 400

    try:
        threads_count = int(threads)
        if threads_count <= 0:
            threads_count = 1
    except ValueError:
        return jsonify({"ok": False, "error": "Threads must be an integer"}), 400

    try:
        ostir_binary = get_ostir_binary()
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

    try:
        candidates, best, design_diagnostics = design_rbs_candidates(
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
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500

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

    response = {
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
        "pre_length": len(pre_seq),
        "cds_length": len(post_seq),
        "candidates": ranked,
        "count": len(ranked),
        "diagnostics": design_diagnostics,
    }
    if best:
        response["best"] = ranked[0] if ranked else None

    return jsonify(response)


@app.errorhandler(Exception)
def _handle_runtime_error(error):
    if request.path in {"/run", "/design"}:
        app.logger.exception("Unhandled exception in %s: %s", request.path, error)
        payload, status = _error_payload(
            "Internal server error in API endpoint",
            detail=traceback.format_exc()[:1000],
        )
        return jsonify(payload), status
    raise error


if __name__ == "__main__":
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        debug=False,
        use_reloader=False,
    )
