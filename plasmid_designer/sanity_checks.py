from __future__ import annotations

from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord

from plasmid_safezone_engine import SafeZoneConfig, build_safe_zones


def _mock_record(seq_len: int, topology: str = "circular") -> SeqRecord:
    seq = Seq("A" * seq_len)
    record = SeqRecord(seq)
    record.id = f"mock_{seq_len}_{topology}"
    record.name = "mock"
    record.annotations["topology"] = topology
    return record


def _feat(start: int, end: int, ftype: str, quals: dict) -> SeqFeature:
    return SeqFeature(FeatureLocation(start, end), type=ftype, qualifiers=quals)


def _annotate(record: SeqRecord, feats: list[SeqFeature]) -> None:
    record.features = feats


def _interval_intersects(start: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    for s, e in intervals:
        if max(s, start) < min(e, end):
            return True
    return False


def check_wrap_around_protection() -> tuple[bool, str]:
    rec = _mock_record(100)
    # origin wraps around [90, 10) with +100 bp buffer; should stay protected in both edges.
    rec.features = [
        _feat(90, 110, "rep_origin", {"product": ["p15A origin"]}),
        _feat(40, 45, "CDS", {"gene": ["ampR"]}),
    ]
    cfg = SafeZoneConfig(target_mode="neutral", buffer_bp=5)
    result = build_safe_zones(rec, cfg)
    safe_points = result.safe_zones
    for s, e in safe_points:
        if not (0 <= s < e <= result.length):
            return False, "invalid interval order"

    blocked = any(s <= p < e for s, e in result.protected_plus_buffer for p in (0, 5, 95, 99))
    if not blocked:
        return False, "wrap-around protected region lost"

    return True, f"safe_count={len(safe_points)}"


def check_antibiotic_protected() -> tuple[bool, str]:
    rec = _mock_record(120)
    rec.features = [
        _feat(20, 60, "CDS", {"gene": ["ampicillin resistance protein"], "product": ["bla"]}),
        _feat(70, 80, "gene", {"gene": ["mCherry"]}),
    ]
    result = build_safe_zones(rec)
    protected = result.protected_plus_buffer
    if any(s <= 20 < e or s <= 59 < e for s, e in protected):
        return True, f"ampR masked: segments={len(protected)}"
    return False, "ampR CDS not masked"


def check_linearization_choice() -> tuple[bool, str]:
    rec = _mock_record(50, topology="linear")
    rec.features = [_feat(0, 5, "rep_origin", {"product": ["vector origin"]})]
    result = build_safe_zones(rec)
    if result.topology != "linear":
        return False, "linearity not preserved"
    for s, e in result.protected_plus_buffer:
        if not (0 <= s < e <= len(rec.seq)):
            return False, "linear interval clipped"
    return True, "linear handled"


def check_lacz_disruptable_in_neutral() -> tuple[bool, str]:
    rec = _mock_record(1000)
    rec.features = [
        _feat(0, 20, "rep_origin", {"product": ["ColE1 origin"]}),
        _feat(700, 760, "CDS", {"product": ["chloramphenicol resistance"], "gene": ["cat"]}),
        _feat(120, 230, "CDS", {"gene": ["lacz alpha"], "product": ["lacZ alpha"]}),
    ]
    result = build_safe_zones(rec, SafeZoneConfig(target_mode="neutral", buffer_bp=20))
    if not _interval_intersects(120, 230, result.safe_zones):
        return False, "lacz alpha interval was unexpectedly blocked in neutral mode"
    if _interval_intersects(700, 760, result.safe_zones):
        return False, "antibiotic CDS still leaked into safe zone (cat should be protected)"
    return True, "lacz alpha remains available while resistance is masked"


def check_standard_like_vector_regression() -> tuple[bool, str]:
    rec = _mock_record(3000)
    rec.features = [
        _feat(2890, 3010, "rep_origin", {"product": ["pUC ori"]}),
        _feat(190, 230, "CDS", {"gene": ["lacZ"], "product": ["lacz"]}),
        _feat(260, 520, "CDS", {"gene": ["replication proteins"], "product": ["unknown"]}),
        _feat(800, 1200, "CDS", {"gene": ["ampicillin"], "product": ["ampicillin resistance"]}),
    ]
    cfg = SafeZoneConfig(target_mode="neutral", buffer_bp=90)
    result = build_safe_zones(rec, cfg)
    if not result.safe_zones:
        return False, "standard-like mock vector produced no safe zones"
    if _interval_intersects(800, 1200, result.protected_plus_buffer):
        return True, "mock standard vector regression passed"
    return False, "ampicillin interval is not fully protected"


def check_expression_anchor_restriction() -> tuple[bool, str]:
    rec = _mock_record(200)
    rec.features = [
        _feat(20, 60, "promoter", {"product": ["T7 promoter"]}),
        _feat(120, 170, "CDS", {"gene": ["lacZ"], "product": ["beta-galactosidase"]}),
    ]
    cfg = SafeZoneConfig(target_mode="expression", buffer_bp=10)
    result = build_safe_zones(rec, cfg)
    if not result.safe_zones:
        return False, "expression mode produced no safe zone"
    if not all(20 <= s and e <= 60 for s, e in result.safe_zones):
        return False, "safe zones include non-expression-anchor regions"
    return True, "expression mode constrained to promoter interval"


def run_sanity_checks() -> dict:
    checks = [
        ("wrap_around_protection", check_wrap_around_protection),
        ("antibiotic_protected", check_antibiotic_protected),
        ("linearization_choice", check_linearization_choice),
        ("lacz_disruptable_neutral", check_lacz_disruptable_in_neutral),
        ("standard_like_regression", check_standard_like_vector_regression),
        ("expression_anchor_restriction", check_expression_anchor_restriction),
    ]
    result = {"ok": True, "cases": []}
    for name, fn in checks:
        try:
            passed, msg = fn()
        except Exception as exc:  # pragma: no cover
            passed = False
            msg = f"{exc}"

        if not passed:
            result["ok"] = False
        result["cases"].append({"name": name, "passed": bool(passed), "msg": msg})
    return result


def main() -> None:
    report = run_sanity_checks()
    if report["ok"]:
        print("[OK] Sanity checks passed")
    else:
        print("[FAIL] Sanity checks failed")
    for case in report["cases"]:
        print(f" - {case['name']}: {'PASS' if case['passed'] else 'FAIL'} ({case['msg']})")


if __name__ == "__main__":
    main()
