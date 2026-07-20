"""SQLite persistence for mooring field detections and enrichment prospects."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mooring_fields.paths import DB_PATH

if TYPE_CHECKING:
    from mooring_fields.cluster_fields import MooringFieldCluster

ENRICHMENT_STATUSES = frozenset(
    {"pending", "places_done", "researched", "exported", "skipped"}
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    source      TEXT,
    weights     TEXT,
    split       TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS fields (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id             INTEGER NOT NULL REFERENCES scans(id),
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    boat_count          INTEGER NOT NULL,
    mean_confidence     REAL,
    location_name       TEXT,
    country             TEXT,
    enrichment_status   TEXT NOT NULL DEFAULT 'pending',
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS boats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id     INTEGER NOT NULL REFERENCES scans(id),
    field_id    INTEGER REFERENCES fields(id),
    latitude    REAL NOT NULL,
    longitude   REAL NOT NULL,
    confidence  REAL,
    image_stem  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prospects (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_business_name TEXT,
    phone                   TEXT,
    email                   TEXT,
    website                 TEXT,
    address                 TEXT,
    operator_type           TEXT,
    place_id                TEXT,
    research_summary        TEXT,
    confidence              REAL,
    sources                 TEXT,
    needs_review            INTEGER NOT NULL DEFAULT 1,
    approved                INTEGER NOT NULL DEFAULT 0,
    raw_places_response     TEXT,
    raw_gemini_response     TEXT,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    last_enriched           TEXT
);

CREATE TABLE IF NOT EXISTS field_prospect_links (
    field_id    INTEGER NOT NULL REFERENCES fields(id),
    prospect_id INTEGER NOT NULL REFERENCES prospects(id),
    PRIMARY KEY (field_id, prospect_id)
);

CREATE TABLE IF NOT EXISTS enrichment_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    provider         TEXT,
    fields_processed INTEGER NOT NULL DEFAULT 0,
    places_calls     INTEGER NOT NULL DEFAULT 0,
    gemini_calls     INTEGER NOT NULL DEFAULT 0,
    cap_hit          INTEGER NOT NULL DEFAULT 0,
    notes            TEXT
);

CREATE INDEX IF NOT EXISTS idx_fields_scan ON fields(scan_id);
CREATE INDEX IF NOT EXISTS idx_boats_scan ON boats(scan_id);
CREATE INDEX IF NOT EXISTS idx_boats_field ON boats(field_id);
CREATE INDEX IF NOT EXISTS idx_prospects_place ON prospects(place_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Open (and create if needed) the SQLite database."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_fields_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(fields)").fetchall()}
    if "enrichment_status" not in cols:
        conn.execute(
            "ALTER TABLE fields ADD COLUMN enrichment_status TEXT NOT NULL DEFAULT 'pending'"
        )
        conn.commit()
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fields_enrichment ON fields(enrichment_status)"
    )


def _migrate_prospects_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(prospects)").fetchall()}
    migrations = {
        "harbor_name": "TEXT",
        "supply_chain_json": "TEXT",
        "supply_chain_summary": "TEXT",
    }
    for col, typedef in migrations.items():
        if col not in cols:
            try:
                conn.execute(f"ALTER TABLE prospects ADD COLUMN {col} {typedef}")
            except sqlite3.OperationalError as exc:
                # Web requests can initialize the same local DB concurrently.
                # Another request may add the column after our PRAGMA check.
                if "duplicate column name" not in str(exc).lower():
                    raise
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_fields_columns(conn)
    _migrate_prospects_columns(conn)
    conn.commit()


def insert_scan(
    conn: sqlite3.Connection,
    source: str | None = None,
    weights: str | None = None,
    split: str | None = None,
    notes: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO scans (created_at, source, weights, split, notes) VALUES (?, ?, ?, ?, ?)",
        (_now(), source, weights, split, notes),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_field(
    conn: sqlite3.Connection,
    scan_id: int,
    latitude: float,
    longitude: float,
    boat_count: int,
    mean_confidence: float | None,
    location_name: str | None = None,
    country: str | None = None,
    enrichment_status: str = "pending",
) -> int:
    cur = conn.execute(
        "INSERT INTO fields "
        "(scan_id, latitude, longitude, boat_count, mean_confidence, location_name, country, "
        "enrichment_status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            scan_id,
            latitude,
            longitude,
            boat_count,
            mean_confidence,
            location_name,
            country,
            enrichment_status,
            _now(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_boats(
    conn: sqlite3.Connection,
    scan_id: int,
    field_id: int | None,
    boats: list,
) -> None:
    rows = [
        (scan_id, field_id, b.lat, b.lon, b.confidence, b.image_stem, _now())
        for b in boats
    ]
    if rows:
        conn.executemany(
            "INSERT INTO boats (scan_id, field_id, latitude, longitude, confidence, image_stem, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()


def save_scan(
    clusters: "list[MooringFieldCluster]",
    source: str | None = None,
    weights: str | None = None,
    split: str | None = None,
    notes: str | None = None,
    geocoder=None,
    db_path: Path | None = None,
) -> dict:
    """Persist one detection run: a scan row, its fields, and member boats."""
    conn = get_connection(db_path)
    try:
        init_db(conn)
        scan_id = insert_scan(conn, source=source, weights=weights, split=split, notes=notes)

        total_boats = 0
        for cluster in clusters:
            name = None
            country = None
            if geocoder is not None:
                try:
                    info = geocoder(cluster.lat, cluster.lon)
                    name = info.get("location_name")
                    country = info.get("country")
                except Exception:
                    pass
            field_id = insert_field(
                conn,
                scan_id=scan_id,
                latitude=cluster.lat,
                longitude=cluster.lon,
                boat_count=cluster.boat_count,
                mean_confidence=cluster.mean_confidence,
                location_name=name,
                country=country,
            )
            member_boats = getattr(cluster, "boats", []) or []
            insert_boats(conn, scan_id, field_id, member_boats)
            total_boats += len(member_boats)

        return {
            "db_path": str(db_path or DB_PATH),
            "scan_id": scan_id,
            "fields_saved": len(clusters),
            "boats_saved": total_boats,
        }
    finally:
        conn.close()


def list_fields(
    conn: sqlite3.Connection,
    *,
    scan_id: int | None = None,
    enrichment_status: str | None = None,
    only_new: bool = False,
) -> list[sqlite3.Row]:
    """Return field rows joined with scan metadata."""
    sql = (
        "SELECT f.*, s.weights AS detection_weights, s.created_at AS detection_date, s.source "
        "FROM fields f JOIN scans s ON f.scan_id = s.id WHERE 1=1"
    )
    params: list[Any] = []
    if scan_id is not None:
        sql += " AND f.scan_id = ?"
        params.append(scan_id)
    if enrichment_status is not None:
        sql += " AND f.enrichment_status = ?"
        params.append(enrichment_status)
    if only_new:
        sql += (
            " AND f.id NOT IN (SELECT field_id FROM field_prospect_links) "
            "AND f.enrichment_status IN ('pending', 'places_done')"
        )
    sql += " ORDER BY f.id"
    return list(conn.execute(sql, params).fetchall())


def get_unenriched_fields(
    conn: sqlite3.Connection,
    *,
    only_new: bool = False,
    include_skipped: bool = False,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Fields needing Places enrichment."""
    if include_skipped:
        status_clause = "f.enrichment_status IN ('pending', 'skipped')"
    else:
        status_clause = "f.enrichment_status = 'pending'"
    sql = (
        "SELECT f.*, s.weights AS detection_weights, s.created_at AS detection_date "
        "FROM fields f JOIN scans s ON f.scan_id = s.id "
        f"WHERE {status_clause}"
    )
    if only_new:
        sql += " AND f.id NOT IN (SELECT field_id FROM field_prospect_links)"
    sql += " ORDER BY f.id"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return list(conn.execute(sql).fetchall())


