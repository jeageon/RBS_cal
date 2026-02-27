from __future__ import annotations

import importlib
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Set

from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord


def _discover_primer_maker_roots() -> list[Path]:
    roots: list[Path] = []
    env_root = os.getenv("PRIMER_MAKER_ROOT")
    if env_root:
        roots.append(Path(env_root).expanduser().resolve())

    cwd = Path.cwd().resolve()
    script_dir = Path(__file__).resolve().parent

    for candidate in [
        script_dir.parent / "pimer_maker",
        script_dir / "pimer_maker",
        cwd / "prime_maker" / "pimer_maker",
        cwd / "pimer_maker",
        cwd / "primer_maker",
        Path("/Users") / os.getenv("USER", "").strip() / "Documents" / "pimer_maker",
        Path("/Users") / os.getenv("USER", "").strip() / "Documents" / "primer_maker",
        Path("/Users") / os.getenv("USER", "").strip() / "Documents" / "primer-maker",
        Path("/Users") / os.getenv("USER", "").strip() / "Documents" / "prime_maker" / "pimer_maker",
    ]:
        try:
            candidate = candidate.expanduser().resolve()
        except Exception:
            continue
        if candidate not in roots and candidate.exists():
            roots.append(candidate)

    return roots


_PM_MODULE: Optional[Any] = None


def _load_primer_maker_pipeline() -> Any:
    """Load local primer_maker pipeline module without requiring Primer3."""
    global _PM_MODULE
    if _PM_MODULE is not None:
        return _PM_MODULE

    module_name_candidates = (
        "src.modules.primer_pipeline",
        "modules.primer_pipeline",
        "pimer_maker.src.modules.primer_pipeline",
    )
    last_error: Optional[BaseException] = None

    for root in _discover_primer_maker_roots():
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

        for module_name in module_name_candidates:
            try:
                module = importlib.import_module(module_name)
                if all(
                    hasattr(module, attr)
                    for attr in ("find_candidates", "validate_primer_pair", "PrimerCandidate", "PrimerPairBinding")
                ):
                    _PM_MODULE = module
                    return module
            except Exception as exc:  # pragma: no cover - optional import path resolution
                last_error = exc

    raise RuntimeError(
        "primer_maker 모듈을 찾지 못했습니다. PRIMER_MAKER_ROOT 환경변수에 "
        "pimer_maker 레포 루트를 지정하거나 pip install된 패키지를 확인하세요."
    ) from last_error


def _revcomp(seq: str) -> str:
    return str(Seq(seq).reverse_complement())


def _window_positions(start: int, end: int, length: int) -> Set[int]:
    if length <= 0:
        return set()

    raw_span = end - start
    start %= length
    end %= length
    if start < 0:
        start += length
    if end < 0:
        end += length

    if raw_span != 0 and (raw_span % length == 0):
        return {i for i in range(length)}

    if start == end:
        return set()

    if start < end:
        return {i for i in range(start, end)}
    return {i for i in range(start, length)} | {i for i in range(0, end)}


def _overlaps_window(feature_start: int, feature_end: int, window: Set[int]) -> bool:
    for pos in range(feature_start, feature_end):
        if pos in window:
            return True
    return False


def _extract_offtarget_count(sequence: str, primer: str, seed_len: int, pm_module: Any) -> int:
    seed = primer[-max(1, seed_len):]
    return max(0, int(pm_module._seed_offtarget_count(sequence, seed)) - 1)


def _first_value(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, (list, tuple)):
        if not values:
            return ""
        values = values[0]
    return str(values).strip()


def _to_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except Exception:
        return None


def _parse_kv_notes(notes: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in notes:
        if not raw:
            continue
        token = str(raw).strip()
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key.strip().lower()] = value.strip()
    return parsed


def _normalize_orientation(raw: Any) -> str:
    value = _first_value(raw).lower()
    if not value:
        return ""
    if value.startswith("f") or value in {"1", "plus", "+"}:
        return "F"
    if value.startswith("r") or value in {"-1", "-", "minus", "rev"}:
        return "R"
    return value[:1].upper()


def _extract_primer_sequence(feature, record_seq: Seq) -> str:
    try:
        seq = str(feature.extract(record_seq)).upper()
    except Exception:
        seq = ""
    seq = re.sub(r"[^ACGT]", "", seq)
    return seq


