"""Tests for the Groq research provider (no network/API key required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mooring_fields.enrichment_providers import get_research_provider
from mooring_fields.groq_client import (
    extract_groq_sources,
    parse_groq_json,
    resolve_groq_config,
)
from mooring_fields.groq_research import LiveGroqResearchProvider

SAMPLE_JSON = {
    "harbor_name": "Manchester Harbor",
    "harbor_subarea": "Proctor's Cove",
    "harbormaster": {
        "name": "Manchester Harbormaster",
        "phone": "978-555-0101",
        "notes": "Issues mooring permits",
    },
    "mooring_service_companies": [
        {
            "name": "Crocker's Boat Yard",
            "phone": "978-526-1971",
            "website": "https://crockersboatyard.com",
            "services": "Mooring installation and seasonal service",
            "confidence": 0.9,
        }
    ],
    "primary_contact": {
        "canonical_business_name": "Crocker's Boat Yard",
        "operator_type": "mooring_service",
        "phone": "978-526-1971",
    },
    "research_summary": "Manchester Harbor moorings serviced by Crocker's Boat Yard.",
    "confidence": 0.9,
    "sources": ["https://crockersboatyard.com"],
    "needs_review": False,
}


def test_parse_groq_json_with_fence():
    text = '```json\n{"harbor_name": "Salem Harbor", "confidence": 0.8}\n```'
    assert parse_groq_json(text)["harbor_name"] == "Salem Harbor"


def test_parse_groq_json_with_prose_prefix():
    text = 'Here is the result:\n{"harbor_name": "Beverly Harbor"}\nDone.'
    assert parse_groq_json(text)["harbor_name"] == "Beverly Harbor"


def test_resolve_groq_config_defaults():
    cfg = resolve_groq_config({})
    assert cfg["model"] == "groq/compound-mini"
    assert cfg["temperature"] == 0.2


def test_extract_groq_sources_from_executed_tools():
    payload = {
        "choices": [
            {
                "message": {
                    "content": "{}",
                    "executed_tools": [
                        {
                            "search_results": {
                                "results": [
                                    {"url": "https://example.com/harbor"},
                                    {"url": "https://example.com/mooring"},
                                ]
                            }
                        }
                    ],
                }
            }
        ]
    }
    sources = extract_groq_sources(payload)
    assert "https://example.com/harbor" in sources
    assert "https://example.com/mooring" in sources


def test_research_provider_selection_groq():
    provider = get_research_provider({"research_provider": "groq"})
    assert isinstance(provider, LiveGroqResearchProvider)


def test_research_provider_override_keeps_places_on_live():
    # provider=live (Places on Google) but research routed to groq
    provider = get_research_provider({"provider": "live", "research_provider": "groq"})
    assert isinstance(provider, LiveGroqResearchProvider)


class _FakeClient:
    """Stand-in for GroqClient that returns canned JSON without HTTP."""

    def __init__(self, cfg: dict):
        self.model = "groq/compound-mini"
        self.calls_made = 0

    def generate_json(self, *, prompt: str, system_instruction: str):
        self.calls_made += 1
        return SAMPLE_JSON, {"sources": ["https://grounding.example/harbor"]}


class _FailingClient:
    def __init__(self, cfg: dict):
        self.model = "groq/compound-mini"
        self.calls_made = 0

    def generate_json(self, *, prompt: str, system_instruction: str):
        self.calls_made += 1
        return None, {"error": {"status": 429, "detail": "rate limited"}}


def test_provider_research_success(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mooring_fields.groq_research.GroqClient", _FakeClient)
    provider = LiveGroqResearchProvider({}, cache_path=tmp_path / "groq_cache.json")
    field = {"id": 1, "latitude": 42.57, "longitude": -70.76, "boat_count": 20}

    result = provider.research(field, None)

    assert result.harbor_name == "Manchester Harbor"
    assert result.canonical_business_name == "Crocker's Boat Yard"
    assert "https://grounding.example/harbor" in result.sources
    assert provider.calls_made == 1


def test_provider_research_caches(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mooring_fields.groq_research.GroqClient", _FakeClient)
    cache = tmp_path / "groq_cache.json"
    provider = LiveGroqResearchProvider({}, cache_path=cache)
    field = {"id": 7, "latitude": 42.5, "longitude": -70.8, "boat_count": 10}

    provider.research(field, None)
    provider.research(field, None)  # served from cache, no second call

    assert provider.calls_made == 1
    assert cache.exists()
    assert "7:v2:groq/compound-mini" in json.loads(cache.read_text(encoding="utf-8"))


def test_provider_research_falls_back_on_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("mooring_fields.groq_research.GroqClient", _FailingClient)
    provider = LiveGroqResearchProvider({}, cache_path=tmp_path / "groq_cache.json")
    field = {"id": 2, "latitude": 42.5, "longitude": -70.8, "boat_count": 5}

    result = provider.research(field, None)

    assert result.needs_review is True
    assert result.raw.get("groq_error", {}).get("status") == 429
    assert "429" in (result.research_summary or "")
