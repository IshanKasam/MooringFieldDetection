"""Tests for web API database helpers and FastAPI routes."""

from __future__ import annotations

from pathlib import Path

import pytest

from mooring_fields.database import (
    field_table_rows,
    get_connection,
    get_stats,
    init_db,
    insert_field,
    insert_scan,
    link_field_to_prospect,
    list_scans,
    upsert_prospect,
)


def _seed(db: Path) -> tuple[int, int]:
    conn = get_connection(db)
    init_db(conn)
    scan_id = insert_scan(conn, source="web-test", weights="mock.pt", split="val")
    f1 = insert_field(
        conn,
        scan_id,
        latitude=42.5,
        longitude=-70.85,
        boat_count=12,
        mean_confidence=0.8,
        location_name="Marblehead Harbor, MA",
        country="United States",
    )
    insert_field(
        conn,
        scan_id,
        latitude=42.51,
        longitude=-70.86,
        boat_count=5,
        mean_confidence=0.7,
        location_name="Near Harbor, MA",
        country="United States",
    )
    pid = upsert_prospect(
        conn,
        {
            "canonical_business_name": "Test Mooring Co",
            "phone": "555-0100",
            "harbor_name": "Marblehead Harbor",
            "needs_review": True,
        },
    )
    link_field_to_prospect(conn, f1, pid)
    conn.close()
    return f1, pid


def test_field_table_rows_joins_prospect(tmp_path: Path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = get_connection(db)
    init_db(conn)
    rows = field_table_rows(conn)
    conn.close()
    assert len(rows) >= 2
    linked = next(r for r in rows if r["controller"] == "Test Mooring Co")
    assert linked["phone"] == "555-0100"
    assert linked["boat_count"] == 12
    assert linked["harbor_name"] == "Marblehead Harbor"


def test_get_stats_and_list_scans(tmp_path: Path):
    db = tmp_path / "t.db"
    _seed(db)
    conn = get_connection(db)
    init_db(conn)
    stats = get_stats(conn)
    scans = list_scans(conn)
    conn.close()
    assert stats["fields"] == 2
    assert stats["prospects"] == 1
    assert stats["needs_review"] == 1
    assert len(scans) == 1
    assert scans[0]["field_count"] == 2


def test_api_health_and_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    db = tmp_path / "t.db"
    _seed(db)

    from mooring_fields import database as dbmod
    import mooring_fields.web.service as svc

    real_get = dbmod.get_connection

    def _get(path=None):
        return real_get(db)

    monkeypatch.setattr(dbmod, "get_connection", _get)
    monkeypatch.setattr(svc, "get_connection", _get)

    from mooring_fields.web.api import app

    client = TestClient(app)
    assert client.get("/api/health").json()["status"] == "ok"
    stats = client.get("/api/stats").json()
    assert stats["fields"] == 2
    table = client.get("/api/table").json()
    assert len(table) >= 2
    assert "state" in table[0]
    assert any(row["state"] == "MA" for row in table)
    geo = client.get("/api/fields.geojson").json()
    assert geo["type"] == "FeatureCollection"
    assert len(geo["features"]) == 2


def test_api_approve_and_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    db = tmp_path / "t.db"
    _, pid = _seed(db)

    from mooring_fields import database as dbmod
    import mooring_fields.web.service as svc

    real_get = dbmod.get_connection

    def _get(path=None):
        return real_get(db)

    monkeypatch.setattr(dbmod, "get_connection", _get)
    monkeypatch.setattr(svc, "get_connection", _get)

    from mooring_fields.web.api import app

    client = TestClient(app)
    r = client.post(f"/api/prospects/{pid}/approve", json={"approved": True})
    assert r.status_code == 200
    detail = client.get(f"/api/prospects/{pid}").json()
    assert detail["approved"] == 1
    assert detail["needs_review"] == 0

    r = client.patch(
        f"/api/prospects/{pid}",
        json={"phone": "555-9999", "canonical_business_name": "Updated Co"},
    )
    assert r.status_code == 200
    assert r.json()["phone"] == "555-9999"
    assert r.json()["canonical_business_name"] == "Updated Co"


def test_fields_geojson_dedupes_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from mooring_fields.web import service as svc
    from mooring_fields import database as dbmod

    db = tmp_path / "t.db"
    f1, _pid = _seed(db)
    conn = get_connection(db)
    init_db(conn)
    pid2 = upsert_prospect(conn, {"canonical_business_name": "Second Co"})
    link_field_to_prospect(conn, f1, pid2)
    conn.close()

    real_get = dbmod.get_connection

    def _get(path=None):
        return real_get(db)

    monkeypatch.setattr(dbmod, "get_connection", _get)
    monkeypatch.setattr(svc, "get_connection", _get)

    geo = svc.fields_geojson()
    assert len(geo["features"]) == 2