@dataclass
class PrimerPair:
    left_seq: str
    right_seq: str
    left_tm: float
    right_tm: float
    primer_pair_penalty: float
    primer_left_penalty: float
    primer_right_penalty: float
    pcr_product_min: int
    pcr_product_max: int
    tm_balance: float
    hairpin_any: float
    self_any: float
    end_stability_ok: bool
    off_target_left: int
    off_target_right: int
    unique: bool
    raw: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def _normalize_meta(self) -> dict:
        raw = dict(self.raw or {})
        if "left" in raw and "right" in raw:
            return raw
        candidate_left = raw.get("candidate_left")
        candidate_right = raw.get("candidate_right")
        if isinstance(candidate_left, dict) and isinstance(candidate_right, dict):
            return {
                "left": {
                    "name": _first_value(candidate_left.get("primer_id")),
                    "tm": float(candidate_left.get("tm", 0.0)) if candidate_left.get("tm") is not None else 0.0,
                },
                "right": {
                    "name": _first_value(candidate_right.get("primer_id")),
                    "tm": float(candidate_right.get("tm", 0.0)) if candidate_right.get("tm") is not None else 0.0,
                },
                "product_size": int(raw.get("product_size", self.pcr_product_min or 0)),
            }
        return {
            "product_size": int(raw.get("product_size", self.pcr_product_min or 0)),
        }

    def to_dict(self) -> dict:
        return {
            "left_seq": self.left_seq,
            "right_seq": self.right_seq,
            "left_tm": round(self.left_tm, 2),
            "right_tm": round(self.right_tm, 2),
            "tm_balance": round(self.tm_balance, 2),
            "primer_pair_penalty": round(self.primer_pair_penalty, 2),
            "primer_left_penalty": round(self.primer_left_penalty, 2),
            "primer_right_penalty": round(self.primer_right_penalty, 2),
            "hairpin_any": round(self.hairpin_any, 2),
            "self_any": round(self.self_any, 2),
            "end_stability_ok": self.end_stability_ok,
            "off_target_left": self.off_target_left,
            "off_target_right": self.off_target_right,
            "unique": self.unique,
            "warnings": list(self.warnings),
            "score_breakdown": {
                "product_size": self.pcr_product_min,
                "pcr_product_range": [self.pcr_product_min, self.pcr_product_max],
            },
            "pair_meta": self._normalize_meta(),
        }


@dataclass
class PrimerFeature:
    name: str
    sequence: str
    start: int
    end: int
    strand: int
    orientation: str
    tm: Optional[float]
    gc: Optional[float]
    primer_id: Optional[str]
    length: int
    raw: dict[str, Any] = field(default_factory=dict)


def _score_pair(
    left_score: float,
    right_score: float,
    pair_info: dict[str, Any],
    pair_tm_gap: float,
) -> float:
    # 낮을수록 좋은 점수 (기존 Primer3 스코어 관성 유사)
    base = 0.25 * (left_score + right_score)
    base += 1.2 * pair_tm_gap
    base += 1.8 * int(pair_info.get("seed_warnings", 0))
    if pair_info.get("dimer_risk"):
        base += 8.0
    return base


def _candidate_pair_matches(
    validation_pairs: list[dict[str, Any]],
    left_start: int,
    right_start: int,
) -> Optional[dict[str, Any]]:
    for item in validation_pairs:
        if (
            item.get("forward_start") == left_start
            and item.get("reverse_start") == right_start
        ):
            return item
    return None


