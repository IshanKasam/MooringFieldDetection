"""Tests for KML parsing."""

from pathlib import Path

import pytest

from mooring_fields.kml_parser import parse_kml, write_sites_json
from mooring_fields.paths import KML_PATH

# Northeast US coastal bounding box (covers RI through northern ME)
LON_MIN, LON_MAX = -72.0, -66.5
LAT_MIN, LAT_MAX = 41.0, 45.5


class TestKmlParser:
    def test_parse_count(self):
        sites = parse_kml(KML_PATH)
        assert len(sites) == 123

    def test_coordinates_in_new_england(self):
        sites = parse_kml(KML_PATH)
        for site in sites:
            assert LON_MIN <= site.longitude <= LON_MAX
            assert LAT_MIN <= site.latitude <= LAT_MAX

    def test_unique_ids(self):
        sites = parse_kml(KML_PATH)
        ids = [s.id for s in sites]
        assert len(ids) == len(set(ids))

    def test_look_at_range_present(self):
        sites = parse_kml(KML_PATH)
        with_range = [s for s in sites if s.look_at.range is not None]
        assert len(with_range) >= 100

    def test_write_and_reload(self, tmp_path: Path):
        sites = parse_kml(KML_PATH)
        out = tmp_path / "sites.json"
        write_sites_json(sites, out)
        assert out.exists()
        assert out.stat().st_size > 0
