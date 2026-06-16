# Enrichment API Budget Policy

Goal: **$0 billed** — stay within Google Maps Platform monthly credit and Gemini **free tier only**.

## APIs used

| API | Calls per field (typical) | Free-tier notes |
|-----|---------------------------|-----------------|
| Geocoding | 0 (already on field row) | $200/mo Maps credit |
| Places Nearby + Details | 2 | Maps Platform credit |
| Gemini generateContent | 1 | Free Flash / Flash-Lite only |
| Gemini supply chain (batched) | ~1 per 6 companies | Same free-tier models |

## Gemini free-tier safeguards (`config/enrichment.yaml`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `free_tier_only` | `true` | Blocks Pro/preview models; uses AI Studio key only (not Maps key) |
| `model` | `gemini-2.0-flash-lite` | Highest free daily quota |
| `allowed_models` | flash + flash-lite only | Runtime whitelist |
| `max_gemini_calls_per_run` | 20 | Harbor/contractor research cap |
| `max_supply_chain_calls_per_run` | 5 | Supplier research cap |

**Never use paid models:** If you set `model: gemini-2.5-pro` with `free_tier_only: true`, the client auto-downgrades to `gemini-2.0-flash-lite`.

Create your key at [Google AI Studio](https://aistudio.google.com/apikey) **without** attaching a billing account to stay on the free tier.

## Recommended caps

| Setting | Default | Purpose |
|---------|---------|---------|
| max_places_calls_per_run | 40 | Pilot batches |
| max_fields_per_run | 20 | Batch size |
| max_companies_per_supply_chain_call | 6 | Batched supplier prompt |
| pilot_field_limit | 5 | First live test |

## Workflow

1. `estimate-enrichment` — preview calls for N fields
2. `enrich-all --dry-run` — no API calls, no DB writes
3. Pilot: `enrich-all --limit 5` — review Excel (3 sheets: Fields, Prospects, Supply_Chain)
4. Scale with daily caps until all fields enriched
5. `enrich-supply-chain --only-new` — supplier research for mooring companies

## Stop conditions

- Cap hit → re-run next batch (caches prevent re-billing)
- HTTP 429 → free-tier daily quota exhausted; retry tomorrow
- Quota exhausted → switch to `import-prospects --csv` manual path
- Set Google Cloud **$1 budget alert** on Maps APIs only

## Cost estimate formula

For N pending fields:

```
places_calls ≈ 2 × N   (nearby + details, minus cache hits)
gemini_calls ≈ 1 × N   (harbor/contractor research, minus cache)
supply_chain_calls ≈ ceil(prospects / 6)   (batched by harbor)
```

Cached responses reuse prior results at no additional cost.
