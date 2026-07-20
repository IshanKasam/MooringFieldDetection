"""Tests for NOAA/OSM candidate generation helpers."""

from __future__ import annotations

from pathlib import Path

from mooring_fields.kml_parser import parse_kml
from mooring_fields.noaa_candidates import (
    Candidate,
    dedupe_candidates,
    write_candidates_kml,
)


def test_dedupe_prefers_marina_and_drops_nearby_mooring():
    marina = Candidate(42.0, -70.0, "Harbor Marina", "M", "osm_marina", "A")
    mooring_near = Candidate(42.0005, -70.0005, "Buoy", "MO", "osm_mooring", "B")
    far = Candidate(42.1, -70.1, "Far Mooring", "MO", "noaa_anchorage", "C")
    kept = dedupe_candidates([mooring_near, marina, far], radius_m=150)
    assert len(kept) == 2
    assert kept[0].source_type == "M"
    assert {c.source_id for c in kept} == {"A", "C"}


def test_write_candidates_kml_roundtrips_parse_kml(tmp_path: Path):
    cands = [
        Candidate(41.55, -70.61, "Test Marina", "M", "osm_marina", "ABCDEF0123456789"),
        Candidate(42.54, -70.87, "Test Anchorage", "MO", "noaa_anchorage", "FEDCBA9876543210"),
    ]
    out = write_candidates_kml(cands, tmp_path / "cands.kml")
    sites = parse_kml(out)
    assert len(sites) == 2
    assert {s.id for s in sites} == {"ABCDEF0123456789", "FEDCBA9876543210"}
    assert abs(sites[0].latitude - 41.55) < 1e-5 or abs(sites[1].latitude - 41.55) < 1e-5
