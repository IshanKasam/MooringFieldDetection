"""Tests for Groq supply-chain provider selection (no network required)."""

from __future__ import annotations

from mooring_fields.gemini_research import places_only_research
from mooring_fields.gemini_supply_chain import (
    LiveSupplyChainProvider,
    MockSupplyChainProvider,
    get_supply_chain_provider,
)
from mooring_fields.groq_supply_chain import LiveGroqSupplyChainProvider


def test_get_supply_chain_provider_prefers_groq_when_research_provider_groq():
    cfg = {"provider": "live", "research_provider": "groq"}
    provider = get_supply_chain_provider(cfg)
    assert isinstance(provider, LiveGroqSupplyChainProvider)


def test_get_supply_chain_provider_gemini_when_research_live():
    cfg = {"provider": "live", "research_provider": "live"}
    provider = get_supply_chain_provider(cfg)
    assert isinstance(provider, LiveSupplyChainProvider)


def test_get_supply_chain_provider_mock_when_not_live():
    cfg = {"provider": "mock"}
    provider = get_supply_chain_provider(cfg)
    assert isinstance(provider, MockSupplyChainProvider)


def test_places_only_research_is_provider_neutral():
    result = places_only_research(
        {"id": 1, "boat_count": 10, "location_name": "Test Harbor"},
        None,
    )
    assert "Gemini unavailable" not in (result.research_summary or "")
    assert "LLM research unavailable" in (result.research_summary or "")
    assert "GROQ_API_KEY" in (result.research_summary or "")
