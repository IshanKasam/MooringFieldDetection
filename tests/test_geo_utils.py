"""Tests for geospatial helpers."""

import pytest

from mooring_fields.geo_utils import (
    haversine_m,
    offset_latlon,
    tile_bounds,
    zoom_from_range,
)


class TestGeoUtils:
    def test_haversine_zero_distance(self):
        assert haversine_m(41.5, -71.0, 41.5, -71.0) == 0.0

    def test_haversine_known_distance(self):
        # ~111 km per degree latitude
        d = haversine_m(0, 0, 1, 0)
        assert 110_000 < d < 112_000

    def test_offset_latlon_north(self):
        lat, lon = offset_latlon(41.0, -71.0, 1000, 0)
        assert lat > 41.0
        assert lon == pytest.approx(-71.0, abs=1e-6)

    def test_zoom_from_range_reasonable(self):
        z = zoom_from_range(41.5, 1500, fovy_deg=30)
        assert 18 <= z <= 20

    def test_tile_bounds_ordering(self):
        b = tile_bounds(41.5, -71.0, 19)
        assert b.north > b.south
        assert b.east > b.west
