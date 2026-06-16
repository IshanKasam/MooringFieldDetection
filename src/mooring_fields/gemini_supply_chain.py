"""Gemini supply-chain research for mooring service companies."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mooring_fields.gemini_client import GeminiClient, parse_gemini_json
from mooring_fields.paths import DATA_DIR

SUPPLY_CHAIN_CACHE = DATA_DIR / "supply_chain_cache.json"

SYSTEM_INSTRUCTION = """You are a marine industry supply-chain researcher focused on mooring ground tackle.

For each mooring service company provided, determine where they obtain materials and equipment used to construct and maintain moorings: chain, anchors, shackles, swivels, buoys, pennants, rope, hardware, and other ground tackle.

Use company websites, supplier catalogs, industry partnerships, public documents, social media, and photographs when available via search grounding. If direct supplier information is unavailable, provide the most likely suppliers based on equipment visible, regional marine supply networks, or industry-standard New England sourcing — and clearly mark conclusions as inferred.

Do not invent supplier relationships. Return ONLY valid JSON matching the user schema.

Focus on upstream supply chains (manufacturers, distributors, brands), not the mooring services the company sells to boat owners."""


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


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


@dataclass
class SupplyChainSupplierRow:
    supplier_or_manufacturer: str
    component_types: str
    evidence: str
    confidence_level: str
    confirmation_status: str
    notable_brands: str


@dataclass
class SupplyChainCompanyResult:
    mooring_company: str
    harbor_name: str | None
    prospect_id: int | None
    field_ids: list[int]
    known_suppliers: list[SupplyChainSupplierRow] = field(default_factory=list)
    company_summary: str = ""
    overall_confidence: str = "Low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mooring_company": self.mooring_company,
            "harbor_name": self.harbor_name,
            "prospect_id": self.prospect_id,
            "field_ids": self.field_ids,
            "company_summary": self.company_summary,
            "overall_confidence": self.overall_confidence,
            "known_suppliers": [
                {
                    "supplier_or_manufacturer": s.supplier_or_manufacturer,
                    "component_types": s.component_types,
                    "evidence": s.evidence,
                    "confidence_level": s.confidence_level,
                    "confirmation_status": s.confirmation_status,
                    "notable_brands": s.notable_brands,
                }
                for s in self.known_suppliers
            ],
        }


def build_supply_chain_prompt(batch: list[dict[str, Any]]) -> str:
    """Build a batched prompt for multiple mooring companies (optionally across harbors)."""
    lines = [
        "Research the upstream supply chain for each mooring service company below.",
        "",
        "For each company provide:",
        "- known_suppliers: list of suppliers/manufacturers/distributors with component_types, evidence, "
        "confidence_level (High/Medium/Low), confirmation_status (confirmed/inferred), notable_brands",
        "- company_summary: short narrative",
        "- overall_confidence: High/Medium/Low",
        "",
        "Companies to research:",
    ]
    for item in batch:
        lines.append(
            f"- prospect_id={item.get('prospect_id')}; "
            f"company={item.get('canonical_business_name')}; "
            f"harbor={item.get('harbor_name') or 'unknown'}; "
            f"website={item.get('website') or 'N/A'}; "
            f"field_ids={item.get('field_ids')}; "
            f"context={item.get('research_summary', '')[:400]}"
        )
    lines.append(
        "\nReturn ONLY valid JSON:\n"
        "{\n"
        '  "companies": [\n'
        "    {\n"
        '      "prospect_id": 1,\n'
        '      "mooring_company": "string",\n'
        '      "harbor_name": "string or null",\n'
        '      "overall_confidence": "High|Medium|Low",\n'
        '      "company_summary": "string",\n'
        '      "known_suppliers": [\n'
        "        {\n"
        '          "supplier_or_manufacturer": "string",\n'
        '          "component_types": "chain; shackles; buoys",\n'
        '          "evidence": "string",\n'
        '          "confidence_level": "High|Medium|Low",\n'
        '          "confirmation_status": "confirmed|inferred",\n'
        '          "notable_brands": "string"\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    return "\n".join(lines)


def parse_supply_chain_response(
    data: dict[str, Any],
    batch: list[dict[str, Any]],
) -> list[SupplyChainCompanyResult]:
    companies = data.get("companies") or []
    if not isinstance(companies, list):
        companies = []

    by_id = {int(b["prospect_id"]): b for b in batch if b.get("prospect_id")}
    by_name = {_normalize_name(str(b.get("canonical_business_name", ""))): b for b in batch}
    results: list[SupplyChainCompanyResult] = []

    for entry in companies:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("prospect_id")
        base = by_id.get(int(pid)) if pid is not None else None
        if base is None:
            base = by_name.get(_normalize_name(str(entry.get("mooring_company", ""))))
        field_ids = []
        if base and base.get("field_ids"):
            field_ids = [int(x) for x in str(base["field_ids"]).split(",") if x.strip()]

        suppliers: list[SupplyChainSupplierRow] = []
        for sup in entry.get("known_suppliers") or []:
            if not isinstance(sup, dict):
                continue
            suppliers.append(
                SupplyChainSupplierRow(
                    supplier_or_manufacturer=str(sup.get("supplier_or_manufacturer") or ""),
                    component_types=str(sup.get("component_types") or ""),
                    evidence=str(sup.get("evidence") or ""),
                    confidence_level=str(sup.get("confidence_level") or "Low"),
                    confirmation_status=str(sup.get("confirmation_status") or "inferred"),
                    notable_brands=str(sup.get("notable_brands") or ""),
                )
            )

        results.append(
            SupplyChainCompanyResult(
                mooring_company=str(
                    entry.get("mooring_company")
                    or (base or {}).get("canonical_business_name")
                    or "Unknown"
                ),
                harbor_name=entry.get("harbor_name") or (base or {}).get("harbor_name"),
                prospect_id=int(pid) if pid is not None else (base or {}).get("prospect_id"),
                field_ids=field_ids,
                known_suppliers=suppliers,
                company_summary=str(entry.get("company_summary") or ""),
                overall_confidence=str(entry.get("overall_confidence") or "Low"),
            )
        )
    return results


def format_supply_chain_summary(result: SupplyChainCompanyResult) -> str:
    lines = [
        f"Supply chain for {result.mooring_company}"
        + (f" ({result.harbor_name})" if result.harbor_name else "")
        + f" — overall confidence: {result.overall_confidence}",
    ]
    if result.company_summary:
        lines.append(result.company_summary)
    if result.known_suppliers:
        lines.append("Suppliers:")
        for sup in result.known_suppliers:
            line = f"- {sup.supplier_or_manufacturer} [{sup.component_types}]"
            line += f" ({sup.confidence_level}, {sup.confirmation_status})"
            if sup.notable_brands:
                line += f" — brands: {sup.notable_brands}"
            lines.append(line)
    return "\n".join(lines)


def flatten_supply_chain_rows(results: list[SupplyChainCompanyResult]) -> list[dict[str, Any]]:
    """Flatten to one export row per supplier line (safe for CSV/Excel)."""
    rows: list[dict[str, Any]] = []
    for co in results:
        if not co.known_suppliers:
            rows.append(
                {
                    "prospect_id": co.prospect_id,
                    "mooring_company": co.mooring_company,
                    "harbor_name": co.harbor_name,
                    "field_ids": ",".join(str(i) for i in co.field_ids),
                    "supplier_or_manufacturer": "",
                    "component_types": "",
                    "evidence": co.company_summary[:32000] if co.company_summary else "",
                    "confidence_level": co.overall_confidence,
                    "confirmation_status": "",
                    "notable_brands": "",
                    "company_overall_confidence": co.overall_confidence,
                }
            )
            continue
        for sup in co.known_suppliers:
            rows.append(
                {
                    "prospect_id": co.prospect_id,
                    "mooring_company": co.mooring_company,
                    "harbor_name": co.harbor_name,
                    "field_ids": ",".join(str(i) for i in co.field_ids),
                    "supplier_or_manufacturer": sup.supplier_or_manufacturer,
                    "component_types": sup.component_types,
                    "evidence": sup.evidence[:32000],
                    "confidence_level": sup.confidence_level,
                    "confirmation_status": sup.confirmation_status,
                    "notable_brands": sup.notable_brands[:8000],
                    "company_overall_confidence": co.overall_confidence,
                }
            )
    return rows


class MockSupplyChainProvider:
    """Fixture-based supply chain research for tests."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.calls_made = 0

    def research_batch(self, batch: list[dict[str, Any]]) -> list[SupplyChainCompanyResult]:
        self.calls_made += 1
        out: list[SupplyChainCompanyResult] = []
        for item in batch:
            name = item.get("canonical_business_name") or "Unknown"
            out.append(
                SupplyChainCompanyResult(
                    mooring_company=name,
                    harbor_name=item.get("harbor_name"),
                    prospect_id=item.get("prospect_id"),
                    field_ids=[
                        int(x)
                        for x in str(item.get("field_ids", "")).split(",")
                        if str(x).strip()
                    ],
                    known_suppliers=[
                        SupplyChainSupplierRow(
                            supplier_or_manufacturer="Acco/Peerless",
                            component_types="chain",
                            evidence="Mock fixture — industry-standard New England mooring chain.",
                            confidence_level="Medium",
                            confirmation_status="inferred",
                            notable_brands="grade 43 galvanized chain",
                        )
                    ],
                    company_summary=f"Mock supply chain research for {name}.",
                    overall_confidence="Medium",
                )
            )
        return out


