"""Tests for mooring field clustering logic."""

from mooring_fields.cluster_fields import (
    BoatDetection,
    cluster_boats,
    dedupe_boats,
    is_qualifying_field,
    MooringFieldCluster,
)


class TestClusterFields:
    def _boats_grid(self, center_lat: float, center_lon: float, n: int = 6) -> list[BoatDetection]:
        boats = []
        for i in range(n):
            boats.append(
                BoatDetection(
                    lat=center_lat + i * 0.00005,
                    lon=center_lon + i * 0.00002,
                    confidence=0.8,
                    image_stem="test",
                )
            )
        return boats

    def test_cluster_dense_boats(self):
        boats = self._boats_grid(41.5, -71.0, n=8)
        clusters = cluster_boats(boats, eps_m=80, min_samples=4)
        assert len(clusters) >= 1
        assert clusters[0].boat_count >= 4

    def test_is_qualifying_field(self):
        cluster = MooringFieldCluster(
            lat=41.5, lon=-71.0, boat_count=6, mean_confidence=0.7, boats=[]
        )
        assert is_qualifying_field(cluster, min_boats=5)
        assert not is_qualifying_field(cluster, min_boats=10)

    def test_sparse_boats_no_cluster(self):
        boats = self._boats_grid(41.5, -71.0, n=2)
        clusters = cluster_boats(boats, eps_m=30, min_samples=4)
        assert len(clusters) == 0

    def test_dedupe_removes_nearby_duplicates(self):
        boats = [
            BoatDetection(41.5, -71.0, 0.9, "a"),
            BoatDetection(41.500001, -71.000001, 0.5, "b"),
            BoatDetection(41.51, -71.01, 0.7, "c"),
        ]
        deduped = dedupe_boats(boats, min_dist_m=25)
        assert len(deduped) == 2
        assert deduped[0].confidence == 0.9
