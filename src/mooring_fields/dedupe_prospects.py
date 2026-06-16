"""Deduplicate prospects by name, phone, website, and proximity."""

from __future__ import annotations

import re
import sqlite3
from urllib.parse import urlparse

from mooring_fields.geo_utils import haversine_m


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", " ", s)


def _normalize_phone(phone: str | None) -> str:
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)[-10:]


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url if "://" in url else f"https://{url}").netloc
        return host.lower().removeprefix("www.")
    except Exception:
        return ""


def _prospect_coords(conn: sqlite3.Connection, prospect_id: int) -> list[tuple[float, float]]:
    rows = conn.execute(
        """
        SELECT f.latitude, f.longitude FROM fields f
        JOIN field_prospect_links fpl ON fpl.field_id = f.id
        WHERE fpl.prospect_id = ?
        """,
        (prospect_id,),
    ).fetchall()
    return [(float(r[0]), float(r[1])) for r in rows]


def _min_distance_m(
    coords_a: list[tuple[float, float]], coords_b: list[tuple[float, float]]
) -> float:
    if not coords_a or not coords_b:
        return float("inf")
    return min(
        haversine_m(a[0], a[1], b[0], b[1]) for a in coords_a for b in coords_b
    )


def _should_merge(
    a: sqlite3.Row,
    b: sqlite3.Row,
    coords_a: list[tuple[float, float]],
    coords_b: list[tuple[float, float]],
    proximity_m: float,
) -> bool:
    na, nb = _normalize_name(a["canonical_business_name"]), _normalize_name(
        b["canonical_business_name"]
    )
    if na and nb and (na == nb or na in nb or nb in na):
        return True
    pa, pb = _normalize_phone(a["phone"]), _normalize_phone(b["phone"])
    if pa and pb and pa == pb:
        return True
    da, db = _domain(a["website"]), _domain(b["website"])
    if da and db and da == db:
        return True
    if _min_distance_m(coords_a, coords_b) <= proximity_m:
        if na and nb and (na[:6] in nb or nb[:6] in na):
            return True
    return False


def _merge_into(conn: sqlite3.Connection, keep_id: int, drop_id: int) -> None:
    rows = conn.execute(
        "SELECT field_id FROM field_prospect_links WHERE prospect_id = ?",
        (drop_id,),
    ).fetchall()
    for (field_id,) in rows:
        conn.execute(
            "DELETE FROM field_prospect_links WHERE field_id = ? AND prospect_id = ?",
            (field_id, drop_id),
        )
        conn.execute(
            "INSERT OR IGNORE INTO field_prospect_links (field_id, prospect_id) VALUES (?, ?)",
            (field_id, keep_id),
        )
    conn.execute("DELETE FROM prospects WHERE id = ?", (drop_id,))


def dedupe_prospects(
    conn: sqlite3.Connection,
    *,
    proximity_meters: float = 200,
) -> dict:
    """Merge duplicate prospect rows. Returns summary."""
    prospects = list(
        conn.execute("SELECT * FROM prospects ORDER BY id").fetchall()
    )
    merged = 0
    removed_ids: set[int] = set()

    for i, a in enumerate(prospects):
        if int(a["id"]) in removed_ids:
            continue
        coords_a = _prospect_coords(conn, int(a["id"]))
        for b in prospects[i + 1 :]:
            bid = int(b["id"])
            if bid in removed_ids:
                continue
            coords_b = _prospect_coords(conn, bid)
            if _should_merge(a, b, coords_a, coords_b, proximity_meters):
                _merge_into(conn, int(a["id"]), bid)
                removed_ids.add(bid)
                merged += 1

    conn.commit()
    remaining = int(conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0])
    return {"merged": merged, "prospects_remaining": remaining}
