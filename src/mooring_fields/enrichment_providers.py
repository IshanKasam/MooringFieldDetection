"""Provider adapters for Places and Gemini enrichment."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mooring_fields.paths import ROOT


@dataclass
class PlaceResult:
    place_id: str | None
    name: str | None
    address: str | None
    phone: str | None
    website: str | None
    types: list[str]
    raw: dict[str, Any]


@dataclass
class ResearchResult:
    canonical_business_name: str | None
    operator_type: str | None
    phone: str | None
    email: str | None
    website: str | None
    research_summary: str | None
    confidence: float
    sources: list[str]
    needs_review: bool
    harbor_name: str | None = None
    additional_prospects: list[dict[str, Any]] | None = None
    raw: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.additional_prospects is None:
            self.additional_prospects = []
        if self.raw is None:
            self.raw = {}


class PlacesProvider(Protocol):
    def lookup(self, lat: float, lon: float, field_id: int) -> PlaceResult | None: ...


class ResearchProvider(Protocol):
    def research(self, field: dict[str, Any], place: PlaceResult | None) -> ResearchResult: ...


def _fixture_path(name: str) -> Path:
    return ROOT / "tests" / "fixtures" / "enrichment" / name


class MockPlacesProvider:
    """Return fixture Places data keyed by field_id mod fixture count."""

    def __init__(self, fixture_path: Path | None = None):
        path = fixture_path or _fixture_path("places_fixtures.json")
        self._data: dict[str, Any] = {}
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def lookup(self, lat: float, lon: float, field_id: int) -> PlaceResult | None:
        key = str(field_id)
        if key not in self._data:
            fixtures = list(self._data.values())
            if not fixtures:
                return PlaceResult(
                    place_id="mock_place_1",
                    name="Mock Harbor Marina",
                    address=f"{lat:.4f}, {lon:.4f}",
                    phone="555-0100",
                    website="https://example.com/marina",
                    types=["marina"],
                    raw={"mock": True},
                )
            entry = fixtures[field_id % len(fixtures)]
        else:
            entry = self._data[key]
        return PlaceResult(
            place_id=entry.get("place_id"),
            name=entry.get("name"),
            address=entry.get("address"),
            phone=entry.get("phone"),
            website=entry.get("website"),
            types=entry.get("types", ["marina"]),
            raw=entry,
        )


class MockResearchProvider:
    """Return fixture Gemini-style research."""

    def __init__(self, fixture_path: Path | None = None):
        path = fixture_path or _fixture_path("gemini_fixtures.json")
        self._data: dict[str, Any] = {}
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def research(self, field: dict[str, Any], place: PlaceResult | None) -> ResearchResult:
        fid = str(field.get("id", field.get("field_id", 0)))
        entry = self._data.get(fid)
        if entry is None:
            name = place.name if place else "Unknown Operator"
            entry = {
                "canonical_business_name": name,
                "operator_type": "marina",
                "phone": place.phone if place else None,
                "email": None,
                "website": place.website if place else None,
                "research_summary": f"Mock research for {name} at mooring field {fid}.",
                "confidence": 0.75,
                "sources": ["mock_provider"],
                "needs_review": False,
            }
        return ResearchResult(
            canonical_business_name=entry.get("canonical_business_name"),
            operator_type=entry.get("operator_type"),
            phone=entry.get("phone"),
            email=entry.get("email"),
            website=entry.get("website"),
            research_summary=entry.get("research_summary"),
            confidence=float(entry.get("confidence", 0.5)),
            sources=list(entry.get("sources", [])),
            needs_review=bool(entry.get("needs_review", True)),
            raw=entry,
        )


class ManualCSVPlacesProvider:
    """Load place data from CSV: field_id, name, address, phone, website, place_id."""

    def __init__(self, csv_path: Path):
        self._by_field: dict[int, dict[str, str]] = {}
        with csv_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                fid = int(row["field_id"])
                self._by_field[fid] = row

    def lookup(self, lat: float, lon: float, field_id: int) -> PlaceResult | None:
        row = self._by_field.get(field_id)
        if not row:
            return None
        return PlaceResult(
            place_id=row.get("place_id"),
            name=row.get("name") or row.get("canonical_business_name"),
            address=row.get("address"),
            phone=row.get("phone"),
            website=row.get("website"),
            types=["marina"],
            raw=dict(row),
        )


class ManualCSVResearchProvider:
    """Load research from CSV: prospect_id or field_id keyed rows."""

    def __init__(self, csv_path: Path):
        self._by_field: dict[int, dict[str, str]] = {}
        with csv_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                key = row.get("field_id") or row.get("prospect_id")
                if key:
                    self._by_field[int(key)] = row

    def research(self, field: dict[str, Any], place: PlaceResult | None) -> ResearchResult:
        fid = int(field.get("id", field.get("field_id", 0)))
        row = self._by_field.get(fid, {})
        sources = row.get("sources", "")
        return ResearchResult(
            canonical_business_name=row.get("canonical_business_name") or (place.name if place else None),
            operator_type=row.get("operator_type", "unknown"),
            phone=row.get("phone") or (place.phone if place else None),
            email=row.get("email"),
            website=row.get("website") or (place.website if place else None),
            research_summary=row.get("research_summary", ""),
            confidence=float(row.get("confidence") or 0.8),
            sources=[s.strip() for s in sources.split(";") if s.strip()] if sources else ["manual_csv"],
            needs_review=row.get("needs_review", "").lower() in ("1", "true", "yes"),
            raw=dict(row),
        )


def get_places_provider(cfg: dict, *, csv_path: Path | None = None) -> PlacesProvider:
    provider = cfg.get("provider", "mock")
    if provider == "live":
        from mooring_fields.places import LivePlacesProvider

        return LivePlacesProvider(cfg)
    if provider == "manual" and csv_path:
        return ManualCSVPlacesProvider(csv_path)
    return MockPlacesProvider()


def get_research_provider(cfg: dict, *, csv_path: Path | None = None) -> ResearchProvider:
    # research_provider overrides provider so Places can stay on Google (live)
    # while research runs on a different backend (e.g. free Groq).
    provider = cfg.get("research_provider") or cfg.get("provider", "mock")
    if provider in ("groq", "live"):
        from mooring_fields.llm_research import UnifiedLLMResearchProvider

        return UnifiedLLMResearchProvider(cfg, provider=provider)
    if provider == "manual" and csv_path:
        return ManualCSVResearchProvider(csv_path)
    return MockResearchProvider()
