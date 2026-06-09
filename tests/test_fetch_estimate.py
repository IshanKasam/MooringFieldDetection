"""Tests for fetch cost estimation."""

from mooring_fields.fetch_imagery import estimate_fetch, iter_planned_tiles


class TestFetchEstimate:
    def test_planned_tile_count(self):
        planned = iter_planned_tiles()
        # 123 sites × 5 directions
        assert len(planned) == 123 * 5

    def test_estimate_structure(self):
        est = estimate_fetch()
        assert est["total_tiles"] == 615
        assert est["api_calls_needed"] >= 0
        assert est["within_free_tier"] is True
        assert est["within_run_cap"] is True
