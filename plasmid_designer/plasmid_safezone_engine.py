from __future__ import annotations

import argparse
import hashlib
import json
import io
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from Bio import SeqIO
from Bio.SeqRecord import SeqRecord

Interval = Tuple[int, int]


class ImportanceLabel(str, Enum):
    PROTECTED = "protected"
    DISRUPTABLE = "disruptable"
    NEUTRAL = "neutral"


TARGET_MODES = {"neutral", "expression", "fusion"}


@dataclass
class FeatureHit:
    feature_type: str
    label: str
    strand: int
    qualifiers: Dict[str, List[str]]
    start: int
    end: int
    importance: ImportanceLabel


@dataclass
class SafeZoneConfig:
    buffer_bp: int = 100
    protected_labels: Tuple[ImportanceLabel, ...] = (ImportanceLabel.PROTECTED,)
    target_mode: str = "neutral"
    include_disruptable: bool = True
    include_neutral: bool = True
    topology: Optional[str] = None


@dataclass
class SafeZoneResult:
    sequence_id: str
    topology: str
    length: int
    features: List[FeatureHit]
    protected_mask: List[Interval]
    protected_plus_buffer: List[Interval]
    safe_zones: List[Interval]

    def to_json(self) -> str:
        payload = {
            "sequence_id": self.sequence_id,
            "topology": self.topology,
            "length": self.length,
            "features": [
                {
                    "type": f.feature_type,
                    "label": f.label,
                    "strand": f.strand,
                    "start": f.start,
                    "end": f.end,
                    "importance": f.importance.value,
                    "qualifiers": f.qualifiers,
                }
                for f in self.features
            ],
            "protected_mask": [
                {
                    "start": s + 1,
                    "end": e,
                    "topology": "half-open->1-based inclusive"
                }
                for s, e in self.protected_mask
            ],
            "buffered_protected": [
                {
                    "start": s + 1,
                    "end": e,
                    "topology": "half-open->1-based inclusive"
                }
                for s, e in self.protected_plus_buffer
            ],
            "safe_zones": [
                {
                    "start": s + 1,
                    "end": e,
                    "topology": "half-open->1-based inclusive"
                }
                for s, e in self.safe_zones
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)


_PROTECTED_FEATURE_TYPE_KEYWORDS = {
    "rep_origin",
    "replication_origin",
    "origin_of_replication",
    "origin of replication",
    "plasmid_rep_origin",
    "oriT",
    "originoftor",
    "origin_of_transfer",
}


_PROTECTED_SELECTOR = [
    "ampicillin",
    "chloramphenicol",
    "kanamycin",
    "kan resistance",
    "streptomycin",
    "tetracycline",
    "carbenicillin",
    "gentamicin",
    "spectinomycin",
    "amp resistance",
    "km resistance",
    "cat gene",
]

_DISRUPTABLE_SELECTOR = [
    "lacz",
    "lacz alpha",
    "ccdb",
    "ccd b",
    "screening",
    "screening cassette",
    "blue white",
]

_NEUTRAL_SELECTOR = [
    "gfp",
    "rfp",
    "yfp",
    "venus",
    "tdtomato",
    "luciferase",
    "mcherry",
]


_INSDC_SELECTOR_BY_TYPE: dict[ImportanceLabel, list[str]] = {
    ImportanceLabel.PROTECTED: [
        "rep_origin",
        "replication_origin",
        "origin",
        "gene",
        "cds",
        "misc_feature",
        "marker",
    ],
    ImportanceLabel.DISRUPTABLE: [
        "misc_feature",
        "primer_bind",
        "repeat_region",
        "regulatory",
    ],
    ImportanceLabel.NEUTRAL: [
        "CDS",
        "gene",
        "misc_feature",
        "mature_protein_region",
    ],
}

_INSDC_QUALIFIER_KEYS = (
    "product",
    "note",
    "label",
    "gene",
    "regulatory_class",
    "function",
    "standard_name",
    "clone",
    "allele",
    "comment",
    "source",
)

_EXPRESSION_ANCHOR_TERMS = ("promoter", "terminator")


def _qualifier_values(feature, key: str) -> List[str]:
    return [str(v).lower() for v in feature.qualifiers.get(key, [])]


def _contains_any(feature, keys: Sequence[str], terms: Sequence[str]) -> bool:
    if not terms:
        return False
    flat = [v for k in keys for v in _qualifier_values(feature, k)]
    if not flat:
        return False
    joined = " ".join(flat)
    return any(term in joined for term in terms)


def _is_expression_anchor(feature, feature_type: str, qualifiers: dict[str, list[str]]) -> bool:
    if _match_type(feature_type, ("promoter", "terminator")):
        return True

    joined_qual = " ".join(qualifiers["product"] + qualifiers["note"] + qualifiers["gene"] + qualifiers["regulatory_class"])
    return any(term in joined_qual for term in _EXPRESSION_ANCHOR_TERMS)


def _match_type(feature_type: str, keys: Iterable[str]) -> bool:
    t = feature_type.lower()
    return any(k in t for k in keys)


def infer_importance(feature, target_mode: str = "neutral", manual_labels: Optional[Dict[str, str]] = None) -> ImportanceLabel:
    manual = None
    if manual_labels:
        if feature.id and feature.id in manual_labels:
            manual = manual_labels[feature.id]
        else:
            locus = feature.qualifiers.get("locus_tag", [None])[0]
            if locus and locus in manual_labels:
                manual = manual_labels[locus]
    if manual:
        return ImportanceLabel(manual)

    feature_type = (feature.type or "").lower()

    qualifiers = {
        "product": [q.lower() for q in feature.qualifiers.get("product", [])],
        "note": [q.lower() for q in feature.qualifiers.get("note", [])],
        "gene": [q.lower() for q in feature.qualifiers.get("gene", [])],
        "label": [q.lower() for q in feature.qualifiers.get("label", [])],
        "regulatory_class": [q.lower() for q in feature.qualifiers.get("regulatory_class", [])],
    }

    if _match_type(feature_type, _PROTECTED_FEATURE_TYPE_KEYWORDS) or (
        feature_type in {"cds", "gene", "coding sequence"} and
        any(sel in " ".join(qualifiers["product"] + qualifiers["note"] + qualifiers["gene"]) for sel in _PROTECTED_SELECTOR)
    ):
        return ImportanceLabel.PROTECTED

    if _contains_any(feature, _INSDC_QUALIFIER_KEYS, _DISRUPTABLE_SELECTOR):
        return ImportanceLabel.DISRUPTABLE

    if _contains_any(feature, _INSDC_QUALIFIER_KEYS, _NEUTRAL_SELECTOR):
        return ImportanceLabel.NEUTRAL

    if feature_type in {"regulatory", "misc_feature", "repeat_region", "protein_bind", "primer_bind"}:
        return ImportanceLabel.DISRUPTABLE

    return ImportanceLabel.NEUTRAL


def _merge_intervals(intervals: Sequence[Interval], length: int) -> List[Interval]:
    if not intervals:
        return []
    items = sorted(
        [iv for iv in intervals if iv[0] < iv[1] and iv[0] >= 0 and iv[1] <= length],
        key=lambda x: x[0],
    )
    merged: List[Interval] = []
    cur_s, cur_e = items[0]
    for s, e in items[1:]:
        if s <= cur_e:
            if e > cur_e:
                cur_e = e
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
    merged.append((cur_s, cur_e))
    return merged


def _intersect_intervals(left: Sequence[Interval], right: Sequence[Interval]) -> List[Interval]:
    if not left or not right:
        return []

    max_len = 0
    if left:
        max_len = max(max_len, max(i[1] for i in left))
    if right:
        max_len = max(max_len, max(i[1] for i in right))

    l_intervals = _merge_intervals(left, max_len)
    r_intervals = _merge_intervals(right, max_len)
    result: List[Interval] = []
    i = 0
    j = 0

    while i < len(l_intervals) and j < len(r_intervals):
        s = max(l_intervals[i][0], r_intervals[j][0])
        e = min(l_intervals[i][1], r_intervals[j][1])
        if s < e:
            result.append((s, e))

        if l_intervals[i][1] <= r_intervals[j][1]:
            i += 1
        else:
            j += 1
    return result


def _split_wrapped_interval(start: int, end: int, length: int) -> List[Interval]:
    if length <= 0:
        return []
    if start == end:
        return []

    width = end - start
    if width >= length:
        return [(0, length)]
    if width <= 0:
        # malformed but still valid as a tiny gap in some tools; avoid invalid interval
        return []

    s = start % length
    e_raw = s + width
    if e_raw <= length:
        return [(s, e_raw)]
    return [(s, length), (0, e_raw - length)]


def _feature_intervals(feature, length: int, is_circular: bool) -> List[Interval]:
    loc = feature.location
    intervals: List[Interval] = []
    if hasattr(loc, "parts") and len(loc.parts) > 1:
        for p in loc.parts:
            intervals.extend(_feature_intervals(type("obj", (), {"location": p, "type": feature.type})(), length, is_circular))
        return intervals

    start = int(loc.start)
    end = int(loc.end)

    if not is_circular:
        s = max(0, min(length, start))
        e = max(0, min(length, end))
        if s < e:
            intervals.append((s, e))
        return intervals

    # circular
    return _split_wrapped_interval(start, end, length)


def _expand_interval(interval: Interval, buffer_bp: int, length: int, is_circular: bool) -> List[Interval]:
    if buffer_bp <= 0:
        return [interval]

    s, e = interval
    if is_circular:
        return _split_wrapped_interval(s - buffer_bp, e + buffer_bp, length)

    s2 = max(0, s - buffer_bp)
    e2 = min(length, e + buffer_bp)
    if s2 < e2:
        return [(s2, e2)]
    return []


def _complement(intervals: Sequence[Interval], length: int) -> List[Interval]:
    if length <= 0:
        return []
    if not intervals:
        return [(0, length)]

    merged = _merge_intervals(intervals, length)
    safe: List[Interval] = []
    cursor = 0
    for s, e in merged:
        if s > cursor:
            safe.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < length:
        safe.append((cursor, length))
    return safe


def _to_report_intervals(intervals: Sequence[Interval]) -> List[Tuple[int, int]]:
    return [(s + 1, e) for s, e in intervals]


def _feature_payload(feature, start: int, end: int, length: int, cfg: SafeZoneConfig) -> FeatureHit:
    importance = infer_importance(feature, cfg.target_mode)
    return FeatureHit(
        feature_type=feature.type,
        label=getattr(feature, "id", "") or feature.qualifiers.get("locus_tag", [""])[0],
        strand=int(feature.location.strand) if feature.location.strand is not None else 0,
        qualifiers={k: [str(v) for v in vlist] for k, vlist in feature.qualifiers.items()},
        start=start,
        end=end,
        importance=importance,
    )


def build_safe_zones(
    record: SeqRecord,
    cfg: Optional[SafeZoneConfig] = None,
    manual_labels: Optional[Dict[str, str]] = None,
) -> SafeZoneResult:
    cfg = cfg or SafeZoneConfig()
    if cfg.target_mode not in TARGET_MODES:
        raise ValueError(f"invalid target_mode={cfg.target_mode}")

    length = len(record.seq)
    if length <= 0:
        raise ValueError("empty sequence")

    topology = str(record.annotations.get("topology", cfg.topology or "circular")).lower()
    is_circular = topology != "linear"

    feature_hits: List[FeatureHit] = []
    expression_anchor_intervals: List[Interval] = []
    protected: List[Interval] = []
    safe_candidates: List[Interval] = []

    for feat in record.features:
        intervals = _feature_intervals(feat, length, is_circular)
        if not intervals:
            continue

        for s, e in intervals:
            importance = infer_importance(feat, target_mode=cfg.target_mode, manual_labels=manual_labels)
            feat_qualifiers = {
                "product": [q.lower() for q in feat.qualifiers.get("product", [])],
                "note": [q.lower() for q in feat.qualifiers.get("note", [])],
                "gene": [q.lower() for q in feat.qualifiers.get("gene", [])],
                "label": [q.lower() for q in feat.qualifiers.get("label", [])],
                "regulatory_class": [q.lower() for q in feat.qualifiers.get("regulatory_class", [])],
            }
            if _is_expression_anchor(feat, (feat.type or "").lower(), feat_qualifiers):
                expression_anchor_intervals.append((s, e))

            if importance in cfg.protected_labels:
                protected.extend(_expand_interval((s, e), cfg.buffer_bp, length, is_circular))
                feature_hits.append(_feature_payload(feat, s, e, length, cfg))
            elif importance == ImportanceLabel.DISRUPTABLE and cfg.include_disruptable:
                feature_hits.append(_feature_payload(feat, s, e, length, cfg))
            elif importance == ImportanceLabel.NEUTRAL and cfg.include_neutral:
                feature_hits.append(_feature_payload(feat, s, e, length, cfg))

    protected_buffered = _merge_intervals(protected, length)
    safe = _complement(protected_buffered, length)

    if cfg.target_mode == "expression":
        expr_intervals = _merge_intervals(expression_anchor_intervals, length)
        if expr_intervals:
            safe = _intersect_intervals(safe, expr_intervals)

    for feat in safe:
        if feat[0] < feat[1]:
            safe_candidates.append(feat)

    return SafeZoneResult(
        sequence_id=record.id,
        topology="circular" if is_circular else "linear",
        length=length,
        features=feature_hits,
        protected_mask=protected,
        protected_plus_buffer=protected_buffered,
        safe_zones=safe_candidates,
    )


def parse_genbank(path: Path | str) -> SeqRecord:
    raw_path = Path(path)
    raw_bytes = raw_path.read_bytes()
    errors: list[str] = []
    for encoding in ("utf-8", "utf-8-sig", "latin1", "cp932"):
        try:
            candidate = raw_bytes.decode(encoding).lstrip("\ufeff")
        except Exception as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        try:
            return SeqIO.read(io.StringIO(candidate), "genbank")
        except Exception as exc:
            errors.append(f"{encoding}/genbank: {exc}")

    # try one more pass for common FASTA mislabeled inputs
    for encoding in ("utf-8", "utf-8-sig", "latin1", "cp932"):
        try:
            candidate = raw_bytes.decode(encoding).lstrip("\ufeff")
        except Exception as exc:
            continue
        try:
            return SeqIO.read(io.StringIO(candidate), "fasta")
        except Exception as exc:
            errors.append(f"{encoding}/fasta: {exc}")

    raise ValueError(f"failed to parse genbank: {raw_path} / {errors}")


def safe_zone_report(record: SeqRecord, cfg: Optional[SafeZoneConfig] = None, manual_labels: Optional[Dict[str, str]] = None) -> Dict[str, object]:
    cfg = cfg or SafeZoneConfig()
    result = build_safe_zones(record, cfg, manual_labels=manual_labels)
    return {
        "sequence_id": result.sequence_id,
        "topology": result.topology,
        "length": result.length,
        "safe_zones_1based_inclusive": _to_report_intervals(result.safe_zones),
        "buffered_protected_1based_inclusive": _to_report_intervals(result.protected_plus_buffer),
    }


def feature_fingerprint(record: SeqRecord) -> str:
    payload = json.dumps({
        "id": record.id,
        "description": record.description,
        "size": len(record.seq),
        "md5": hashlib.md5(str(record.seq).encode("utf-8")).hexdigest(),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="GenBank 기반 원형 플라스미드 Safe Zone 뼈대 계산")
    parser.add_argument("genbank", help="input GenBank file")
    parser.add_argument("--mode", default="neutral", choices=sorted(TARGET_MODES), help="target mode")
    parser.add_argument("--buffer", type=int, default=100, help="protected feature buffer bp")
    parser.add_argument("--topology", default=None, help="override topology: circular|linear")
    parser.add_argument("--json", action="store_true", help="print JSON payload")
    args = parser.parse_args()

    cfg = SafeZoneConfig(
        buffer_bp=max(0, args.buffer),
        target_mode=args.mode,
        topology=args.topology,
    )
    record = parse_genbank(args.genbank)
    result = build_safe_zones(record, cfg)

    if args.json:
        print(result.to_json())
        return

    print(f"Sequence ID: {result.sequence_id}")
    print(f"Length: {result.length}")
    print(f"Topology: {result.topology}")
    print("Safe intervals (1-based inclusive):")
    for s, e in _to_report_intervals(result.safe_zones):
        print(f"  {s}-{e}")


if __name__ == "__main__":
    main()
