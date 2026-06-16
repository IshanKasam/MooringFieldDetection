# ADR-002: Enrichment Pipeline Architecture

## Status

Accepted

## Date

2026-06-15

## Context

Detection produces mooring field clusters (lat/lon, boat counts) stored in SQLite. The product goal is a **customer/prospect list** exported to Excel: one sheet per detected field and one deduplicated sheet per business/operator.

Enrichment uses Google Places API and Gemini API. Detection quality will improve later; enrichment must not depend on the model directly.

## Decision

1. **Decouple enrichment from detection.** Enrichment reads only from `mooring_fields.db` (`fields`, `boats`, `scans`). Swapping `best.pt` and re-running `evaluate`/`scan` appends new rows; `enrich --only-new` processes unlinked fields only.

2. **Adapter pattern for providers.** `PlacesProvider` and `ResearchProvider` protocols with `live`, `mock`, and `manual` implementations wired via `config/enrichment.yaml`.

3. **Cost safety mirrors imagery fetch.** `estimate-enrichment`, per-run caps, on-disk caches (`places_cache.json`, `gemini_cache.json`), `--dry-run` default off but available.

4. **Dual export.** Single `.xlsx` with **Fields** and **Prospects** sheets; CSV pair for non-Excel users.

5. **Human QA loop.** `needs_review` and `approved` flags; `import-prospects --csv` for manual corrections.

## Model plug-in contract

1. Replace `runs/mooring_boats/weights/best.pt`
2. Run `python -m mooring_fields.cli evaluate` (and/or `scan`)
3. Run `python -m mooring_fields.cli enrich-all --only-new`
4. Re-export; compare scans via `diff-scans` if needed

Detection version is tracked in `scans.weights` and `scans.created_at`.

## Consequences

- Places + Gemini modules are new; no changes to cluster_fields or train_boats when model improves
- Free-tier caps required before batch enrichment
- False-positive fields from low hit-rate model flow through with `needs_review=true`

## References

- [PROSPECT_SCHEMA.md](../PROSPECT_SCHEMA.md)
- [ENRICHMENT_BUDGET.md](../ENRICHMENT_BUDGET.md)
- [GEMINI_PROMPTS.md](../GEMINI_PROMPTS.md)
