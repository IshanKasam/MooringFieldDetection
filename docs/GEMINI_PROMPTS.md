# Gemini Prompt Specification

## Model

Default: `gemini-2.0-flash` with **Google Search grounding** (`use_google_search: true` in `config/enrichment.yaml`).

Prompt version: `v2` (cache key: `field_id:prompt_version`).

## Research goal

Mooring fields are often **open water with no adjacent marina POI**. Sales targets are:

1. **Harbor name** (required) — e.g. Marblehead Harbor, Salem Harbor, Beverly Harbor
2. **Harbormaster** — municipal office that assigns mooring permits
3. **Private mooring service companies** — authorized contractors who install, inspect, and service moorings (often multiple per harbor)

Example harbors (North Shore MA):

| Field | Harbor | Expected contractors |
|-------|--------|----------------------|
| MF 50 | Marblehead Harbor | Willard and Sons, Jordan's Marine, Mid-Harbor Moorings, Houghton Marine |
| MF 51 | Salem Harbor | Northeast Mooring & Salvage, Mid-Harbor Marine, Houghton Marine, Manchester Mooring |
| MF 52 | Beverly Harbor | Beverly Harbormaster, Manchester Mooring, Northeast Mooring & Salvage |
| MF 54 | Manchester Harbor (Proctor's / Whittier's Cove) | Manchester Mooring Service, Manchester Marine |

## System instruction

The model is instructed to:

- Identify harbor from lat/lon and address (not just nearest marina POI)
- Search the web for `"who does mooring services for {harbor name}"`
- Search cove-specific queries when sub-areas apply
- List **all** credible private mooring contractors with sourced phones/websites
- Pick a `primary_contact` among private contractors (not the harbormaster unless no contractors found)
- Never invent contact details

## User prompt template

See `build_prompt()` in `src/mooring_fields/gemini_research.py`. Includes:

- Field coordinates, boat count, reverse-geocoded address
- Nearby Places POI (if any) as **context only**
- Explicit workflow steps mirroring manual Google research

## Response JSON schema (v2)

```json
{
  "harbor_name": "Marblehead Harbor",
  "harbor_subarea": null,
  "harbormaster": {
    "name": "Town of Marblehead Harbormaster",
    "phone": "string or null",
    "website": "string or null",
    "notes": "Assigns mooring permits; servicing by private companies"
  },
  "mooring_service_companies": [
    {
      "name": "Willard and Sons Inc.",
      "phone": null,
      "website": null,
      "services": "Annual contracts, off-season storage",
      "confidence": 0.9
    }
  ],
  "primary_contact": {
    "canonical_business_name": "Willard and Sons Inc.",
    "operator_type": "mooring_service",
    "phone": null,
    "email": null,
    "website": null
  },
  "research_summary": "Narrative for salesperson",
  "confidence": 0.85,
  "sources": ["https://..."],
  "needs_review": false
}
```

## Pipeline behavior

- Fields with **no nearby marina** still proceed to Gemini (stub prospect, `places_done`)
- Primary company → main prospect row; additional companies → extra prospect rows linked to same field
- `research_summary` is formatted with harbor, harbormaster, and bulleted contractor list
- Grounding URLs from `groundingMetadata` are appended to `sources`

## Auto `needs_review` triggers

- Missing `harbor_name`
- `confidence` < 0.5
- No mooring companies and no phone/website on primary contact
- Email present without sources

## Re-run after prompt change

Bump `prompt_version` in config (now `v2`) or delete `data/gemini_cache.json` entries.

For previously **skipped** fields (no marina before v2):

```powershell
python -m mooring_fields.cli enrich-all --include-skipped --only-new
```

Or reset all exported fields and re-run full pipeline.
