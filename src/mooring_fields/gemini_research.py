"""Gemini API research enrichment for mooring field prospects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mooring_fields.enrichment_providers import PlaceResult, ResearchResult
from mooring_fields.gemini_client import GeminiClient, parse_gemini_json
from mooring_fields.paths import GEMINI_CACHE

SYSTEM_INSTRUCTION = """You are a maritime mooring-field sales research assistant for the North Shore of Massachusetts and similar US harbors.

Your job is NOT to find the nearest marina POI. Mooring fields are often open water with no adjacent business. Instead:

1. Identify the HARBOR NAME from coordinates and address (required). Include sub-areas/coves when relevant (e.g. Proctor's Cove, Whittier's Cove in Manchester Harbor).
2. Determine who ADMINISTERS mooring permits (municipal harbormaster / harbor department) and find their public phone or website when available.
3. Search the web (use grounding) for authorized PRIVATE mooring service companies that install, maintain, and service moorings in that harbor. Example queries:
   - "who does mooring services for {harbor name}"
   - "mooring service companies {harbor name} Massachusetts"
   - For specific coves: "mooring service {cove name} {town}"
4. List ALL credible mooring service companies you find (not just one), with phone numbers and websites only when found in search results.
5. Pick the best primary sales contact among the private mooring service companies (prefer companies that explicitly service that harbor).

Do not invent phone numbers, emails, or websites. If uncertain, set confidence below 0.5 and needs_review true.