def get_fields_for_research(
    conn: sqlite3.Connection,
    *,
    only_new: bool = False,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Fields with Places data ready for Gemini research."""
    sql = (
        "SELECT f.*, s.weights AS detection_weights, s.created_at AS detection_date, "
        "p.id AS prospect_id, p.canonical_business_name AS place_name, p.address AS place_address, "
        "p.phone AS place_phone, p.website AS place_website, p.operator_type AS place_types, "
        "p.raw_places_response "
        "FROM fields f "
        "JOIN scans s ON f.scan_id = s.id "
        "JOIN field_prospect_links fpl ON fpl.field_id = f.id "
        "JOIN prospects p ON p.id = fpl.prospect_id "
        "WHERE f.enrichment_status = 'places_done'"
    )
    if only_new:
        sql += " AND (p.research_summary IS NULL OR p.research_summary = '')"
    sql += " ORDER BY f.id"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return list(conn.execute(sql).fetchall())


def set_field_enrichment_status(
    conn: sqlite3.Connection, field_id: int, status: str
) -> None:
    if status not in ENRICHMENT_STATUSES:
        raise ValueError(f"Invalid enrichment_status: {status}")
    conn.execute(
        "UPDATE fields SET enrichment_status = ? WHERE id = ?",
        (status, field_id),
    )
    conn.commit()


def upsert_prospect(
    conn: sqlite3.Connection,
    data: dict[str, Any],
    prospect_id: int | None = None,
) -> int:
    """Insert or update a prospect row. Returns prospect id."""
    now = _now()
    sources = data.get("sources")
    if isinstance(sources, list):
        sources = json.dumps(sources)
    fields = {
        "canonical_business_name": data.get("canonical_business_name"),
        "phone": data.get("phone"),
        "email": data.get("email"),
        "website": data.get("website"),
        "address": data.get("address"),
        "operator_type": data.get("operator_type"),
        "place_id": data.get("place_id"),
        "research_summary": data.get("research_summary"),
        "confidence": data.get("confidence"),
        "sources": sources,
        "needs_review": 1 if data.get("needs_review", True) else 0,
        "approved": 1 if data.get("approved", False) else 0,
        "raw_places_response": data.get("raw_places_response"),
        "raw_gemini_response": data.get("raw_gemini_response"),
        "harbor_name": data.get("harbor_name"),
        "supply_chain_json": (
            json.dumps(data["supply_chain_json"])
            if isinstance(data.get("supply_chain_json"), (dict, list))
            else data.get("supply_chain_json")
        ),
        "supply_chain_summary": data.get("supply_chain_summary"),
        "last_enriched": data.get("last_enriched") or now,
    }
    if prospect_id is None:
        cur = conn.execute(
            "INSERT INTO prospects "
            "(canonical_business_name, phone, email, website, address, operator_type, place_id, "
            "research_summary, confidence, sources, needs_review, approved, "
            "raw_places_response, raw_gemini_response, harbor_name, supply_chain_json, "
            "supply_chain_summary, created_at, updated_at, last_enriched) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fields["canonical_business_name"],
                fields["phone"],
                fields["email"],
                fields["website"],
                fields["address"],
                fields["operator_type"],
                fields["place_id"],
                fields["research_summary"],
                fields["confidence"],
                fields["sources"],
                fields["needs_review"],
                fields["approved"],
                fields["raw_places_response"],
                fields["raw_gemini_response"],
                fields["harbor_name"],
                fields["supply_chain_json"],
                fields["supply_chain_summary"],
                now,
                now,
                fields["last_enriched"],
            ),
        )
        conn.commit()
        return int(cur.lastrowid)

    conn.execute(
        "UPDATE prospects SET "
        "canonical_business_name=?, phone=?, email=?, website=?, address=?, operator_type=?, "
        "place_id=?, research_summary=?, confidence=?, sources=?, needs_review=?, approved=?, "
        "raw_places_response=?, raw_gemini_response=?, harbor_name=?, supply_chain_json=?, "
        "supply_chain_summary=?, updated_at=?, last_enriched=? "
        "WHERE id=?",
        (
            fields["canonical_business_name"],
            fields["phone"],
            fields["email"],
            fields["website"],
            fields["address"],
            fields["operator_type"],
            fields["place_id"],
            fields["research_summary"],
            fields["confidence"],
            fields["sources"],
            fields["needs_review"],
            fields["approved"],
            fields["raw_places_response"],
            fields["raw_gemini_response"],
            fields["harbor_name"],
            fields["supply_chain_json"],
            fields["supply_chain_summary"],
            now,
            fields["last_enriched"],
            prospect_id,
        ),
    )
    conn.commit()
    return prospect_id


def link_field_to_prospect(
    conn: sqlite3.Connection, field_id: int, prospect_id: int
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO field_prospect_links (field_id, prospect_id) VALUES (?, ?)",
        (field_id, prospect_id),
    )
    conn.commit()


def list_prospects(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM prospects ORDER BY id").fetchall())


def field_table_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """One row per field, joined to linked prospect (controller + contact)."""
    rows = conn.execute(
        """
        SELECT f.id AS field_id, f.latitude, f.longitude, f.boat_count,
               f.mean_confidence, f.location_name, f.country, f.enrichment_status,
               f.scan_id, s.created_at AS detection_date,
               p.id AS prospect_id, p.canonical_business_name AS controller,
               p.phone, p.email, p.website, p.address, p.harbor_name, p.operator_type,
               p.confidence, p.sources, p.research_summary, p.supply_chain_summary,
               p.needs_review, p.approved
        FROM fields f
        JOIN scans s ON f.scan_id = s.id
        LEFT JOIN field_prospect_links fpl ON fpl.field_id = f.id
        LEFT JOIN prospects p ON p.id = fpl.prospect_id
        ORDER BY f.id, p.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_stats(conn: sqlite3.Connection) -> dict[str, int]:
    """Aggregate counts for the web dashboard header."""
    fields = int(conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0])
    boats = int(conn.execute("SELECT COUNT(*) FROM boats").fetchone()[0])
    prospects = int(conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0])
    needs_review = int(
        conn.execute(
            "SELECT COUNT(*) FROM prospects WHERE needs_review = 1"
        ).fetchone()[0]
    )
    approved = int(
        conn.execute("SELECT COUNT(*) FROM prospects WHERE approved = 1").fetchone()[0]
    )
    return {
        "fields": fields,
        "boats": boats,
        "prospects": prospects,
        "needs_review": needs_review,
        "approved": approved,
    }


