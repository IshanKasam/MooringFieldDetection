"""Groq supply-chain research for mooring service companies.

Free alternative to Gemini when research_provider: groq. Reuses prompt/schema
helpers from gemini_supply_chain so DB/export shapes stay identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mooring_fields.gemini_supply_chain import (
    SYSTEM_INSTRUCTION,
    SupplyChainCompanyResult,
    _load_cache,
    _save_cache,
    build_supply_chain_prompt,
    parse_supply_chain_response,
)
from mooring_fields.groq_client import GroqClient
from mooring_fields.paths import GROQ_SUPPLY_CHAIN_CACHE



class LiveGroqSupplyChainProvider:
    """Batched supply-chain research via Groq (compound models search the web)."""

    def __init__(self, cfg: dict, cache_path: Path | None = None):
        self.cfg = cfg
        groq_cfg = cfg.get("groq", {})
        self.prompt_version = groq_cfg.get(
            "supply_chain_prompt_version",
            groq_cfg.get("prompt_version", "v1"),
        )
        self.max_per_call = int(cfg.get("max_companies_per_supply_chain_call", 6))
        self.cache_path = cache_path or GROQ_SUPPLY_CHAIN_CACHE
        self.cache = _load_cache(self.cache_path)
        self.client = GroqClient(cfg)
        self.calls_made = 0

    def _cache_key(self, batch: list[dict[str, Any]]) -> str:
        ids = ",".join(
            str(b["prospect_id"]) for b in sorted(batch, key=lambda x: x["prospect_id"])
        )
        harbors = ",".join(sorted({str(b.get("harbor_name") or "") for b in batch}))
        return f"groq:{self.prompt_version}:{self.client.model}:{harbors}:{ids}"

    def research_batch(self, batch: list[dict[str, Any]]) -> list[SupplyChainCompanyResult]:
        if not batch:
            return []
        key = self._cache_key(batch)
        if key in self.cache:
            return parse_supply_chain_response(self.cache[key], batch)

        prompt = build_supply_chain_prompt(batch)
        data, meta = self.client.generate_json(
            prompt=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
        )
        self.calls_made = self.client.calls_made

        if data is None:
            err = meta.get("error") or {}
            detail = str(err.get("detail") or err)[:500]
            if err.get("missing_key"):
                detail = (
                    "GROQ_API_KEY is not set — add a free key from "
                    "https://console.groq.com/keys to your .env."
                )
            elif err.get("status") == 429:
                detail = (
                    "Groq free-tier rate limit hit (HTTP 429). Retry later or "
                    "lower max_supply_chain_calls_per_run."
                )
            return [
                SupplyChainCompanyResult(
                    mooring_company=str(b.get("canonical_business_name") or "Unknown"),
                    harbor_name=b.get("harbor_name"),
                    prospect_id=b.get("prospect_id"),
                    field_ids=[
                        int(x)
                        for x in str(b.get("field_ids", "")).split(",")
                        if str(x).strip()
                    ],
                    company_summary=f"Supply chain research unavailable. {detail}",
                    overall_confidence="Low",
                )
                for b in batch
            ]

        if meta.get("sources"):
            data["_grounding_sources"] = meta["sources"]
        self.cache[key] = data
        _save_cache(self.cache_path, self.cache)
        return parse_supply_chain_response(data, batch)
