from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from plasmid_safezone_engine import SafeZoneConfig, SafeZoneResult, parse_genbank, build_safe_zones

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plasmids (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  record_id TEXT NOT NULL,
  sequence_id TEXT,
  topology TEXT NOT NULL,
  length INTEGER NOT NULL,
  md5 TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  gb_path TEXT,
  source_path TEXT,
  source_sha256 TEXT,
  gb_blob TEXT NOT NULL,
  annotations_json TEXT,
  parse_rules_json TEXT,
  parse_signature TEXT,
  safezone_version INTEGER DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS features (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plasmid_id INTEGER NOT NULL,
  feature_type TEXT NOT NULL,
  label TEXT,
  start INTEGER NOT NULL,
  end INTEGER NOT NULL,
  strand INTEGER DEFAULT 0,
  importance TEXT NOT NULL,
  qualifiers_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(plasmid_id) REFERENCES plasmids(id)
);

CREATE TABLE IF NOT EXISTS manual_tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plasmid_id INTEGER NOT NULL,
  feature_key TEXT NOT NULL,
  importance TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(plasmid_id, feature_key),
  FOREIGN KEY(plasmid_id) REFERENCES plasmids(id)
);

CREATE TABLE IF NOT EXISTS safe_intervals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plasmid_id INTEGER NOT NULL,
  interval_kind TEXT NOT NULL,
  start INTEGER NOT NULL,
  end INTEGER NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(plasmid_id) REFERENCES plasmids(id)
);

