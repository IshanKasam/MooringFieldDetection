"""SQLite persistence for mooring field detections (scans, fields, boats)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from mooring_fields.paths import DB_PATH

if TYPE_CHECKING:
    from mooring_fields.cluster_fields import MooringFieldCluster

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
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         INTEGER NOT NULL REFERENCES scans(id),
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    boat_count      INTEGER NOT NULL,
    mean_confidence REAL,
    location_name   TEXT,
    country         TEXT,
    created_at      TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_fields_scan ON fields(scan_id);
CREATE INDEX IF NOT EXISTS idx_boats_scan ON boats(scan_id);
CREATE INDEX IF NOT EXISTS idx_boats_field ON boats(field_id);
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


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
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
) -> int:
    cur = conn.execute(
        "INSERT INTO fields "
        "(scan_id, latitude, longitude, boat_count, mean_confidence, location_name, country, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (scan_id, latitude, longitude, boat_count, mean_confidence, location_name, country, _now()),
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
    """Persist one detection run: a scan row, its fields, and member boats.

    *geocoder* is an optional callable ``(lat, lon) -> {"location_name", "country"}``.
    Returns a summary dict including the scan id and counts.
    """
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
