from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from Bio.Seq import Seq

from plasmid_db import SafeZoneConfig, export_json_payload, init_db, upsert_plasmid
from plasmid_safezone_engine import SafeZoneResult, build_safe_zones, parse_genbank


RESTRICTION_ENZYME_DB: dict[str, dict[str, Any]] = {
    "EcoRI": {
        "site": "GAATTC",
        "sticky": True,
        "dam_sensitive": False,
        "dcm_sensitive": True,
        "star_risk": 0.06,
        "directional": False,
    },
    "BamHI": {
        "site": "GGATCC",
        "sticky": True,
        "dam_sensitive": False,
        "dcm_sensitive": True,
        "star_risk": 0.08,
        "directional": False,
    },
    "HindIII": {
        "site": "AAGCTT",
        "sticky": True,
        "dam_sensitive": False,
        "dcm_sensitive": False,
        "star_risk": 0.05,
        "directional": False,
    },
    "XbaI": {
        "site": "TCTAGA",
        "sticky": True,
        "dam_sensitive": False,
        "dcm_sensitive": False,
        "star_risk": 0.09,
        "directional": True,
    },
    "XhoI": {
        "site": "CTCGAG",
        "sticky": True,
        "dam_sensitive": False,
        "dcm_sensitive": True,
        "star_risk": 0.07,
        "directional": True,
    },
    "PstI": {
        "site": "CTGCAG",
        "sticky": True,
        "dam_sensitive": True,
        "dcm_sensitive": False,
        "star_risk": 0.12,
        "directional": True,
    },
    "SmaI": {
        "site": "CCCGGG",
        "sticky": False,
        "dam_sensitive": False,
        "dcm_sensitive": False,
        "star_risk": 0.10,
        "directional": False,
    },
}


def _revcomp(seq: str) -> str:
    return str(Seq(seq).reverse_complement())


def _safe01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


@dataclass
class HostContext:
    host: str = "E. coli"
    dam_dcm_sensitive: bool = False
    methylation_sensitive: bool = False
    comments: str = ""


@dataclass
class InsertMetadata:
    length_bp: int
    gc_content: Optional[float] = None
    gc_extreme: Optional[float] = None
    toxic_gene: bool = False
    repeat_like: float = 0.0


def _normalize_strategy(value: str) -> str:
    key = (value or "restriction").strip().lower().replace("-", "_")
    if key in {"restriction", "digest", "restriction_digest", "single", "single_digest"}:
        return "restriction_single"
    if key in {"inverse", "inverse_pcr", "inversepcr", "inverse-pcr", "gibson", "assembly", "pcr", "inverse_pcr_amp"}:
        return "inverse_pcr"
    if key in {"restriction_double", "double", "double_digest", "directional"}:
        return "restriction_double"
    return key


def _normalize_mode(value: str) -> str:
    value = (value or "neutral").strip().lower()
    if value not in {"neutral", "expression", "fusion"}:
        return "neutral"
    return value


@dataclass
class CloneParams:
    target_mode: str = "neutral"
    cloning_strategy: str = "inverse_pcr"
    host_context: HostContext = field(default_factory=HostContext)
    insert: InsertMetadata = field(default_factory=lambda: InsertMetadata(0))
    include_disruptable: bool = True
    include_neutral: bool = True
    buffer_bp: int = 100
    top_k: int = 20
    candidate_per_zone: int = 3
    flank_bp: int = 350
    risk_ratio_cap: float = 0.25
    max_product_bp: int = 4000
    risk_weight: float = 1.0
    strategy_window_bp: int = 7000


@dataclass
class Candidate:
    interval_start: int
    interval_end: int
    start: int
    end: int
    strategy: str
    score: float
    risk: float
    strategy_score: float
    reasons: List[str] = field(default_factory=list)
    closest_feature: Optional[str] = None
    feature_distance_bp: Optional[int] = None
    primer_pairs: List[dict] = field(default_factory=list)
    strategy_candidates: List[dict] = field(default_factory=list)
    strategy_penalties: dict = field(default_factory=dict)
    strategy_summary: Optional[str] = None
    risk_breakdown: dict = field(default_factory=dict)

    def as_1based(self) -> dict:
        return {
            "interval_start_1based": self.interval_start + 1,
            "interval_start_0based": self.interval_start,
            "interval_end_1based": self.interval_end,
            "interval_end_0based": self.interval_end,
            "insert_start_1based": self.start + 1,
            "insert_start_0based": self.start,
            "insert_end_1based": self.end,
            "insert_end_0based": self.end,
            "insert_length": max(0, self.end - self.start),
            "strategy": self.strategy,
            "score": round(self.score, 3),
            "risk": round(self.risk, 3),
            "strategy_score": round(self.strategy_score, 3),
            "closest_feature": self.closest_feature,
            "feature_distance_bp": self.feature_distance_bp,
            "risk_breakdown": self.risk_breakdown,
            "strategy_penalties": self.strategy_penalties,
            "strategy_candidates": self.strategy_candidates[:3],
            "strategy_summary": self.strategy_summary,
            "primer_pairs": self.primer_pairs,
            "reasons": self.reasons,
        }