CREATE TABLE IF NOT EXISTS _meta (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event TEXT NOT NULL,
  ts TEXT NOT NULL
);
"""


def _read_text_auto(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "latin1", "cp932"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


def init_db(db_path: str | Path) -> None:
    db_path = Path(db_path)
    with sqlite3.connect(db_path) as con:
        for stmt in [s.strip() for s in SCHEMA_SQL.split(";\n") if s.strip()]:
            con.execute(stmt)
        con.commit()


def _ensure_schema_columns(con: sqlite3.Connection) -> None:
    columns = {row[1] for row in con.execute("PRAGMA table_info(plasmids)").fetchall()}
    if "parse_rules_json" not in columns:
        con.execute("ALTER TABLE plasmids ADD COLUMN parse_rules_json TEXT")
    if "parse_signature" not in columns:
        con.execute("ALTER TABLE plasmids ADD COLUMN parse_signature TEXT")
    if "safezone_version" not in columns:
        con.execute("ALTER TABLE plasmids ADD COLUMN safezone_version INTEGER DEFAULT 1")


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    return sqlite3.connect(Path(db_path))


def _safezone_signature(cfg: SafeZoneConfig, manual_labels: Optional[Dict[str, str]] = None) -> str:
    payload = {
        "safezone_version": 1,
        "buffer_bp": cfg.buffer_bp,
        "protected_labels": sorted(label.value for label in cfg.protected_labels),
        "target_mode": cfg.target_mode,
        "include_disruptable": cfg.include_disruptable,
        "include_neutral": cfg.include_neutral,
        "topology": cfg.topology,
        "manual_labels": sorted((manual_labels or {}).items()),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def safezone_to_feature_dict(result: SafeZoneResult) -> list[dict]:
    rows = []
    for f in result.features:
        rows.append(
            {
                "feature_type": f.feature_type,
                "label": f.label,
                "start": f.start,
                "end": f.end,
                "strand": f.strand,
                "importance": f.importance.value,
                "qualifiers": f.qualifiers,
            }
        )
    return rows


def _to_interval_rows(result: SafeZoneResult, kind: str) -> list[tuple[int, int]]:
    intervals = result.safe_zones if kind == "safe" else result.protected_plus_buffer
    return [(s, e) for s, e in intervals if s < e]


def _json_annotations(record, topology: str, metadata: Optional[dict] = None) -> str:
    payload = {
        "name": record.name,
        "description": record.description,
        "topology": topology,
        "molecule_type": record.annotations.get("molecule_type"),
        "data_file_division": record.annotations.get("data_file_division"),
        "source": metadata,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def upsert_plasmid(
    db_path: str | Path,
    gb_path: str | Path,
    cfg: Optional[SafeZoneConfig] = None,
    manual_labels: Optional[Dict[str, str]] = None,
    metadata: Optional[dict] = None,
) -> tuple[int, SafeZoneResult]:
    cfg = cfg or SafeZoneConfig()
    gb_path = Path(gb_path)
    gb_bytes = gb_path.read_bytes()
    gb_text = _read_text_auto(gb_path)
    record = parse_genbank(gb_path)
    result = build_safe_zones(record, cfg, manual_labels=manual_labels)

    source_sha256 = hashlib.sha256(gb_bytes).hexdigest()
    sequence_sha256 = hashlib.sha256(str(record.seq).encode("utf-8")).hexdigest()
    sequence_md5 = hashlib.md5(str(record.seq).encode("utf-8")).hexdigest()
    parse_signature = _safezone_signature(cfg, manual_labels=manual_labels)
    parse_rules_json = json.dumps(
        {
            "safezone_version": 1,
            "cfg": {
                "buffer_bp": cfg.buffer_bp,
                "target_mode": cfg.target_mode,
                "include_disruptable": cfg.include_disruptable,
                "include_neutral": cfg.include_neutral,
                "topology": cfg.topology,
            },
            "manual_labels": manual_labels or {},
        },
        ensure_ascii=False,
        sort_keys=True,
    )

    db_path = Path(db_path)
    with closing(connect_db(db_path)) as con:
        con.row_factory = sqlite3.Row
        init_db(db_path)
        _ensure_schema_columns(con)

        existing = con.execute(
            "SELECT id FROM plasmids WHERE record_id = ? AND source_sha256 = ? AND ifnull(parse_signature, '') = ? ORDER BY created_at DESC LIMIT 1",
            (record.id, source_sha256, parse_signature),
        ).fetchone()

        if existing is None:
            cur = con.execute(
                """
                INSERT INTO plasmids(
                    record_id, sequence_id, topology, length, md5, sha256,
                    gb_path, source_path, source_sha256, gb_blob, annotations_json,
                    parse_rules_json, parse_signature, safezone_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.name,
                    result.topology,
                    len(record.seq),
                    sequence_md5,
                    source_sha256,
                    str(gb_path),
                    str(gb_path),
                    source_sha256,
                    gb_text,
                    _json_annotations(record, result.topology, metadata=metadata),
                    parse_rules_json,
                    parse_signature,
                    1,
                ),
            )
            plasmid_id = int(cur.lastrowid)

            for feat in safezone_to_feature_dict(result):
                con.execute(
                    """
                    INSERT INTO features(
                        plasmid_id, feature_type, label, start, end, strand, importance, qualifiers_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plasmid_id,
                        feat["feature_type"],
                        feat["label"],
                        feat["start"],
                        feat["end"],
                        feat["strand"],
                        feat["importance"],
                        json.dumps(feat["qualifiers"], ensure_ascii=False),
                    ),
                )

            for kind in ("safe", "masked"):
                for s, e in _to_interval_rows(result, kind):
                    con.execute(
                        "INSERT INTO safe_intervals(plasmid_id, interval_kind, start, end) VALUES (?, ?, ?, ?)",
                        (plasmid_id, kind, s, e),
                    )

            if manual_labels:
                for key, label in manual_labels.items():
                    con.execute(
                        "INSERT OR REPLACE INTO manual_tags(plasmid_id, feature_key, importance, note) VALUES (?, ?, ?, ?)",
                        (plasmid_id, key, str(label), "user-provided"),
                    )

            con.execute(
                "INSERT INTO features (plasmid_id, feature_type, label, start, end, strand, importance, qualifiers_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plasmid_id,
                    "_meta",
                    "SAFEZONE_STATS",
                    0,
                    0,
                    0,
                    "neutral",
                    json.dumps(
                        {
                            "safe_count": len(result.safe_zones),
                            "masked_count": len(result.protected_plus_buffer),
                            "source_sha256": source_sha256,
                            "sequence_sha256": sequence_sha256,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

            con.execute(
                "INSERT INTO _meta(event, ts) VALUES (?, ?)",
                ("ingest", datetime.utcnow().isoformat() + "Z"),
            )
            con.commit()
            return plasmid_id, result

        plasmid_id = int(existing["id"])
        if manual_labels:
            for key, label in manual_labels.items():
                con.execute(
                    "INSERT OR REPLACE INTO manual_tags(plasmid_id, feature_key, importance, note) VALUES (?, ?, ?, ?)",
                    (plasmid_id, key, str(label), "user-provided"),
                )
            con.commit()
        return plasmid_id, result


def last_ingest(db_path: str | Path, record_id: str) -> Optional[dict]:
    with closing(connect_db(db_path)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM plasmids WHERE record_id = ? ORDER BY id DESC LIMIT 1",
            (record_id,),
        ).fetchone()
        return dict(row) if row else None


def export_json_payload(plasmid_id: int, db_path: str | Path) -> str:
    db_path = Path(db_path)
    with closing(connect_db(db_path)) as con:
        con.row_factory = sqlite3.Row
        plasmid = con.execute("SELECT * FROM plasmids WHERE id = ?", (plasmid_id,)).fetchone()
        if plasmid is None:
            raise ValueError(f"plasmid id={plasmid_id} not found")

        features = con.execute(
            "SELECT feature_type, label, start, end, strand, importance, qualifiers_json FROM features WHERE plasmid_id = ? ORDER BY start ASC",
            (plasmid_id,),
        ).fetchall()

        safe_intervals = con.execute(
            "SELECT interval_kind, start, end FROM safe_intervals WHERE plasmid_id = ? ORDER BY interval_kind, start",
            (plasmid_id,),
        ).fetchall()

        tags = con.execute(
            "SELECT feature_key, importance, note, created_at FROM manual_tags WHERE plasmid_id = ?",
            (plasmid_id,),
        ).fetchall()

        payload = {
            "plasmid": dict(plasmid),
            "features": [dict(r) for r in features],
            "intervals": [dict(r) for r in safe_intervals],
            "manual_tags": [dict(r) for r in tags],
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

        return json.dumps(payload, ensure_ascii=False, indent=2)


def touch_heartbeat(db_path: str | Path) -> None:
    init_db(db_path)
    with closing(connect_db(db_path)) as con:
        con.execute(
            "INSERT INTO _meta(event, ts) VALUES (?, ?)",
            ("heartbeat", datetime.utcnow().isoformat() + "Z"),
        )
        con.commit()