Return ONLY valid JSON matching the schema described in the user message."""


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_api_key() -> str:
    from mooring_fields.gemini_client import get_api_key as _get_key

    return _get_key(free_tier_only=True)


def build_prompt(field: dict[str, Any], place: PlaceResult | None) -> str:
    lat = field.get("latitude")
    lon = field.get("longitude")
    place_name = place.name if place else "None found nearby"
    place_note = (
        "A nearby marina/yacht club was found via Google Places (use as context only)."
        if place
        else "No nearby marina or mooring business was found via Google Places. This is common - research the harbor and private mooring contractors via web search."
    )
    return (
        f"Mooring field detection (satellite):\n"
        f"- Field ID: {field.get('id')}\n"
        f"- Latitude: {lat}\n"
        f"- Longitude: {lon}\n"
        f"- Boat count (estimate): {field.get('boat_count')}\n"
        f"- Reverse-geocoded address: {field.get('location_name')}\n"
        f"- Country: {field.get('country')}\n\n"
        f"Google Places nearby POI:\n"
        f"- {place_note}\n"
        f"- Name: {place_name}\n"
        f"- Address: {place.address if place else 'N/A'}\n"
        f"- Phone: {place.phone if place else 'N/A'}\n"
        f"- Website: {place.website if place else 'N/A'}\n"
        f"- Types: {', '.join(place.types) if place and place.types else 'N/A'}\n\n"
        "Research workflow:\n"
        f"1. What harbor is at ({lat}, {lon})? Harbor name is REQUIRED.\n"
        "2. Who is the harbormaster / harbor department that assigns mooring permits?\n"
        "3. Search: who does mooring services for that harbor?\n"
        "4. If the field is in a named cove or sub-area, also search mooring services for that cove.\n"
        "5. List all private mooring service companies (with sourced phones/websites).\n\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "harbor_name": "string (required)",\n'
        '  "harbor_subarea": "string or null (cove/anchorage name if applicable)",\n'
        '  "harbormaster": {\n'
        '    "name": "string",\n'
        '    "phone": "string or null",\n'
        '    "website": "string or null",\n'
        '    "notes": "string (role in mooring permitting)"\n'
        "  },\n"
        '  "mooring_service_companies": [\n'
        "    {\n"
        '      "name": "string",\n'
        '      "phone": "string or null",\n'
        '      "website": "string or null",\n'
        '      "services": "string (what they do: spring/fall, inspections, etc.)",\n'
        '      "confidence": 0.0\n'
        "    }\n"
        "  ],\n"
        '  "primary_contact": {\n'
        '    "canonical_business_name": "string (best private mooring contractor to call first)",\n'
        '    "operator_type": "mooring_service|marina|harbormaster|unknown",\n'
        '    "phone": "string or null",\n'
        '    "email": "string or null",\n'
        '    "website": "string or null"\n'
        "  },\n"
        '  "research_summary": "string (narrative for salesperson: harbor, harbormaster role, list of contractors)",\n'
        '  "confidence": 0.0,\n'
        '  "sources": ["url or source label", ...],\n'
        '  "needs_review": true\n'
        "}"
    )


def _format_research_summary(data: dict[str, Any]) -> str:
    if data.get("research_summary"):
        summary = str(data["research_summary"]).strip()
    else:
        summary = ""

    harbor = data.get("harbor_name") or "Unknown harbor"
    subarea = data.get("harbor_subarea")
    header = f"Harbor: {harbor}"
    if subarea:
        header += f" ({subarea})"

    hm = data.get("harbormaster") or {}
    if isinstance(hm, dict) and hm.get("name"):
        hm_line = f"Harbormaster: {hm['name']}"
        if hm.get("phone"):
            hm_line += f" | {hm['phone']}"
        if hm.get("website"):
            hm_line += f" | {hm['website']}"
        if hm.get("notes"):
            hm_line += f" — {hm['notes']}"
        header += f"\n{hm_line}"

    companies = data.get("mooring_service_companies") or []
    if companies:
        header += "\n\nMooring service companies:"
        for co in companies:
            if not isinstance(co, dict):
                continue
            line = f"- {co.get('name', 'Unknown')}"
            if co.get("phone"):
                line += f" | {co['phone']}"
            if co.get("website"):
                line += f" | {co['website']}"
            if co.get("services"):
                line += f" — {co['services']}"
            header += f"\n{line}"

    if summary and summary not in header:
        return f"{header}\n\n{summary}"
    return header or summary or "No research summary available."


def _company_to_prospect_dict(
    company: dict[str, Any],
    *,
    harbor_name: str | None,
    sources: list[str],
    needs_review: bool,
) -> dict[str, Any]:
    name = company.get("name") or "Unknown mooring service"
    summary = company.get("services") or ""
    if harbor_name:
        summary = f"Services {harbor_name}. {summary}".strip()
    return {
        "canonical_business_name": name,
        "operator_type": "mooring_service",
        "phone": company.get("phone"),
        "email": None,
        "website": company.get("website"),
        "research_summary": summary,
        "confidence": float(company.get("confidence", 0.6)),
        "sources": list(sources),
        "needs_review": needs_review,
    }


def validate_research(
    data: dict[str, Any],
    place: PlaceResult | None,
    *,
    grounding_sources: list[str] | None = None,
) -> ResearchResult:
    primary = data.get("primary_contact") or {}
    if not isinstance(primary, dict):
        primary = {}

    companies = data.get("mooring_service_companies") or []
    if not isinstance(companies, list):
        companies = []

    canonical = (
        primary.get("canonical_business_name")
        or (companies[0].get("name") if companies and isinstance(companies[0], dict) else None)
        or (place.name if place else None)
        or data.get("harbor_name")
    )

    confidence = float(data.get("confidence", 0.5))
    sources = list(data.get("sources") or [])
    if grounding_sources:
        for src in grounding_sources:
            if src not in sources:
                sources.append(src)
    if isinstance(sources, str):
        sources = [sources]

    email = primary.get("email")
    phone = primary.get("phone") or (place.phone if place else None)
    if not phone and companies and isinstance(companies[0], dict):
        phone = companies[0].get("phone")

    website = primary.get("website") or (place.website if place else None)
    operator_type = primary.get("operator_type") or "mooring_service"

    needs_review = bool(data.get("needs_review", confidence < 0.5))
    if not data.get("harbor_name"):
        needs_review = True
    if email and not sources:
        needs_review = True
    if not companies and not phone and not website:
        needs_review = True
    if place and canonical:
        pn = (place.name or "").lower()
        cn = str(canonical).lower()
        if pn and cn and pn not in cn and cn not in pn and operator_type == "marina":
            needs_review = True

    harbor_name = data.get("harbor_name")
    research_summary = _format_research_summary(data)

    additional: list[dict[str, Any]] = []
    primary_name = (canonical or "").lower()
    for co in companies:
        if not isinstance(co, dict):
            continue
        co_name = (co.get("name") or "").lower()
        if not co_name or co_name == primary_name:
            continue
        additional.append(
            _company_to_prospect_dict(
                co,
                harbor_name=harbor_name,
                sources=sources,
                needs_review=needs_review or float(co.get("confidence", 0.6)) < 0.5,
            )
        )

    return ResearchResult(
        canonical_business_name=canonical,
        operator_type=operator_type,
        phone=phone,
        email=email,
        website=website,
        research_summary=research_summary,
        confidence=confidence,
        sources=sources,
        needs_review=needs_review,
        harbor_name=harbor_name,
        additional_prospects=additional,
        raw=data,
    )


def places_only_research(field: dict[str, Any], place: PlaceResult | None) -> ResearchResult:
    """Fallback when Gemini API is unavailable — Places data only."""
    name = place.name if place else field.get("location_name")
    return ResearchResult(
        canonical_business_name=name,
        operator_type=(place.types[0] if place and place.types else "unknown"),
        phone=place.phone if place else None,
        email=None,
        website=place.website if place else None,
        research_summary=(
            f"Places-only enrichment (Gemini unavailable). "
            f"Detected mooring field with {field.get('boat_count')} boats near {name}. "
            "Re-run enrich-research after setting GEMINI_API_KEY for harbor and mooring contractor lookup."
        ),
        confidence=0.35,
        sources=["google_places"] if place else [],
        needs_review=True,
        harbor_name=None,
        additional_prospects=[],
        raw={"fallback": "places_only", "field_id": field.get("id")},
    )


class LiveGeminiResearchProvider:
    """Gemini generateContent with Google Search grounding and disk cache."""

    def __init__(self, cfg: dict, cache_path: Path | None = None):
        self.cfg = cfg
        gemini_cfg = cfg.get("gemini", {})
        self.client = GeminiClient(cfg)
        self.model = self.client.model
        self.prompt_version = gemini_cfg.get("prompt_version", "v2")
        self.cache_path = cache_path or GEMINI_CACHE
        self.cache = _load_cache(self.cache_path)
        self.calls_made = 0

    def _cache_key(self, field_id: int) -> str:
        return f"{field_id}:{self.prompt_version}"

    def research(self, field: dict[str, Any], place: PlaceResult | None) -> ResearchResult:
        field_id = int(field.get("id", field.get("field_id", 0)))
        key = self._cache_key(field_id)
        if key in self.cache:
            cached = self.cache[key]
            if isinstance(cached, dict) and cached.get("fallback") == "places_only":
                pass
            else:
                return validate_research(cached, place)

        data, meta = self.client.generate_json(
            prompt=build_prompt(field, place),
            system_instruction=SYSTEM_INSTRUCTION,
        )
        self.calls_made = self.client.calls_made

        if data is None:
            fallback = places_only_research(field, place)
            fallback.raw["gemini_error"] = meta.get("error")
            err = meta.get("error") or {}
            if err.get("status") == 429:
                fallback.research_summary = (
                    (fallback.research_summary or "")
                    + " Gemini free-tier quota exhausted (HTTP 429). Retry tomorrow or use gemini-2.0-flash-lite."
                )
            return fallback

        grounding_sources = meta.get("sources") or []
        self.cache[key] = data
        _save_cache(self.cache_path, self.cache)
        return validate_research(data, place, grounding_sources=grounding_sources)
