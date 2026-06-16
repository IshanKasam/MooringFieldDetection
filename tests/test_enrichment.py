"""Tests for enrichment pipeline (mock providers)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mooring_fields.database import (
    get_connection,
    init_db,
    insert_field,
    insert_scan,
    list_prospects,
)
from mooring_fields.dedupe_prospects import dedupe_prospects
from mooring_fields.enrichment import enrich_all, import_prospects_csv, query_fields
from mooring_fields.enrichment_config import estimate_enrichment
from mooring_fields.export_excel import export_prospects
from mooring_fields.gemini_research import build_prompt, parse_gemini_json, validate_research


def _seed_db(db_path: Path) -> int:
    conn = get_connection(db_path)
    init_db(conn)
    scan_id = insert_scan(conn, source="test", weights="mock.pt", split="val")
    insert_field(
        conn,
        scan_id,
        latitude=41.5,
        longitude=-70.9,
        boat_count=12,
        mean_confidence=0.8,
        location_name="Test Harbor, MA",
        country="United States",
    )
    insert_field(
        conn,
        scan_id,
        latitude=41.51,
        longitude=-70.91,
        boat_count=8,
        mean_confidence=0.7,
        location_name="Near Harbor, MA",
        country="United States",
    )
    conn.close()
    return scan_id


def test_estimate_enrichment(tmp_path: Path):
    db = tmp_path / "test.db"
    _seed_db(db)
    est = estimate_enrichment(db_path=db)
    assert est["pending_fields"] == 2
    assert est["estimated_places_calls"] == 4


def test_mock_enrich_all_pipeline(tmp_path: Path, monkeypatch):
    db = tmp_path / "test.db"
    _seed_db(db)
    out = tmp_path / "export.xlsx"

    monkeypatch.setenv("MOORING_ENRICHMENT_CONFIG", str(tmp_path / "enrichment.yaml"))
    cfg_src = Path(__file__).resolve().parents[1] / "config" / "enrichment.yaml"
    (tmp_path / "enrichment.yaml").write_text(cfg_src.read_text(encoding="utf-8"))

    # Patch config loader path via monkeypatch on load_enrichment_config
    import mooring_fields.enrichment_config as ec

    def _load():
        import yaml

        cfg = yaml.safe_load((tmp_path / "enrichment.yaml").read_text(encoding="utf-8"))
        cfg["provider"] = "mock"
        return cfg

    monkeypatch.setattr(ec, "load_enrichment_config", _load)
    import mooring_fields.enrichment as enr

    monkeypatch.setattr(enr, "load_enrichment_config", _load)

    report = enrich_all(db_path=db, limit=2, export_path=out)
    assert report["dedupe"]["prospects_remaining"] >= 1
    assert out.exists()

    conn = get_connection(db)
    prospects = list_prospects(conn)
    conn.close()
    assert len(prospects) >= 1


def test_query_fields(tmp_path: Path):
    db = tmp_path / "test.db"
    _seed_db(db)
    rows = query_fields(db_path=db)
    assert len(rows) == 2


def test_supply_chain_mock_batch():
    from mooring_fields.gemini_supply_chain import (
        MockSupplyChainProvider,
        flatten_supply_chain_rows,
    )

    batch = [
        {
            "prospect_id": 1,
            "canonical_business_name": "Willard and Sons Inc.",
            "harbor_name": "Marblehead Harbor",
            "field_ids": "50",
        }
    ]
    provider = MockSupplyChainProvider({})
    results = provider.research_batch(batch)
    assert results[0].mooring_company == "Willard and Sons Inc."
    rows = flatten_supply_chain_rows(results)
    assert rows[0]["supplier_or_manufacturer"] == "Acco/Peerless"


def test_free_tier_model_guard():
    from mooring_fields.gemini_client import resolve_gemini_config

    cfg = resolve_gemini_config(
        {"gemini": {"model": "gemini-2.5-pro", "free_tier_only": True}}
    )
    assert cfg["model"] == "gemini-2.0-flash-lite"
    assert "pro" not in cfg["model"]


def test_export_prospects_xlsx(tmp_path: Path):
    db = tmp_path / "test.db"
    _seed_db(db)
    from mooring_fields.enrichment import enrich_places, enrich_research, enrich_supply_chain, run_dedupe

    enrich_places(db_path=db, limit=2)
    enrich_research(db_path=db, limit=2)
    enrich_supply_chain(db_path=db, limit=2)
    run_dedupe(db_path=db)
    xlsx = tmp_path / "out.xlsx"
    result = export_prospects(xlsx, db_path=db)
    assert Path(result["xlsx"]).exists()
    assert "supply_chain_csv" in result


def test_validate_research_v2_harbor_companies():
    data = {
        "harbor_name": "Salem Harbor",
        "harbormaster": {
            "name": "Salem Harbormaster",
            "phone": "978-555-0100",
            "notes": "Assigns mooring permits",
        },
        "mooring_service_companies": [
            {
                "name": "Northeast Mooring & Salvage",
                "phone": "781-631-9595",
                "services": "Mooring installation and service",
                "confidence": 0.9,
            },
            {
                "name": "Houghton Marine Service, Inc.",
                "phone": "781-631-9338",
                "services": "Annual maintenance",
                "confidence": 0.85,
            },
        ],
        "primary_contact": {
            "canonical_business_name": "Northeast Mooring & Salvage",
            "operator_type": "mooring_service",
            "phone": "781-631-9595",
        },
        "research_summary": "Salem Harbor moorings are managed by the harbormaster with private contractors.",
        "confidence": 0.88,
        "sources": ["https://example.com/salem"],
        "needs_review": False,
    }
    result = validate_research(data, None)
    assert result.harbor_name == "Salem Harbor"
    assert result.canonical_business_name == "Northeast Mooring & Salvage"
    assert len(result.additional_prospects) == 1
    assert "Salem Harbor" in (result.research_summary or "")
    assert "Northeast Mooring" in (result.research_summary or "")


def test_build_prompt_no_nearby_place():
    field = {
        "id": 50,
        "latitude": 42.5,
        "longitude": -70.85,
        "boat_count": 15,
        "location_name": "Marblehead, MA",
        "country": "United States",
    }
    prompt = build_prompt(field, None)
    assert "Marblehead" in prompt
    assert "No nearby marina" in prompt
    assert "harbor_name" in prompt


def test_parse_gemini_json():
    text = '```json\n{"canonical_business_name": "Test", "confidence": 0.9, "sources": []}\n```'
    data = parse_gemini_json(text)
    assert data["canonical_business_name"] == "Test"


def test_dedupe_by_phone(tmp_path: Path):
    db = tmp_path / "test.db"
    conn = get_connection(db)
    init_db(conn)
    scan_id = insert_scan(conn, source="t")
    f1 = insert_field(conn, scan_id, 41.0, -70.0, 5, 0.8)
    f2 = insert_field(conn, scan_id, 41.001, -70.001, 6, 0.8)
    from mooring_fields.database import link_field_to_prospect, upsert_prospect

    p1 = upsert_prospect(
        conn,
        {"canonical_business_name": "Same Marina", "phone": "5551234567"},
    )
    p2 = upsert_prospect(
        conn,
        {"canonical_business_name": "Same Marina LLC", "phone": "555-123-4567"},
    )
    link_field_to_prospect(conn, f1, p1)
    link_field_to_prospect(conn, f2, p2)
    summary = dedupe_prospects(conn, proximity_meters=500)
    assert summary["merged"] >= 1
    conn.close()


def test_import_prospects_csv(tmp_path: Path):
    db = tmp_path / "test.db"
    conn = get_connection(db)
    init_db(conn)
    from mooring_fields.database import upsert_prospect

    pid = upsert_prospect(conn, {"canonical_business_name": "Old Name"})
    conn.close()

    csv_path = tmp_path / "corrections.csv"
    csv_path.write_text(
        "prospect_id,canonical_business_name,phone,approved,needs_review\n"
        f"{pid},New Name,555-9999,true,false\n",
        encoding="utf-8",
    )
    result = import_prospects_csv(csv_path, db_path=db)
    assert result["prospects_updated"] == 1

    conn = get_connection(db)
    row = conn.execute("SELECT * FROM prospects WHERE id = ?", (pid,)).fetchone()
    conn.close()
    assert row["canonical_business_name"] == "New Name"
    assert row["approved"] == 1