class LiveSupplyChainProvider:
    def __init__(self, cfg: dict, cache_path: Path | None = None):
        self.cfg = cfg
        gemini_cfg = cfg.get("gemini", {})
        self.prompt_version = gemini_cfg.get("supply_chain_prompt_version", "v1")
        self.max_per_call = int(cfg.get("max_companies_per_supply_chain_call", 6))
        self.cache_path = cache_path or SUPPLY_CHAIN_CACHE
        self.cache = _load_cache(self.cache_path)
        self.client = GeminiClient(cfg)
        self.calls_made = 0

    def _cache_key(self, batch: list[dict[str, Any]]) -> str:
        ids = ",".join(str(b["prospect_id"]) for b in sorted(batch, key=lambda x: x["prospect_id"]))
        harbors = ",".join(sorted({str(b.get("harbor_name") or "") for b in batch}))
        return f"{self.prompt_version}:{harbors}:{ids}"

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
        self.calls_made += 1
        self.client.calls_made = self.calls_made

        if data is None:
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
                    company_summary=(
                        "Supply chain research unavailable. "
                        + str((meta.get("error") or {}).get("detail", ""))[:500]
                    ),
                    overall_confidence="Low",
                )
                for b in batch
            ]

        if meta.get("sources"):
            data["_grounding_sources"] = meta["sources"]
        self.cache[key] = data
        _save_cache(self.cache_path, self.cache)
        return parse_supply_chain_response(data, batch)


def get_supply_chain_provider(cfg: dict):
    if cfg.get("provider", "mock") == "live":
        return LiveSupplyChainProvider(cfg)
    return MockSupplyChainProvider(cfg)


def extract_harbor_from_prospect(row: dict[str, Any]) -> str | None:
    if row.get("harbor_name"):
        return row["harbor_name"]
    raw = row.get("raw_gemini_response")
    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, dict) and data.get("harbor_name"):
                return data["harbor_name"]
        except (json.JSONDecodeError, TypeError):
            pass
    summary = row.get("research_summary") or ""
    match = re.search(r"Harbor:\s*([^\n(]+)", summary)
    if match:
        return match.group(1).strip()
    return None
