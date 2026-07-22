"""Job queue + maps quota helpers for in-app long-running work."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for key in ("params_json", "progress_json", "result_json"):
        raw = d.get(key)
        short = key.replace("_json", "")
        if isinstance(raw, str) and raw:
            try:
                d[short] = json.loads(raw)
            except json.JSONDecodeError:
                d[short] = raw
        else:
            d[short] = None
    d["cancel_requested"] = bool(d.get("cancel_requested"))
    return d


def create_job(
    conn: sqlite3.Connection, kind: str, params: dict[str, Any] | None = None
) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (kind, status, params_json, created_at) VALUES (?, ?, ?, ?)",
        (kind, "queued", json.dumps(params or {}), _now()),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    return _job_row(
        conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    )


def list_jobs(
    conn: sqlite3.Connection, *, kind: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    if kind:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE kind = ? ORDER BY id DESC LIMIT ?",
            (kind, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [r for r in (_job_row(row) for row in rows) if r]


def active_long_job(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM jobs WHERE status IN ('queued','running','cancelling') "
        "AND kind IN ('scan','fetch','detect','import','enrich') "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _job_row(row)


def mark_job_running(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute(
        "UPDATE jobs SET status=?, started_at=? WHERE id=?",
        ("running", _now(), job_id),
    )
    conn.commit()


def update_job_progress(
    conn: sqlite3.Connection, job_id: int, progress: dict[str, Any]
) -> None:
    conn.execute(
        "UPDATE jobs SET progress_json=? WHERE id=?",
        (json.dumps(progress), job_id),
    )
    conn.commit()


def request_job_cancel(conn: sqlite3.Connection, job_id: int) -> bool:
    row = get_job(conn, job_id)
    if row is None:
        return False
    if row["status"] not in ("queued", "running"):
        return False
    conn.execute(
        "UPDATE jobs SET cancel_requested=1, status=? WHERE id=?",
        ("cancelling", job_id),
    )
    conn.commit()
    return True


def finish_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: str,
    result: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "UPDATE jobs SET status=?, result_json=?, finished_at=?, cancel_requested=? WHERE id=?",
        (status, json.dumps(result or {}), _now(), 0, job_id),
    )
    conn.commit()


def job_cancel_requested(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute(
        "SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return bool(row and row[0])


def maps_quota_cap() -> int:
    try:
        import yaml
        from mooring_fields.paths import ROOT

        cfg = (
            yaml.safe_load((ROOT / "config" / "imagery.yaml").read_text(encoding="utf-8"))
            or {}
        )
        return int(cfg.get("max_api_requests_per_run") or 800)
    except Exception:
        return 800


def get_maps_quota(conn: sqlite3.Connection) -> dict[str, Any]:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT maps_used FROM maps_quota_daily WHERE day = ?", (day,)
    ).fetchone()
    used = int(row[0]) if row else 0
    cap = maps_quota_cap()
    return {
        "day": day,
        "maps_used": used,
        "cap": cap,
        "remaining": max(0, cap - used),
    }


def add_maps_quota_usage(conn: sqlite3.Connection, n: int) -> dict[str, Any]:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO maps_quota_daily (day, maps_used) VALUES (?, ?) "
        "ON CONFLICT(day) DO UPDATE SET maps_used = maps_used + excluded.maps_used",
        (day, max(0, int(n))),
    )
    conn.commit()
    return get_maps_quota(conn)