def extract_primers_from_record(record: SeqRecord) -> list[PrimerFeature]:
    seq = record.seq
    out: list[PrimerFeature] = []

    # 1) primer_bind from primer_maker
    for idx, feat in enumerate(record.features, 1):
        if feat.type != "primer_bind":
            continue
        try:
            start = int(feat.location.start)
            end = int(feat.location.end)
        except Exception:
            continue
        if end <= start:
            continue

        quals = feat.qualifiers or {}
        orientation = _normalize_orientation(
            _first_value(quals.get("orientation"))
            or _first_value(quals.get("primer_strand"))
            or _first_value(quals.get("strand"))
        )
        if not orientation:
            strand = feat.location.strand or 1
            orientation = "F" if int(strand) >= 0 else "R"

        note_map = _parse_kv_notes([_first_value(v) for v in quals.get("note", []) if _first_value(v)])
        seq_quoted = note_map.get("sequence") or _first_value(quals.get("sequence"))
        if seq_quoted:
            raw_seq = re.sub(r"[^ACGT]", "", str(seq_quoted).upper())
        else:
            raw_seq = _extract_primer_sequence(feat, seq)
        if not raw_seq or len(raw_seq) < 2:
            continue

        tm = _to_float(note_map.get("tm"))
        if tm is None:
            tm = _to_float(_first_value(quals.get("Tm")))

        gc = _to_float(note_map.get("gc"))
        if gc is not None and gc > 1:
            gc = gc / 100.0

        out.append(
            PrimerFeature(
                name=(
                    _first_value(quals.get("primer_name"))
                    or _first_value(quals.get("label"))
                    or _first_value(feat.id)
                    or f"primer_{idx}"
                ),
                sequence=raw_seq,
                start=start,
                end=end,
                strand=int(feat.location.strand or 1),
                orientation=orientation,
                tm=tm,
                gc=gc,
                primer_id=note_map.get("primer_id") or _first_value(quals.get("primer_id")),
                length=len(raw_seq),
                raw={
                    "qualifiers": {k: list(v) if isinstance(v, (list, tuple)) else [str(v)] for k, v in quals.items()},
                    "note_map": note_map,
                    "feature_id": str(feat.id),
                    "feature_type": feat.type,
                },
            )
        )

    # 2) fallback: 다른 feature에 primer_name / primer_id가 들어간 경우
    if out:
        return out

    for idx, feat in enumerate(record.features, 1):
        quals = feat.qualifiers or {}
        if not (
            _first_value(quals.get("primer_name"))
            or _first_value(quals.get("primer_id"))
            or _first_value(quals.get("sequence"))
            or any("sequence=" in _first_value(v) for v in quals.get("note", []))
        ):
            continue

        try:
            start = int(feat.location.start)
            end = int(feat.location.end)
        except Exception:
            continue
        if end <= start:
            continue

        note_map = _parse_kv_notes([_first_value(v) for v in quals.get("note", []) if _first_value(v)])
        raw_seq = note_map.get("sequence") or _extract_primer_sequence(feat, seq)
        raw_seq = re.sub(r"[^ACGT]", "", str(raw_seq).upper()) if raw_seq else ""
        if len(raw_seq) < 2:
            continue

        tm = _to_float(note_map.get("tm"))
        if tm is None:
            tm = _to_float(_first_value(quals.get("Tm")))

        out.append(
            PrimerFeature(
                name=_first_value(quals.get("primer_name")) or _first_value(quals.get("label")) or f"primer_{idx}",
                sequence=raw_seq,
                start=start,
                end=end,
                strand=int(feat.location.strand or 1),
                orientation=_normalize_orientation(_first_value(quals.get("orientation"))),
                tm=tm,
                gc=None,
                primer_id=_first_value(quals.get("primer_id")),
                length=len(raw_seq),
                raw={
                    "qualifiers": {k: list(v) if isinstance(v, (list, tuple)) else [str(v)] for k, v in quals.items()},
                    "note_map": note_map,
                    "feature_id": str(feat.id),
                    "feature_type": feat.type,
                },
            )
        )

    return out


def _circular_product_size(start: int, end: int, length: int) -> int:
    if length <= 0:
        return 0
    span = (end - start) % length
    if span <= 0:
        span = length
    return int(span)


def _is_forward_primer(primer: PrimerFeature) -> bool:
    if primer.orientation:
        return primer.orientation == "F"
    return primer.strand >= 0


def _is_reverse_primer(primer: PrimerFeature) -> bool:
    if primer.orientation:
        return primer.orientation == "R"
    return primer.strand < 0


def _offtarget_count(sequence: str, primer_seq: str) -> int:
    if not primer_seq:
        return 1
    s = sequence.upper()
    target = primer_seq.upper()
    rc = _revcomp(target)
    count = s.count(target)
    if rc != target:
        count += s.count(rc)
    return max(0, count - 1)


