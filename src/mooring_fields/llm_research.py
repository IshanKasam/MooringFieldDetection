"""Unified LLM research & supply chain provider for Gemini and Groq."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mooring_fields.enrichment_providers import PlaceResult, ResearchResult
from mooring_fields.gemini_client import GeminiClient
from mooring_fields.gemini_research import (
    SYSTEM_INSTRUCTION,
    build_prompt,
    places_only_research,
    validate_research,
)
from mooring_fields.groq_client import GroqClient
from mooring_fields.paths import GEMINI_CACHE, GROQ_CACHE


def _load_cache(path: Path) -> dict[str, Any]:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


class UnifiedLLMResearchProvider:
    """Unified provider supporting both Gemini (live) and Groq LLM research."""

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        provider: str = "live",
        cache_path: Path | None = None,
    ):
        self.cfg = cfg
        self.provider = provider
        if provider == "groq":
            self.client = GroqClient(cfg)
            self.cache_path = cache_path or GROQ_CACHE
            groq_cfg = cfg.get("groq", {})
            self.prompt_version = groq_cfg.get("prompt_version", "v2")
        else:
            self.client = GeminiClient(cfg)
            self.cache_path = cache_path or GEMINI_CACHE
            gemini_cfg = cfg.get("gemini", {})
            self.prompt_version = gemini_cfg.get("prompt_version", "v2")

        self.model = self.client.model
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
        self.calls_made = getattr(self.client, "calls_made", 1)

        if data is None:
            fallback = places_only_research(field, place)
            err = meta.get("error") or {}
            fallback.raw[f"{self.provider}_error"] = err
            if err.get("missing_key"):
                fallback.research_summary = (
                    (fallback.research_summary or "")
                    + f" API key for {self.provider} is not set — add key to your .env to enable research."
                )
            if err.get("status") == 429:
                fallback.research_summary = (
                    (fallback.research_summary or "")
                    + f" {self.provider.capitalize()} rate limit hit (HTTP 429). Retry later."
                )
            return fallback

        grounding_sources = meta.get("sources") or []
        self.cache[key] = data
        _save_cache(self.cache_path, self.cache)
        return validate_research(data, place, grounding_sources=grounding_sources)
