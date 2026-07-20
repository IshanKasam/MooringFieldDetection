"""Tests for Kaggle scan package / import helpers."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from mooring_fields.database import (
    get_connection,
    get_stats,
    init_db,
    insert_field,
    insert_scan,
    list_scans,
)
from mooring_fields.kaggle_scan import import_scan, package_kaggle_scan


def test_package_kaggle_scan_zip(tmp_path: Path):
    imagery = tmp_path / "imagery" / "scan"
    imagery.mkdir(parents=True)
    (imagery / "site_a_center_z19.png").write_bytes(b"fake-png")
    (imagery / "site_a_center_z19.json").write_text(
        '{"site_id": "ABCD1234"}', encoding="utf-8"
    )
    # Extra tile for a different site — must be excluded when only_kml_sites=True
    (imagery / "other_center_z19.png").write_bytes(b"other")
    (imagery / "other_center_z19.json").write_text(
        '{"site_id": "OTHER999"}', encoding="utf-8"
    )
    kml = tmp_path / "c.kml"
    kml.write_text(
        '<?xml version="1.0"?><kml xmlns="http://www.opengis.net/kml/2.2">'
        '<Document><Placemark id="ABCD1234"><name>t</name>'
        "<Point><coordinates>-70,42,0</coordinates></Point>"
        "</Placemark></Document></kml>",
        encoding="utf-8",
    )
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"fake-weights")
    out = tmp_path / "payload.zip"
    report = package_kaggle_scan(
        kml_path=kml,
        imagery_dir=tmp_path / "imagery",
        weights=weights,
        output_zip=out,
    )
    assert out.is_file()
    assert report["png_count"] == 1
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert "candidates.kml" in names
    assert "imagery/scan/site_a_center_z19.png" in names
    assert "imagery/scan/other_center_z19.png" not in names
    assert "weights/best.pt" in names
    assert "manifest.json" in names


def test_import_scan_copies_fields(tmp_path: Path):
    src_db = tmp_path / "cloud.db"
    dst_db = tmp_path / "local.db"
    conn = get_connection(src_db)
    init_db(conn)
    sid = insert_scan(conn, source="scan:candidates_FL.kml", weights="best.pt", split="scan")
    insert_field(
        conn,
        sid,
        latitude=26.1,
        longitude=-80.1,
        boat_count=9,
        mean_confidence=0.7,
        location_name="Test Harbor, FL",
        country="United States",
    )
    conn.close()

    result = import_scan(src_db, dest_db=dst_db, source_label="import:FL")
    assert result["fields_imported"] == 1
    dst = get_connection(dst_db)
    init_db(dst)
    assert get_stats(dst)["fields"] == 1
    assert list_scans(dst)[0]["source"] == "import:FL"
    dst.close()