def design_inverse_pcr_from_features(
    record: SeqRecord,
    insert_start: int,
    insert_end: int,
    num_return: int = 3,
    flank: int = 350,
    max_product_bp: int = 0,
    expected_product_bp: int = 0,
) -> list[PrimerPair]:
    seq = str(record.seq).upper()
    length = len(seq)
    if length <= 0:
        return []

    primers = extract_primers_from_record(record)
    if not primers:
        return []

    if expected_product_bp <= 0:
        expected_product_bp = length - max(1, insert_end - insert_start)

    left_window = _window_positions(insert_start - flank, insert_start, length)
    right_window = _window_positions(insert_end, insert_end + flank, length)

    left_candidates = [p for p in primers if _is_forward_primer(p) and _overlaps_window(p.start, p.end, left_window)]
    right_candidates = [p for p in primers if _is_reverse_primer(p) and _overlaps_window(p.start, p.end, right_window)]

    # fallback
    if not left_candidates:
        left_candidates = [p for p in primers if _overlaps_window(p.start, p.end, left_window)]
    if not right_candidates:
        right_candidates = [p for p in primers if _overlaps_window(p.start, p.end, right_window)]

    if not left_candidates or not right_candidates:
        return []

    left_pool = sorted(left_candidates, key=lambda item: (item.start, item.length))[: max(1, num_return * 12)]
    right_pool = sorted(right_candidates, key=lambda item: (item.start, item.length))[: max(1, num_return * 12)]

    found: list[tuple[float, PrimerPair]] = []
    for left in left_pool:
        for right in right_pool:
            if left.start == right.start and left.end == right.end:
                continue

            product_size = _circular_product_size(left.start, right.start, length)
            if max_product_bp and product_size > max_product_bp:
                continue
            if product_size < 80:
                continue

            tm_gap = 0.0
            if left.tm is not None and right.tm is not None:
                tm_gap = abs(float(left.tm) - float(right.tm))
            offtarget_left = _offtarget_count(seq, left.sequence)
            offtarget_right = _offtarget_count(seq, right.sequence)

            expected_ratio = 0.0
            if expected_product_bp > 0:
                expected_ratio = abs(product_size - expected_product_bp) / max(1, expected_product_bp)

            unique = offtarget_left <= 1 and offtarget_right <= 1
            pair_penalty = 0.0
            pair_penalty += 0.8 * expected_ratio
            pair_penalty += 0.2 * tm_gap
            pair_penalty += 0.3 * abs(left.length - right.length)
            if not unique:
                pair_penalty += 0.9

            warnings: list[str] = []
            if not unique:
                warnings.append("off-target binding risk (exact/rc match >=2)")
            if tm_gap > 5.0:
                warnings.append("Tm gap is large")
            if expected_ratio > 1.0:
                warnings.append("product size far from expected window")

            pair = PrimerPair(
                left_seq=left.sequence,
                right_seq=right.sequence,
                left_tm=float(left.tm or 0.0),
                right_tm=float(right.tm or 0.0),
                primer_pair_penalty=pair_penalty,
                primer_left_penalty=float(len(left.sequence)),
                primer_right_penalty=float(len(right.sequence)),
                pcr_product_min=product_size,
                pcr_product_max=product_size,
                tm_balance=tm_gap,
                hairpin_any=0.0,
                self_any=0.0,
                end_stability_ok=unique,
                off_target_left=offtarget_left,
                off_target_right=offtarget_right,
                unique=unique,
                raw={
                    "left": {
                        "name": left.name,
                        "start": left.start,
                        "end": left.end,
                        "strand": left.strand,
                        "orientation": left.orientation,
                        "tm": left.tm,
                        "len": left.length,
                    },
                    "right": {
                        "name": right.name,
                        "start": right.start,
                        "end": right.end,
                        "strand": right.strand,
                        "orientation": right.orientation,
                        "tm": right.tm,
                        "len": right.length,
                    },
                    "product_size": product_size,
                },
                warnings=warnings,
            )
            found.append((pair_penalty, pair))

    found.sort(key=lambda item: item[0])
    return [pair for _, pair in found[: max(1, num_return)]]


