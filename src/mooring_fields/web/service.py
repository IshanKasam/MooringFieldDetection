"""Per-request DB access wrapping mooring_fields.database helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mooring_fields.database import (
    approve_prospect,
    diff_scans,
    field_table_rows,
    get_boats,
    get_connection,
    get_prospect,
    get_prospect_field_ids,
    get_stats,
    init_db,
    list_enrichment_runs,
    list_scans,
    prospects_export_rows,
    upsert_prospect,
)
from mooring_fields.paths import DB_PATH, PROSPECTS_EXPORT


def _conn(db_path: Path | None = None):
    conn = get_connection(db_path)
    init_db(conn)
    return conn


def stats(*, db_path: Path | None = None) -> dict[str, int]:
    conn = _conn(db_path)
    try:
        return get_stats(conn)
    finally:
        conn.close()


def table_rows(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = _conn(db_path)
    try:
        return field_table_rows(conn)
    finally:
        conn.close()


def fields_geojson(*, db_path: Path | None = None) -> dict[str, Any]:
    """One GeoJSON Feature per field_id (first linked prospect wins)."""
    rows = table_rows(db_path=db_path)
    seen: set[int] = set()
    features: list[dict[str, Any]] = []
    for row in rows:
        fid = int(row["field_id"])
        if fid in seen:
            continue
        seen.add(fid)
        props = {k: v for k, v in row.items() if k not in ("latitude", "longitude")}
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row["longitude"]), float(row["latitude"])],
                },
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def boats(
    *,
    field_id: int | None = None,
    scan_id: int | None = None,
    limit: int = 5000,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    conn = _conn(db_path)
    try:
        return get_boats(conn, field_id=field_id, scan_id=scan_id, limit=limit)
    finally:
        conn.close()


def prospects(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = _conn(db_path)
    try:
        return prospects_export_rows(conn)
    finally:
        conn.close()


def prospect_detail(prospect_id: int, *, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = _conn(db_path)
    try:
        row = get_prospect(conn, prospect_id)
        if row is None:
            return None
        sources = row.get("sources")
        if isinstance(sources, str):
            try:
                sources = json.loads(sources)
            except json.JSONDecodeError:
                pass
        supply = row.get("supply_chain_json")
        if isinstance(supply, str) and supply:
            try:
                supply = json.loads(supply)
            except json.JSONDecodeError:
                pass
        return {
            "prospect_id": int(row["id"]),
            "canonical_business_name": row.get("canonical_business_name"),
            "phone": row.get("phone"),
            "email": row.get("email"),
            "website": row.get("website"),
            "address": row.get("address"),
            "operator_type": row.get("operator_type"),
            "harbor_name": row.get("harbor_name"),
            "research_summary": row.get("research_summary"),
            "supply_chain_summary": row.get("supply_chain_summary"),
            "supply_chain_json": supply,
            "confidence": row.get("confidence"),
            "sources": sources,
            "needs_review": row.get("needs_review"),
            "approved": row.get("approved"),
            "last_enriched": row.get("last_enriched"),
            "field_ids": get_prospect_field_ids(conn, prospect_id),
        }
    finally:
        conn.close()


def update_prospect(
    prospect_id: int,
    data: dict[str, Any],
    *,
    db_path: Path | None = None,
) -> dict[str, Any] | None:
    conn = _conn(db_path)
    try:
        if get_prospect(conn, prospect_id) is None:
            return None
        payload = {k: v for k, v in data.items() if v is not None}
        if "needs_review" in payload:
            payload["needs_review"] = bool(payload["needs_review"])
        if "approved" in payload:
            payload["approved"] = bool(payload["approved"])
        upsert_prospect(conn, payload, prospect_id=prospect_id)
    finally:
        conn.close()
    return prospect_detail(prospect_id, db_path=db_path)


def set_approved(
    prospect_id: int,
    approved: bool,
    *,
    db_path: Path | None = None,
) -> bool:
    conn = _conn(db_path)
    try:
        if get_prospect(conn, prospect_id) is None:
            return False
        approve_prospect(conn, prospect_id, approved=approved)
        return True
    finally:
        conn.close()


def scans(*, db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = _conn(db_path)
    try:
        return list_scans(conn)
    finally:
        conn.close()


def scan_diff(scan_a: int, scan_b: int, *, db_path: Path | None = None) -> dict[str, Any]:
    conn = _conn(db_path)
    try:
        return diff_scans(conn, scan_a, scan_b)
    finally:
        conn.close()


def enrichment_runs(*, limit: int = 20, db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = _conn(db_path)
    try:
        return list_enrichment_runs(conn, limit=limit)
    finally:
        conn.close()


def build_export(
    *,
    db_path: Path | None = None,
    output: Path | None = None,
) -> Path:
    from mooring_fields.export_excel import export_prospects

    out = output or PROSPECTS_EXPORT
    export_prospects(out, db_path=db_path)
    return Path(out)


def db_path_default() -> Path:
    return DB_PATH
