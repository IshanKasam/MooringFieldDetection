"""Tests for dock/marina post-cluster filter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from mooring_fields.cluster_fields import BoatDetection, MooringFieldCluster, clusters_from_boats
from mooring_fields.dock_filter import (
    DockPoint,
    TILE_DEG,
    _tiles_covering_points,
    cluster_aspect_ratio,
    fetch_dock_geometries,
    filter_mooring_clusters,
    min_distance_m,
)


def _boat(lat: float, lon: float, conf: float = 0.8) -> BoatDetection:
    return BoatDetection(lat=lat, lon=lon, confidence=conf, image_stem="t")


def _cluster(
    lat: float, lon: float, boats: list[BoatDetection] | None = None
) -> MooringFieldCluster:
    boats = boats or [_boat(lat, lon)]
    return MooringFieldCluster(
        lat=lat,
        lon=lon,
        boat_count=len(boats),
        mean_confidence=0.8,
        boats=boats,
    )


CFG = {
    "dock_filter_enabled": True,
    "reject_near_dock_meters": 80,
    "reject_linear_aspect_ratio": 4.0,
    "dock_filter_soft_fail": True,
    "reject_shoreline_meters": 0,
    "reject_spacing_cv_below": 0,
    "reject_density_above": 0,
    "reject_pier_alignment_deg": 0,
}


class TestTiling:
    def test_tile_deg_is_half_degree(self):
        assert TILE_DEG == 0.5

    def test_two_distant_points_not_continent_grid(self):
        tiles = _tiles_covering_points([(41.6, -70.9), (27.8, -82.6)])
        # Coastal cells only — not a full FL→MA lattice
        assert 1 <= len(tiles) <= 24
        for west, south, east, north in tiles:
            assert abs(east - west - TILE_DEG) < 1e-9
            assert abs(north - south - TILE_DEG) < 1e-9


class TestDockDistance:
    def test_near_pier_rejected(self):
        pier = [DockPoint(lat=41.5, lon=-71.0, kind="pier")]
        near = _cluster(41.5001, -71.0)  # ~11 m
        far = _cluster(41.503, -71.0)  # ~330 m
        kept, stats = filter_mooring_clusters([near, far], CFG, docks=pier, shoreline=[])
        assert stats["rejected_near_dock"] == 1
        assert len(kept) == 1
        assert kept[0].lat == pytest.approx(41.503)

    def test_far_from_dock_kept(self):
        pier = [DockPoint(lat=41.5, lon=-71.0, kind="pier")]
        far = _cluster(41.503, -71.0)
        kept, stats = filter_mooring_clusters([far], CFG, docks=pier, shoreline=[])
        assert stats["rejected"] == 0
        assert len(kept) == 1

    def test_min_distance(self):
        docks = [DockPoint(41.5, -71.0, "pier"), DockPoint(42.0, -71.0, "marina")]
        d = min_distance_m(41.5001, -71.0, docks)
        assert d < 20


class TestAspectRatio:
    def test_linear_pier_line_rejected(self):
        # ~200 m east-west line of boats (high aspect)
        boats = [_boat(41.5, -71.0 + i * 0.0003) for i in range(8)]
        cluster = _cluster(41.5, -71.00105, boats)
        assert cluster_aspect_ratio(boats) >= 4.0
        kept, stats = filter_mooring_clusters([cluster], CFG, docks=[], shoreline=[])
        assert stats["rejected_linear"] == 1
        assert kept == []

    def test_compact_blob_kept(self):
        boats = [
            _boat(41.5 + (i % 3) * 0.00005, -71.0 + (i // 3) * 0.00005)
            for i in range(9)
        ]
        cluster = _cluster(41.5, -71.0, boats)
        assert cluster_aspect_ratio(boats) < 4.0
        kept, stats = filter_mooring_clusters([cluster], CFG, docks=[], shoreline=[])
        assert stats["rejected"] == 0
        assert len(kept) == 1


class TestEnabledFlag:
    def test_disabled_passes_all(self):
        pier = [DockPoint(lat=41.5, lon=-71.0, kind="pier")]
        near = _cluster(41.5001, -71.0)
        cfg = {**CFG, "dock_filter_enabled": False}
        kept, stats = filter_mooring_clusters([near], cfg, docks=pier)
        assert stats["enabled"] is False
        assert len(kept) == 1


class TestOverpassMock:
    def test_fetch_parses_elements(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "mooring_fields.dock_filter.CACHE_DIR", tmp_path / "osm_docks"
        )
        payload = {
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 41.5,
                    "lon": -71.0,
                    "tags": {"man_made": "pier"},
                },
                {
                    "type": "way",
                    "id": 2,
                    "center": {"lat": 41.51, "lon": -71.01},
                    "tags": {"leisure": "marina"},
                },
            ]
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = mock_resp

        points = fetch_dock_geometries(
            (-71.1, 41.4, -70.9, 41.6), client=mock_client, use_cache=True
        )
        assert len(points) == 2
        assert points[0].kind == "pier"
        assert points[1].kind == "marina"
        mock_client.post.assert_called()

        # Second call hits cache (no extra HTTP)
        mock_client.post.reset_mock()
        points2 = fetch_dock_geometries(
            (-71.1, 41.4, -70.9, 41.6), client=mock_client, use_cache=True
        )
        assert len(points2) == 2
        mock_client.post.assert_not_called()

    def test_sample_points_tiles_not_full_bbox(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "mooring_fields.dock_filter.CACHE_DIR", tmp_path / "osm_docks"
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"elements": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.return_value = mock_resp

        # Huge bbox, but only two coastal points → few tiles, not 100+
        fetch_dock_geometries(
            (-87.6, 24.5, -69.9, 42.1),
            client=mock_client,
            use_cache=False,
            sample_points=[(41.6, -70.9), (27.8, -82.6)],
        )
        assert 1 <= mock_client.post.call_count <= 24

    def test_partial_tile_failure_keeps_successes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "mooring_fields.dock_filter.CACHE_DIR", tmp_path / "osm_docks"
        )
        ok = MagicMock()
        ok.status_code = 200
        ok.json.return_value = {
            "elements": [
                {"type": "node", "lat": 41.5, "lon": -71.0, "tags": {"man_made": "pier"}}
            ]
        }
        ok.raise_for_status = MagicMock()

        def post_side_effect(url, data=None, **_kw):
            # Fail first tile requests, succeed later
            if post_side_effect.n == 0:
                post_side_effect.n += 1
                raise httpx.ConnectError("timeout")
            return ok

        post_side_effect.n = 0
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.post.side_effect = post_side_effect

        points = fetch_dock_geometries(
            (-72.0, 41.0, -70.0, 43.0),
            client=mock_client,
            use_cache=False,
            sample_points=[(41.2, -71.5), (42.5, -70.5)],
        )
        assert len(points) >= 1

    def test_soft_fail_keeps_clusters(self):
        cluster = _cluster(41.5, -71.0)

        def boom(*_a, **_k):
            raise httpx.ConnectError("offline")

        with patch(
            "mooring_fields.dock_filter.fetch_dock_geometries", side_effect=boom
        ):
            kept, stats = filter_mooring_clusters([cluster], CFG, bbox=(-71.1, 41.4, -70.9, 41.6))
        assert stats["overpass_error"]
        assert len(kept) == 1


class TestClustersFromBoatsWiring:
    def test_filter_called_when_enabled(self):
        boats = [
            _boat(41.5 + (i % 3) * 0.0002, -71.0 + (i // 3) * 0.0002)
            for i in range(9)
        ]
        cfg = {
            "dedupe_radius_meters": 5,
            "eps_meters": 75,
            "min_samples": 3,
            "min_boats": 4,
            **CFG,
        }
        fake = ([_cluster(41.5, -71.0, boats)], {"kept": 1, "rejected": 0})
        with patch(
            "mooring_fields.dock_filter.filter_mooring_clusters",
            return_value=fake,
        ) as mock_filter:
            out = clusters_from_boats(boats, cfg)
        mock_filter.assert_called_once()
        assert len(out) == 1

    def test_filter_skipped_when_disabled(self):
        boats = [
            _boat(41.5 + (i % 3) * 0.0002, -71.0 + (i // 3) * 0.0002)
            for i in range(9)
        ]
        cfg = {
            "dedupe_radius_meters": 5,
            "eps_meters": 75,
            "min_samples": 3,
            "min_boats": 4,
            **CFG,
            "dock_filter_enabled": False,
        }
        with patch(
            "mooring_fields.dock_filter.filter_mooring_clusters"
        ) as mock_filter:
            out = clusters_from_boats(boats, cfg)
        mock_filter.assert_not_called()
        assert len(out) >= 1
