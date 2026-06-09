"""Tests for geographic train/val split."""

from mooring_fields.kml_parser import parse_kml
from mooring_fields.paths import KML_PATH
from mooring_fields.split_sites import geographic_split


class TestGeographicSplit:
    def test_split_covers_all_sites(self):
        sites = parse_kml(KML_PATH)
        train_ids, val_ids = geographic_split(sites, train_ratio=0.8, random_seed=42)
        assert len(train_ids) + len(val_ids) == len(sites)
        assert len(set(train_ids) & set(val_ids)) == 0

    def test_val_has_at_least_one_per_cluster(self):
        sites = parse_kml(KML_PATH)
        _, val_ids = geographic_split(sites)
        assert len(val_ids) >= 5