def design_inverse_pcr_primers(
    plasmid_sequence: str,
    insert_start: int,
    insert_end: int,
    num_return: int = 3,
    flank: int = 350,
    target_product_len: int = 0,
) -> List[PrimerPair]:
    seq = str(plasmid_sequence).upper()
    n = len(seq)
    if n == 0:
        return []

    insert_len = max(0, insert_end - insert_start)
    if target_product_len <= 0:
        target_product_len = max(120, insert_len + 80)

    pm = _load_primer_maker_pipeline()

    # 기존 primer_maker 기본 파라미터 기반 검색
    all_candidates, _ = pm.find_candidates(
        sequence=seq,
        interference_regions=[],
        tm_target=pm.DEFAULT_PRIMER_TM_TARGET,
        tm_tolerance=pm.DEFAULT_PRIMER_TM_TOLERANCE,
        gc_min=pm.DEFAULT_GC_MIN,
        gc_max=pm.DEFAULT_GC_MAX,
        len_min=pm.DEFAULT_PRIMER_LEN_MIN,
        len_max=pm.DEFAULT_PRIMER_LEN_MAX,
        gc_clamp_min=pm.DEFAULT_GC_CLAMP_MIN,
        gc_clamp_max=pm.DEFAULT_GC_CLAMP_MAX,
        ideal_tm_min=pm.DEFAULT_IDEAL_PRIMER_TM_MIN,
        ideal_tm_max=pm.DEFAULT_IDEAL_PRIMER_TM_MAX,
        ideal_tm_gap=pm.DEFAULT_PRIMER_TM_GAP_MAX,
        ideal_repeat_unit_limit=pm.DEFAULT_IDEAL_REPEAT_UNIT_MAX,
        repeat_run_limit=pm.DEFAULT_INTERFERENCE_REPEAT_RUN,
        max_candidates=max(120, num_return * 40),
        self_dimer_exclude_identical_window=pm.DEFAULT_MANUAL_SELF_DIMER_EXCLUDE_IDENTICAL_WINDOW,
    )

    if not all_candidates:
        return []

    left_window = _window_positions(insert_start - flank, insert_start, n)
    right_window = _window_positions(insert_end, insert_end + flank, n)

    left_candidates = [
        c
        for c in all_candidates
        if c.strand == 1 and _overlaps_window(c.start, c.end, left_window)
    ]
    right_candidates = [
        c
        for c in all_candidates
        if c.strand == -1 and _overlaps_window(c.start, c.end, right_window)
    ]

    # fallback: 강제 창 필터링이 너무 빡빡한 경우는 완화
    if not left_candidates:
        left_candidates = [c for c in all_candidates if _overlaps_window(c.start, c.end, left_window)]
    if not right_candidates:
        right_candidates = [c for c in all_candidates if _overlaps_window(c.start, c.end, right_window)]

    if not left_candidates or not right_candidates:
        return []

    left_pool = sorted(left_candidates, key=lambda item: item.score)[: max(1, num_return * 20)]
    right_pool = sorted(right_candidates, key=lambda item: item.score)[: max(1, num_return * 20)]

    min_product = min(max(80, target_product_len), n)
    max_product = max(min_product, n)

    found: list[tuple[float, PrimerPair]] = []

    for left in left_pool:
        for right in right_pool:
            for first, second in ((left, right), (right, left)):
                validation = pm.validate_primer_pair(
                    sequence=seq,
                    forward_seq=first.sequence,
                    reverse_seq=second.sequence,
                    product_min=min_product,
                    product_max=max_product,
                    tm_gap_fail=pm.DEFAULT_MANUAL_TM_GAP_FAIL,
                    hairpin_min_k=pm.DEFAULT_MANUAL_HAIRPIN_MIN_K,
                    hairpin_max_k=pm.DEFAULT_MANUAL_HAIRPIN_MAX_K,
                    self_dimer_min_overlap=pm.DEFAULT_MANUAL_SELF_DIMER_MIN_OVERLAP,
                    self_dimer_max_overlap=pm.DEFAULT_MANUAL_SELF_DIMER_MAX_OVERLAP,
                    pair_dimer_min_overlap=pm.DEFAULT_MANUAL_PAIR_DIMER_MIN_OVERLAP,
                    pair_dimer_max_overlap=pm.DEFAULT_MANUAL_PAIR_DIMER_MAX_OVERLAP,
                    pair_dimer_require_3p=pm.DEFAULT_MANUAL_REQUIRE_3P_DIMER,
                    offtarget_seed_len=pm.DEFAULT_MANUAL_OFFTARGET_SEED_LEN,
                    offtarget_seed_warning_limit=pm.DEFAULT_MANUAL_OFFTARGET_SEED_WARNING_LIMIT,
                    self_dimer_exclude_identical_window=pm.DEFAULT_MANUAL_SELF_DIMER_EXCLUDE_IDENTICAL_WINDOW,
                    tm_target=pm.DEFAULT_PRIMER_TM_TARGET,
                    tm_tolerance=pm.DEFAULT_PRIMER_TM_TOLERANCE,
                )

                if not validation.get("valid"):
                    continue

                pm_pairs = validation.get("pairs") or []
                if not pm_pairs:
                    continue

                bound_pair = _candidate_pair_matches(pm_pairs, first.start, second.start)
                if bound_pair is None:
                    bound_pair = pm_pairs[0]

                product_size = int(bound_pair.get("product_size", 0))
                tm_gap = float(bound_pair.get("tm_gap", 0.0))
                seed_warnings = int(bound_pair.get("seed_warnings", 0))
                dimer_risk = bool(bound_pair.get("dimer_risk", False))

                warnings = list(validation.get("warnings", []))
                interference = validation.get("interference_details", [])
                hairpin_hits = [
                    item
                    for item in interference
                    if isinstance(item, dict) and item.get("type") in {"hairpin", "self_dimer"}
                ]
                pair_penalty = _score_pair(first.score, second.score, bound_pair, tm_gap)

                offtarget_seed_len = pm.DEFAULT_MANUAL_OFFTARGET_SEED_LEN
                off_left = _extract_offtarget_count(seq, first.sequence, offtarget_seed_len, pm)
                off_right = _extract_offtarget_count(seq, second.sequence, offtarget_seed_len, pm)

                result_pair = PrimerPair(
                    left_seq=first.sequence,
                    right_seq=second.sequence,
                    left_tm=float(validation.get("tm_forward", first.tm)),
                    right_tm=float(validation.get("tm_reverse", second.tm)),
                    primer_pair_penalty=pair_penalty,
                    primer_left_penalty=float(first.score),
                    primer_right_penalty=float(second.score),
                    pcr_product_min=product_size,
                    pcr_product_max=product_size,
                    tm_balance=tm_gap,
                    hairpin_any=float(len(hairpin_hits)),
                    self_any=float(
                        len(
                            [
                                item
                                for item in interference
                                if isinstance(item, dict) and item.get("type") == "self_dimer"
                            ]
                        )
                    ),
                    end_stability_ok=not dimer_risk,
                    off_target_left=off_left,
                    off_target_right=off_right,
                    unique=(seed_warnings == 0 and not dimer_risk),
                    raw={
                        "validation": validation,
                        "candidate_left": {"primer_id": first.primer_id, "score": first.score},
                        "candidate_right": {"primer_id": second.primer_id, "score": second.score},
                        "selected_pair": bound_pair,
                        "seed_warnings": seed_warnings,
                        "dimer_risk": dimer_risk,
                    },
                    warnings=warnings,
                )
                found.append((pair_penalty, result_pair))

    found.sort(key=lambda item: item[0])
    return [item[1] for item in found[:max(1, num_return)]]


def score_candidate_pairs(pairs: list[PrimerPair]) -> list[PrimerPair]:
    return sorted(pairs, key=lambda p: p.primer_pair_penalty)


def design_and_score_inverse_pcr(
    plasmid_sequence: str,
    insert_start: int,
    insert_end: int,
    num_return: int = 3,
    flank: int = 350,
) -> List[PrimerPair]:
    pairs = design_inverse_pcr_primers(
        plasmid_sequence=plasmid_sequence,
        insert_start=insert_start,
        insert_end=insert_end,
        num_return=num_return,
        flank=flank,
    )
    return score_candidate_pairs(pairs)


def design_and_score_inverse_pcr_from_features(
    record: SeqRecord,
    insert_start: int,
    insert_end: int,
    num_return: int = 3,
    flank: int = 350,
    max_product_bp: int = 0,
    expected_product_bp: int = 0,
) -> List[PrimerPair]:
    return design_inverse_pcr_from_features(
        record=record,
        insert_start=insert_start,
        insert_end=insert_end,
        num_return=num_return,
        flank=flank,
        max_product_bp=max_product_bp,
        expected_product_bp=expected_product_bp,
    )
