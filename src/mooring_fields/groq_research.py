"""Groq LLM research enrichment for mooring field prospects.

Free, no-credit-card alternative to Gemini. Reuses the same prompt, JSON schema,
validation, and Places-only fallback as gemini_research so downstream code
(dedupe, export, DB) is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mooring_fields.enrichment_providers import PlaceResult, ResearchResult
from mooring_fields.gemini_research import (
    SYSTEM_INSTRUCTION,
    _load_cache,
    _save_cache,
    build_prompt,
    places_only_research,
    validate_research,
)
from mooring_fields.groq_client import GroqClient
from mooring_fields.paths import GROQ_CACHE


class LiveGroqResearchProvider:
    """Groq chat completions (compound models search the web) with disk cache."""

    def __init__(self, cfg: dict, cache_path: Path | None = None):
        self.cfg = cfg
        groq_cfg = cfg.get("groq", {})
        self.client = GroqClient(cfg)
        self.model = self.client.model
        self.prompt_version = groq_cfg.get("prompt_version", "v2")
        self.cache_path = cache_path or GROQ_CACHE
        self.cache = _load_cache(self.cache_path)
        self.calls_made = 0

    def _cache_key(self, field_id: int) -> str:
        return f"{field_id}:{self.prompt_version}:{self.model}"

    def research(self, field: dict[str, Any], place: PlaceResult | None) -> ResearchResult:
        field_id = int(field.get("id", field.get("field_id", 0)))
        key = self._cache_key(field_id)
        if key in self.cache:
            cached = self.cache[key]
            if not (isinstance(cached, dict) and cached.get("fallback") == "places_only"):
                return validate_research(cached, place)

        data, meta = self.client.generate_json(
            prompt=build_prompt(field, place),
            system_instruction=SYSTEM_INSTRUCTION,
        )
        self.calls_made = self.client.calls_made

        if data is None:
            fallback = places_only_research(field, place)
            fallback.raw["groq_error"] = meta.get("error")
            err = meta.get("error") or {}
            if err.get("missing_key"):
                fallback.research_summary = (
                    (fallback.research_summary or "")
                    + " GROQ_API_KEY is not set — add a free key from "
                    "https://console.groq.com/keys to your .env to enable LLM research."
                )
            if err.get("status") == 429:
                fallback.research_summary = (
                    (fallback.research_summary or "")
                    + " Groq free-tier rate limit hit (HTTP 429). Retry later or "
                    "lower the batch size."
                )
            return fallback

        grounding_sources = meta.get("sources") or []
        self.cache[key] = data
        _save_cache(self.cache_path, self.cache)
        return validate_research(data, place, grounding_sources=grounding_sources)