def list_scans(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.id, s.created_at, s.source, s.weights, s.split, s.notes,
               COUNT(f.id) AS field_count
        FROM scans s
        LEFT JOIN fields f ON f.scan_id = s.id
        GROUP BY s.id
        ORDER BY s.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_boats(
    conn: sqlite3.Connection,
    *,
    field_id: int | None = None,
    scan_id: int | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    sql = (
        "SELECT id, scan_id, field_id, latitude, longitude, confidence, image_stem "
        "FROM boats WHERE 1=1"
    )
    params: list[Any] = []
    if field_id is not None:
        sql += " AND field_id = ?"
        params.append(field_id)
    if scan_id is not None:
        sql += " AND scan_id = ?"
        params.append(scan_id)
    sql += f" ORDER BY id LIMIT {int(limit)}"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_prospect(conn: sqlite3.Connection, prospect_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM prospects WHERE id = ?", (prospect_id,)
    ).fetchone()
    return dict(row) if row else None


def list_enrichment_runs(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM enrichment_runs ORDER BY id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def get_prospect_field_ids(conn: sqlite3.Connection, prospect_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT field_id FROM field_prospect_links WHERE prospect_id = ? ORDER BY field_id",
        (prospect_id,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def start_enrichment_run(conn: sqlite3.Connection, provider: str) -> int:
    cur = conn.execute(
        "INSERT INTO enrichment_runs (started_at, provider, fields_processed, places_calls, gemini_calls) "
        "VALUES (?, ?, 0, 0, 0)",
        (_now(), provider),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_enrichment_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    fields_processed: int,
    places_calls: int,
    gemini_calls: int,
    cap_hit: bool = False,
    notes: str | None = None,
) -> None:
    conn.execute(
        "UPDATE enrichment_runs SET finished_at=?, fields_processed=?, places_calls=?, "
        "gemini_calls=?, cap_hit=?, notes=? WHERE id=?",
        (_now(), fields_processed, places_calls, gemini_calls, int(cap_hit), notes, run_id),
    )
    conn.commit()


def approve_prospect(conn: sqlite3.Connection, prospect_id: int, approved: bool = True) -> None:
    conn.execute(
        "UPDATE prospects SET approved = ?, needs_review = ? WHERE id = ?",
        (int(approved), 0 if approved else 1, prospect_id),
    )
    conn.commit()


def fields_export_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Rows for Fields Excel sheet."""
    rows = conn.execute(
        """
        SELECT f.id AS field_id, f.scan_id, f.latitude, f.longitude, f.boat_count,
               f.mean_confidence, f.location_name, f.country, f.enrichment_status,
               s.weights AS detection_weights, s.created_at AS detection_date,
               p.id AS prospect_id, p.canonical_business_name AS enriched_place_name,
               p.needs_review
        FROM fields f
        JOIN scans s ON f.scan_id = s.id
        LEFT JOIN field_prospect_links fpl ON fpl.field_id = f.id
        LEFT JOIN prospects p ON p.id = fpl.prospect_id
        ORDER BY f.id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def update_prospect_supply_chain(
    conn: sqlite3.Connection,
    prospect_id: int,
    supply_chain: dict[str, Any],
    summary: str,
) -> None:
    conn.execute(
        "UPDATE prospects SET supply_chain_json=?, supply_chain_summary=?, updated_at=?, last_enriched=? "
        "WHERE id=?",
        (json.dumps(supply_chain), summary, _now(), _now(), prospect_id),
    )
    conn.commit()


def get_prospects_for_supply_chain(
    conn: sqlite3.Connection,
    *,
    only_new: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Prospects needing supply-chain research."""
    sql = (
        "SELECT p.*, GROUP_CONCAT(fpl.field_id) AS field_ids "
        "FROM prospects p "
        "LEFT JOIN field_prospect_links fpl ON fpl.prospect_id = p.id "
        "WHERE p.canonical_business_name IS NOT NULL "
        "AND p.operator_type NOT IN ('mooring_field') "
    )
    if only_new:
        sql += "AND (p.supply_chain_json IS NULL OR p.supply_chain_json = '') "
    sql += "GROUP BY p.id ORDER BY p.harbor_name, p.id"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [dict(r) for r in conn.execute(sql).fetchall()]


def supply_chain_export_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Flatten supply chain JSON stored on prospects for export."""
    from mooring_fields.gemini_supply_chain import (
        SupplyChainCompanyResult,
        SupplyChainSupplierRow,
        flatten_supply_chain_rows,
    )

    rows: list[dict[str, Any]] = []
    for p in list_prospects(conn):
        raw = p["supply_chain_json"]
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        field_ids = get_prospect_field_ids(conn, int(p["id"]))
        if isinstance(data, dict) and data.get("known_suppliers") is not None:
            suppliers = [
                SupplyChainSupplierRow(
                    supplier_or_manufacturer=str(s.get("supplier_or_manufacturer") or ""),
                    component_types=str(s.get("component_types") or ""),
                    evidence=str(s.get("evidence") or ""),
                    confidence_level=str(s.get("confidence_level") or "Low"),
                    confirmation_status=str(s.get("confirmation_status") or "inferred"),
                    notable_brands=str(s.get("notable_brands") or ""),
                )
                for s in (data.get("known_suppliers") or [])
                if isinstance(s, dict)
            ]
            result = SupplyChainCompanyResult(
                mooring_company=str(
                    data.get("mooring_company") or p["canonical_business_name"]
                ),
                harbor_name=data.get("harbor_name") or p["harbor_name"],
                prospect_id=int(p["id"]),
                field_ids=field_ids,
                known_suppliers=suppliers,
                company_summary=str(data.get("company_summary") or ""),
                overall_confidence=str(data.get("overall_confidence") or "Low"),
            )
            rows.extend(flatten_supply_chain_rows([result]))
        elif isinstance(data, dict) and data.get("companies"):
            parsed = []
            for co in data["companies"]:
                if not isinstance(co, dict):
                    continue
                suppliers = [
                    SupplyChainSupplierRow(
                        supplier_or_manufacturer=str(s.get("supplier_or_manufacturer") or ""),
                        component_types=str(s.get("component_types") or ""),
                        evidence=str(s.get("evidence") or ""),
                        confidence_level=str(s.get("confidence_level") or "Low"),
                        confirmation_status=str(s.get("confirmation_status") or "inferred"),
                        notable_brands=str(s.get("notable_brands") or ""),
                    )
                    for s in (co.get("known_suppliers") or [])
                    if isinstance(s, dict)
                ]
                parsed.append(
                    SupplyChainCompanyResult(
                        mooring_company=str(co.get("mooring_company") or ""),
                        harbor_name=co.get("harbor_name"),
                        prospect_id=co.get("prospect_id") or int(p["id"]),
                        field_ids=field_ids,
                        known_suppliers=suppliers,
                        company_summary=str(co.get("company_summary") or ""),
                        overall_confidence=str(co.get("overall_confidence") or "Low"),
                    )
                )
            rows.extend(flatten_supply_chain_rows(parsed))
    return rows


def prospects_export_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Rows for Prospects Excel sheet."""
    prospects = list_prospects(conn)
    out = []
    for p in prospects:
        pid = int(p["id"])
        field_ids = get_prospect_field_ids(conn, pid)
        out.append(
            {
                "prospect_id": pid,
                "canonical_business_name": p["canonical_business_name"],
                "phone": p["phone"],
                "email": p["email"],
                "website": p["website"],
                "address": p["address"],
                "operator_type": p["operator_type"],
                "harbor_name": p["harbor_name"],
                "research_summary": p["research_summary"],
                "supply_chain_summary": p["supply_chain_summary"],
                "confidence": p["confidence"],
                "sources": p["sources"],
                "field_ids": ",".join(str(i) for i in field_ids),
                "field_count": len(field_ids),
                "needs_review": p["needs_review"],
                "approved": p["approved"],
                "last_enriched": p["last_enriched"],
            }
        )
    return out


def diff_scans(conn: sqlite3.Connection, scan_id_a: int, scan_id_b: int) -> dict[str, Any]:
    """Compare field counts between two detection scans."""
    def count(sid: int) -> int:
        return int(
            conn.execute("SELECT COUNT(*) FROM fields WHERE scan_id = ?", (sid,)).fetchone()[0]
        )

    return {
        "scan_a": scan_id_a,
        "scan_b": scan_id_b,
        "fields_a": count(scan_id_a),
        "fields_b": count(scan_id_b),
        "delta": count(scan_id_b) - count(scan_id_a),
    }