@dataclass
class PipelineResult:
    record_id: str
    topology: str
    length: int
    safe_zones: list[tuple[int, int]]
    candidates: list[Candidate]
    risk_ratio_cap: float
    strategy: str
    target_mode: str
    host: str
    safe_result: Optional[SafeZoneResult] = None
    plasmid_id: Optional[int] = None

    def to_json(self) -> str:
        payload = {
            "record_id": self.record_id,
            "topology": self.topology,
            "length": self.length,
            "strategy": self.strategy,
            "target_mode": self.target_mode,
            "host": self.host,
            "risk_ratio_cap": self.risk_ratio_cap,
            "safe_zones_1based": [(s + 1, e) for s, e in self.safe_zones],
            "candidates": [c.as_1based() for c in self.candidates],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_manual_tags(values: Optional[Sequence[str]]) -> tuple[Dict[str, str], list[str]]:
    tags: Dict[str, str] = {}
    warnings: list[str] = []
    if not values:
        return tags, warnings

    for item in values:
        if "=" not in item:
            warnings.append(f"manual-tag '{item}' is ignored. expected key=value format.")
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip().lower()
        if not key:
            warnings.append(f"manual-tag '{item}' is ignored because key is empty.")
            continue
        if not value:
            warnings.append(f"manual-tag '{item}' is ignored because value is empty.")
            continue
        tags[key] = value
    return tags, warnings


def _estimate_repeat_like(seq: str, min_run: int = 5) -> float:
    if not seq:
        return 0.0
    max_run = 1
    run = 1
    prev = seq[0]
    runs: list[int] = []
    for ch in seq[1:]:
        if ch == prev:
            run += 1
        else:
            runs.append(run)
            prev = ch
            run = 1
    runs.append(run)

    score = 0.0
    for r in runs:
        if r >= min_run:
            score += (r - (min_run - 1)) / max(1, len(seq))
    return _safe01(score)


def _calc_risk(
    plasmid_len: int,
    insert_len: int,
    gc_content: Optional[float],
    repeat_like: float = 0.0,
    toxic: bool = False,
    risk_ratio_cap: float = 0.25,
) -> float:
    if plasmid_len <= 0:
        return 1.0

    ratio = insert_len / max(1, plasmid_len)
    size_risk = min(1.0, ratio / max(1e-3, risk_ratio_cap))

    if gc_content is None:
        gc_risk = 0.0
    else:
        gc_risk = abs(gc_content - 0.5) / 0.5
        gc_risk = _safe01(gc_risk)

    repeat_risk = _safe01(repeat_like)
    tox_pen = 0.35 if toxic else 0.0
    score = 1.3 * size_risk + 0.8 * gc_risk + 0.9 * repeat_risk + tox_pen
    return _safe01(score)


def _find_nearest_feature(distance_point: int, features: List[object]) -> tuple[Optional[str], Optional[int]]:
    nearest_name: Optional[str] = None
    nearest_distance: Optional[int] = None
    if not features:
        return None, None

    for f in features:
        mid = (f.start + f.end) // 2
        d = abs(mid - distance_point)
        if nearest_distance is None or d < nearest_distance:
            nearest_distance = d
            nearest_name = getattr(f, "label", None) or f.feature_type
    return nearest_name, nearest_distance


def _safe_zone_candidates(interval_start: int, interval_end: int, insert_len: int, sample_size: int = 3) -> list[int]:
    L = max(0, interval_end - interval_start)
    if L <= 0:
        return []

    usable = L - insert_len
    if usable < 0:
        return []

    usable = max(0, usable)
    if sample_size <= 0:
        sample_size = 1

    if usable == 0:
        return [interval_start]

    if sample_size == 1:
        return [interval_start + L // 2]

    points: list[int] = []
    for idx in range(sample_size):
        frac = (idx + 1) / (sample_size + 1)
        pos = interval_start + int(usable * frac)
        pos = min(interval_end - insert_len, max(interval_start, pos))
        if pos not in points:
            points.append(pos)
    points.sort()
    return points


def _find_sites(sequence: str, motif: str, *, include_reverse: bool = True) -> list[int]:
    seq = sequence.upper()
    motif_u = motif.upper()
    if not motif_u or any(nt not in "ACGT" for nt in motif_u):
        return []

    positions: set[int] = set()
    motif_len = len(motif_u)
    for i in range(0, len(seq) - motif_len + 1):
        win = seq[i : i + motif_len]
        if win == motif_u:
            positions.add(i)
        if include_reverse:
            if win == _revcomp(motif_u):
                positions.add(i)
    return sorted(positions)


def _build_restriction_sites(sequence: str) -> dict[str, list[int]]:
    return {name: _find_sites(sequence, cfg["site"]) for name, cfg in RESTRICTION_ENZYME_DB.items()}


def _format_restriction_summary(plan: dict[str, Any], strategy: str) -> str:
    enzymes = plan.get("enzymes") or []
    sites = plan.get("sites") or []
    if strategy == "restriction_single" and len(enzymes) == 1 and len(sites) >= 1:
        enzyme = str(enzymes[0])
        site = int(sites[0])
        motif = str(plan.get("motif_seq", plan.get("motif", "")) or "")
        motif_len = int(plan.get("motif_len", len(motif) if motif else 0))
        if not motif_len:
            motif_len = len(motif)
        span = f"{site + 1}-{site + motif_len}" if motif_len > 0 else f"{site + 1}"
        cut = plan.get("cut_1based")
        cut_txt = f", cut~{int(cut)}" if cut not in (None, "") else ""
        if motif:
            return f"single: {enzyme} ({motif}) at {span}{cut_txt}"
        return f"single: {enzyme} at {span}{cut_txt}"

    if strategy == "restriction_double" and len(enzymes) >= 2 and len(sites) >= 2:
        le = str(enzymes[0])
        re = str(enzymes[1])
        l = int(sites[0])
        r = int(sites[1])
        l_motif = str(plan.get("left_motif_seq", plan.get("left_motif", "")) or "")
        r_motif = str(plan.get("right_motif_seq", plan.get("right_motif", "")) or "")
        l_len = int(plan.get("left_motif_len", len(l_motif) if l_motif else 0))
        r_len = int(plan.get("right_motif_len", len(r_motif) if r_motif else 0))
        if not l_len:
            l_len = len(l_motif)
        if not r_len:
            r_len = len(r_motif)
        l_span = f"{l + 1}-{l + l_len}" if l_len > 0 else f"{l + 1}"
        r_span = f"{r + 1}-{r + r_len}" if r_len > 0 else f"{r + 1}"
        l_cut = plan.get("left_cut_1based")
        r_cut = plan.get("right_cut_1based")
        cuts: list[str] = []
        if l_cut is not None:
            cuts.append(f"{le} cut~{int(l_cut)}")
        if r_cut is not None:
            cuts.append(f"{re} cut~{int(r_cut)}")
        cut_txt = f", {' / '.join(cuts)}" if cuts else ""
        size_txt = ""
        if plan.get("product_size_bp"):
            size_txt = f", product={int(plan['product_size_bp'])} bp"
        if l_motif and r_motif:
            return f"double: {le}({l_motif}:{l_span}) + {re}({r_motif}:{r_span}){cut_txt}{size_txt}"
        return f"double: {le} at {l_span} + {re} at {r_span}{cut_txt}{size_txt}"

    return ""


def _best_restriction_single(position: int, sequence: str, sites_by_enzyme: dict[str, list[int]], strategy: str) -> Optional[dict]:
    candidates: list[dict] = []
    n = len(sequence)
    if n <= 0:
        return None

    for name, positions in sites_by_enzyme.items():
        if not positions:
            continue
        motif = RESTRICTION_ENZYME_DB[name]["site"]
        nearest = min(positions, key=lambda p: abs((p + len(motif) // 2) - position))
        dist = abs(nearest - position)
        candidates.append(
            {
                "type": strategy,
                "enzymes": [name],
                "sites": [nearest],
                "distance_to_site": dist,
                "sticky": bool(RESTRICTION_ENZYME_DB[name]["sticky"]),
                "star_risk": float(RESTRICTION_ENZYME_DB[name]["star_risk"]),
                "dam_sensitive": bool(RESTRICTION_ENZYME_DB[name]["dam_sensitive"]),
                "dcm_sensitive": bool(RESTRICTION_ENZYME_DB[name]["dcm_sensitive"]),
                "motif_seq": motif,
                "motif": motif,
                "motif_len": len(motif),
                "site_start_1based": nearest + 1,
                "site_end_1based": nearest + len(motif),
                "cut_1based": nearest + (len(motif) // 2),
                "window_product_bp": 0,
            }
        )

    if not candidates:
        return None

    return sorted(candidates, key=lambda item: item["distance_to_site"])[0]


def _best_restriction_double(
    position: int,
    sequence: str,
    sites_by_enzyme: dict[str, list[int]],
    max_product_bp: int,
    strategy_mode: str,
) -> Optional[dict]:
    seq_len = len(sequence)
    if seq_len <= 0:
        return None

    all_sites: list[tuple[int, str]] = []
    for name, pos_list in sites_by_enzyme.items():
        for p in pos_list:
            all_sites.append((p, name))
    if len(all_sites) < 2:
        return None

    all_sites.sort()
    left = [s for s in all_sites if s[0] <= position]
    right = [s for s in all_sites if s[0] >= position]
    if not left or not right:
        return None

    best: Optional[dict] = None
    candidates: list[dict] = []
    l_pool = left[-12:]
    r_pool = right[:12]

    for lpos, le in l_pool:
        for rpos, re in r_pool:
            if strategy_mode == "restriction_double" and le == re:
                continue
            if lpos == rpos and len(RESTRICTION_ENZYME_DB[le]["site"]) == len(RESTRICTION_ENZYME_DB[re]["site"]):
                continue

            if rpos <= lpos:
                continue

            product_size = abs(rpos - lpos) + max(len(RESTRICTION_ENZYME_DB[le]["site"]), len(RESTRICTION_ENZYME_DB[re]["site"]))
            if product_size <= 20 or product_size > max_product_bp:
                continue

            dist_pen = abs((lpos + len(RESTRICTION_ENZYME_DB[le]["site"]) // 2) - position) + abs(
                (rpos + len(RESTRICTION_ENZYME_DB[re]["site"]) // 2) - position
            )
            orientation_ok = RESTRICTION_ENZYME_DB[le]["directional"] or RESTRICTION_ENZYME_DB[re]["directional"] or le != re

            score = dist_pen
            candidates.append(
                {
                    "type": strategy_mode,
                    "enzymes": [le, re],
                    "sites": [lpos, rpos],
                    "product_size_bp": product_size,
                    "left_motif_seq": RESTRICTION_ENZYME_DB[le]["site"],
                    "right_motif_seq": RESTRICTION_ENZYME_DB[re]["site"],
                    "left_motif": RESTRICTION_ENZYME_DB[le]["site"],
                    "right_motif": RESTRICTION_ENZYME_DB[re]["site"],
                    "left_motif_len": len(RESTRICTION_ENZYME_DB[le]["site"]),
                    "right_motif_len": len(RESTRICTION_ENZYME_DB[re]["site"]),
                    "left_site_start_1based": lpos + 1,
                    "right_site_start_1based": rpos + 1,
                    "left_site_end_1based": lpos + len(RESTRICTION_ENZYME_DB[le]["site"]),
                    "right_site_end_1based": rpos + len(RESTRICTION_ENZYME_DB[re]["site"]),
                    "left_cut_1based": lpos + (len(RESTRICTION_ENZYME_DB[le]["site"]) // 2),
                    "right_cut_1based": rpos + (len(RESTRICTION_ENZYME_DB[re]["site"]) // 2),
                    "distance_to_site": int(dist_pen),
                    "orientation_ok": bool(orientation_ok),
                    "sticky": bool(RESTRICTION_ENZYME_DB[le]["sticky"] and RESTRICTION_ENZYME_DB[re]["sticky"]),
                    "star_risk": float(max(RESTRICTION_ENZYME_DB[le]["star_risk"], RESTRICTION_ENZYME_DB[re]["star_risk"])),
                    "dam_sensitive": bool(RESTRICTION_ENZYME_DB[le]["dam_sensitive"] or RESTRICTION_ENZYME_DB[re]["dam_sensitive"]),
                    "dcm_sensitive": bool(RESTRICTION_ENZYME_DB[le]["dcm_sensitive"] or RESTRICTION_ENZYME_DB[re]["dcm_sensitive"]),
                }
            )
            if best is None or score < best["distance_to_site"]:
                best = {"distance_to_site": score, **candidates[-1]}

    if best is None:
        return None
    return best


def _score_restriction_plan(
    plan: Optional[dict],
    host_context: HostContext,
    strategy_window_bp: Optional[int] = None,
) -> tuple[float, dict, list[str]]:
    if plan is None:
        return 0.0, {"missing_site": 1.0}, ["no compatible restriction pair/site in searchable range"]

    penalties = {
        "distance": 0.0,
        "methylation": 0.0,
        "star": 0.0,
        "directional": 0.0,
        "blunt": 0.0,
        "window": 0.0,
    }
    warnings: list[str] = []
    distance = float(plan.get("distance_to_site", 0))
    score = 25.0 - min(distance / 200.0, 12.0)

    if host_context.dam_dcm_sensitive:
        if plan.get("dam_sensitive"):
            score -= 1.8
            penalties["methylation"] += 0.7
            warnings.append("restriction enzyme is dam-sensitive")
        if plan.get("dcm_sensitive"):
            score -= 1.8
            penalties["methylation"] += 0.7
            warnings.append("restriction enzyme is dcm-sensitive")
    if plan.get("star_risk"):
        sr = float(plan.get("star_risk", 0.0))
        score -= 10.0 * sr
        penalties["star"] = sr

    if not plan.get("orientation_ok", True):
        score -= 2.5
        penalties["directional"] = 0.6
        warnings.append("directional compatibility not fully satisfied")

    if not plan.get("sticky", True):
        score -= 1.0
        penalties["blunt"] = 0.3
        warnings.append("blunt-end pair; lower ligation efficiency expected")

    if strategy_window_bp is not None and strategy_window_bp > 0 and distance > float(strategy_window_bp):
        window_penalty = min(2.0, (distance - float(strategy_window_bp)) / 300.0)
        score -= window_penalty * 1.5
        penalties["window"] = window_penalty
        warnings.append("restriction plan is outside requested strategy window")

    score = _safe01((score + 20.0) / 20.0)
    return score, penalties, warnings


def _score_pcr_strategy(
    plasmid_sequence: str,
    start: int,
    end: int,
    flank: int,
    primer_record: Any | None = None,
    max_product_bp: int = 0,
) -> tuple[list[dict], float, dict, list[str]]:
    try:
        from plasmid_primer_scoring import (
            design_and_score_inverse_pcr_from_features,
            design_and_score_inverse_pcr,
        )
    except Exception as exc:  # pragma: no cover
        return [], 0.0, {"import_error": 1.0}, [f"primer design import failed: {exc}"]

    try:
        pairs: list[Any]
        if primer_record is not None:
            pairs = design_and_score_inverse_pcr_from_features(
                record=primer_record,
                insert_start=start,
                insert_end=end,
                flank=flank,
                num_return=3,
                max_product_bp=max_product_bp,
                expected_product_bp=max(1, len(plasmid_sequence) - max(0, end - start)),
            )
        else:
            pairs = design_and_score_inverse_pcr(
                plasmid_sequence=plasmid_sequence,
                insert_start=start,
                insert_end=end,
                flank=flank,
                num_return=3,
            )
    except Exception as exc:  # pragma: no cover
        return [], 0.0, {"design_error": 1.0}, [f"primer design failed: {exc}"]

    if not pairs:
        return [], 0.0, {"no_pairs": 1.0}, ["no valid primer pair found"]

    best = pairs[0]
    score = max(0.0, 3.0 - (best.primer_pair_penalty / 6.0))
    score = _safe01(score / 3.0) * 1.2
    payload = {
        "enzymes": ["primer_features"],
        "type": "inverse_pcr",
        "best_pair": best.to_dict(),
        "pair_count": len(pairs),
    }
    penalty = {"primer_penalty": round(best.primer_pair_penalty, 2)}
    warnings: list[str] = []
    if best.tm_balance > 3.0:
        warnings.append("Tm gap slightly large")
    if not best.unique:
        warnings.append("off-target risk elevated (non-unique)")
    return [p.to_dict() for p in pairs], score, penalty, warnings


def _score_candidate(
    safe_result: SafeZoneResult,
    plasmid_sequence: str,
    start: int,
    end: int,
    params: CloneParams,
    primer_record: Any | None = None,
) -> Candidate:
    interval_start = start
    interval_end = end
    risk = _calc_risk(
        plasmid_len=safe_result.length,
        insert_len=max(0, params.insert.length_bp),
        gc_content=params.insert.gc_content,
        repeat_like=params.insert.repeat_like or 0.0,
        toxic=params.insert.toxic_gene,
        risk_ratio_cap=max(0.01, params.risk_ratio_cap),
    )
    risk_breakdown = {
        "size_ratio": _safe01((params.insert.length_bp / max(1, safe_result.length)) / max(0.01, params.risk_ratio_cap)),
        "gc_risk": (0.0 if params.insert.gc_content is None else _safe01(abs(params.insert.gc_content - 0.5) / 0.5)),
        "repeat_like": _safe01(params.insert.repeat_like or 0.0),
        "toxic": bool(params.insert.toxic_gene),
    }

    base_score = (1.0 - risk) * 100.0 * params.risk_weight
    strategy_penalties: dict[str, float] = {}
    reasons: list[str] = []
    strategy_payload: dict = {}
    strategy_candidates: list[dict] = []
    strategy_score = 0.0
    primer_pairs: list[dict] = []
    strategy_summary: str | None = None

    if safe_result.topology == "circular" and interval_start == 0 and interval_end == safe_result.length:
        reasons.append("full circular allowance")
    if params.host_context.dam_dcm_sensitive:
        reasons.append("host methylation sensitive")
    if params.insert.toxic_gene:
        reasons.append("toxic insert warning")

    if params.target_mode == "fusion":
        reasons.append("fusion mode active: in-frame and stop codon checks deferred to downstream")

    if params.cloning_strategy in {"restriction_single", "restriction_double"}:
        sequence = str(plasmid_sequence)
        site_index = _build_restriction_sites(sequence)
        if params.cloning_strategy == "restriction_single":
            best = _best_restriction_single(start, sequence, site_index, params.cloning_strategy)
        else:
            best = _best_restriction_double(start, sequence, site_index, params.max_product_bp, params.cloning_strategy)
        if best is not None:
            strategy_payload = best
            strategy_candidates = [best]
            strategy_summary = _format_restriction_summary(best, params.cloning_strategy)
            strategy_score, penalties, warnings = _score_restriction_plan(
                best,
                params.host_context,
                strategy_window_bp=params.strategy_window_bp,
            )
            strategy_penalties.update(penalties)
            reasons.extend(warnings)
        else:
            reasons.append("no compatible restriction plan found near candidate")
            strategy_payload = {}
            strategy_score = 0.0
            strategy_penalties["missing_plan"] = 1.0
            strategy_summary = "no compatible restriction plan found"

    elif params.cloning_strategy == "inverse_pcr":
        pairs, pscore, penalties, warnings = _score_pcr_strategy(
            plasmid_sequence=plasmid_sequence,
            start=start,
            end=end,
            flank=params.flank_bp,
            primer_record=primer_record,
            max_product_bp=params.max_product_bp,
        )
        primer_pairs = pairs
        strategy_candidates = pairs[:3]
        strategy_score = pscore
        strategy_penalties.update(penalties)
        reasons.extend(warnings)
        if pairs:
            strategy_payload = {
                "type": "inverse_pcr",
                "best_pair": pairs[0],
                "count": len(pairs),
            }
            strategy_summary = f"inverse_pcr: GB-loaded primer features {len(pairs)} pair(s)"
    else:
        reasons.append(f"unknown strategy: {params.cloning_strategy}")

    total = base_score + strategy_score * 15.0 - 10.0 * sum(float(v) for v in strategy_penalties.values())
    total = round(total, 6)

    center = (start + end) // 2 if end > start else start
    closest_feature, feature_distance = _find_nearest_feature(center, safe_result.features)
    return Candidate(
        interval_start=interval_start,
        interval_end=interval_end,
        start=start,
        end=end,
        strategy=params.cloning_strategy,
        score=total,
        risk=risk,
        strategy_score=strategy_score,
        reasons=reasons,
        closest_feature=closest_feature,
        feature_distance_bp=feature_distance,
        primer_pairs=primer_pairs,
        strategy_candidates=[strategy_payload] if strategy_payload else strategy_candidates,
        strategy_penalties=strategy_penalties,
        strategy_summary=strategy_summary,
        risk_breakdown=risk_breakdown,
    )


def build_candidates(
    safe_result: SafeZoneResult,
    params: CloneParams,
    plasmid_sequence: str,
    primer_record: Any | None = None,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    insert_len = max(0, params.insert.length_bp)

    for interval_start, interval_end in safe_result.safe_zones:
        L = max(0, interval_end - interval_start)
        if L <= 0:
            continue
        if insert_len and insert_len >= L:
            continue

        for start in _safe_zone_candidates(
            interval_start=interval_start,
            interval_end=interval_end,
            insert_len=insert_len,
            sample_size=max(1, params.candidate_per_zone),
        ):
            end = start + insert_len
            if end > interval_end:
                end = interval_end
                start = end - insert_len

            cand = _score_candidate(
                safe_result=safe_result,
                plasmid_sequence=plasmid_sequence,
                start=start,
                end=end,
                params=params,
                primer_record=primer_record,
            )
            candidates.append(cand)

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[: max(1, params.top_k)]


def _build_visualization_payload(
    record_id: str,
    safe_result: SafeZoneResult,
    candidates: list[Candidate],
) -> dict:
    return {
        "record_id": record_id,
        "length": safe_result.length,
        "topology": safe_result.topology,
        "safe_zones": [{"start": s + 1, "end": e, "label": "safe"} for s, e in safe_result.safe_zones],
        "protected_zones": [
            {"start": s + 1, "end": e, "label": "protected_or_buffered", "importance": "protected"}
            for s, e in safe_result.protected_plus_buffer
        ],
        "features": [
            {
                "start": f.start + 1,
                "end": f.end,
                "label": getattr(f, "label", ""),
                "type": f.feature_type,
                "importance": getattr(f, "importance", "").value if getattr(f, "importance", None) else "",
            }
            for f in safe_result.features
        ],
        "candidates": [
            {
                "start": c.start + 1,
                "end": c.end,
                "score": c.score,
                "strategy": c.strategy,
                "risk": c.risk,
            }
            for c in candidates
        ],
    }


def _build_safezone_config(
    params: CloneParams,
) -> SafeZoneConfig:
    return SafeZoneConfig(
        buffer_bp=max(0, params.buffer_bp),
        target_mode=params.target_mode,
        include_disruptable=params.include_disruptable,
        include_neutral=params.include_neutral,
    )


def run_pipeline(
    gb_path: str | Path,
    params: CloneParams,
    db_path: str | Path | None = None,
    store: bool = False,
    manual_tags: Optional[Dict[str, str]] = None,
    topology_override: Optional[str] = None,
) -> PipelineResult:
    record = parse_genbank(gb_path)
    cfg = _build_safezone_config(params)
    cfg.topology = topology_override

    safe_result = build_safe_zones(record, cfg=cfg, manual_labels=manual_tags)
    safe_result_cfg = SafeZoneConfig(
        buffer_bp=cfg.buffer_bp,
        target_mode=cfg.target_mode,
        include_disruptable=cfg.include_disruptable,
        include_neutral=cfg.include_neutral,
        topology=topology_override,
    )
    candidates = build_candidates(
        safe_result=safe_result,
        params=params,
        plasmid_sequence=str(record.seq),
        primer_record=record,
    )
    plasmid_id: Optional[int] = None

    if store and db_path is not None:
        init_db(db_path)
        plasmid_id, _ = upsert_plasmid(
            db_path=db_path,
            gb_path=gb_path,
            cfg=safe_result_cfg,
            manual_labels=manual_tags,
        )

    return PipelineResult(
        safe_result=safe_result,
        record_id=record.id,
        topology=safe_result.topology,
        length=safe_result.length,
        safe_zones=safe_result.safe_zones,
        candidates=candidates,
        risk_ratio_cap=params.risk_ratio_cap,
        strategy=params.cloning_strategy,
        target_mode=params.target_mode,
        host=params.host_context.host,
        plasmid_id=plasmid_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="원형 플라스미드 클로닝 후보 통합 엔진")
    parser.add_argument("genbank")
    parser.add_argument("--mode", default="neutral", choices=["neutral", "expression", "fusion"])
    parser.add_argument("--strategy", default="inverse_pcr")
    parser.add_argument("--insert-length", type=int, default=0)
    parser.add_argument("--insert-gc", type=float, default=None)
    parser.add_argument("--insert-extreme-gc", type=float, default=None)
    parser.add_argument("--insert-repeat-like", type=float, default=0.0)
    parser.add_argument("--buffer", type=int, default=100)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--candidate-per-zone", type=int, default=3)
    parser.add_argument("--flank", type=int, default=350)
    parser.add_argument("--risk-ratio-cap", type=float, default=0.25)
    parser.add_argument("--host", default="E. coli")
    parser.add_argument("--dam-dcm-sensitive", action="store_true")
    parser.add_argument("--risk-weight", type=float, default=1.0)
    parser.add_argument("--strategy-window", type=int, default=7000)
    parser.add_argument("--max-product", type=int, default=4000)
    parser.add_argument("--toxic", action="store_true")
    parser.add_argument("--manual-tag", action="append", default=[], help="feature_id=importance label (e.g. lacZ=disruptable)")
    parser.add_argument("--db", default=None)
    parser.add_argument("--store", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--export-db-json", type=str, default=None)
    parser.add_argument("--visualization-json", type=str, default=None)
    args = parser.parse_args()

    params = CloneParams(
        target_mode=_normalize_mode(args.mode),
        cloning_strategy=_normalize_strategy(args.strategy),
        insert=InsertMetadata(
            length_bp=max(0, args.insert_length),
            gc_content=args.insert_gc,
            gc_extreme=args.insert_extreme_gc,
            toxic_gene=args.toxic,
            repeat_like=args.insert_repeat_like,
        ),
        buffer_bp=max(0, args.buffer),
        top_k=max(1, args.top_k),
        candidate_per_zone=max(1, args.candidate_per_zone),
        flank_bp=max(80, args.flank),
        risk_ratio_cap=max(0.01, args.risk_ratio_cap),
        risk_weight=max(0.0, args.risk_weight),
        strategy_window_bp=max(1000, args.strategy_window),
        max_product_bp=max(1, args.max_product),
    )
    params.host_context = HostContext(
        host=args.host,
        dam_dcm_sensitive=args.dam_dcm_sensitive,
        methylation_sensitive=args.dam_dcm_sensitive,
    )

    manual_tags, manual_tag_warnings = _parse_manual_tags(args.manual_tag)
    for warn in manual_tag_warnings:
        print(f"warning: {warn}")

    if params.cloning_strategy == "inverse_pcr" and params.insert.length_bp <= 0:
        params.insert.length_bp = 0

    result = run_pipeline(
        gb_path=args.genbank,
        params=params,
        db_path=args.db,
        store=args.store,
        manual_tags=manual_tags,
    )

    if args.json:
        print(result.to_json())
    else:
        print(f"record={result.record_id}")
        print(f"topology={result.topology}")
        print(f"length={result.length}")
        print(f"strategy={result.strategy}")
        print(f"target_mode={result.target_mode}")
        print(f"host={result.host}")
        print("safe zones:")
        for s, e in result.safe_zones:
            print(f" - {s+1}-{e}")
        print("top candidates:")
        for c in result.candidates:
            print(json.dumps(c.as_1based(), ensure_ascii=False))

    if args.visualization_json:
        payload = _build_visualization_payload(
            result.record_id,
            result.safe_result or build_safe_zones(parse_genbank(args.genbank), cfg=_build_safezone_config(params), manual_labels=manual_tags),
            result.candidates,
        )
        Path(args.visualization_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"exported_visualization={args.visualization_json}")

    if args.db and args.export_db_json:
        latest_id: Optional[int] = result.plasmid_id
        if latest_id is None:
            latest_id, _ = upsert_plasmid(
                db_path=args.db,
                gb_path=args.genbank,
                cfg=_build_safezone_config(params),
                manual_labels=manual_tags,
            )
        if latest_id:
            payload = export_json_payload(latest_id, args.db)
            Path(args.export_db_json).write_text(payload, encoding="utf-8")
            print(f"exported_db_payload={args.export_db_json}")


if __name__ == "__main__":
    main()
