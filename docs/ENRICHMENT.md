# Enrichment Pipeline

Build a customer/prospect list from detected mooring fields using Places + Gemini, then export dual-sheet Excel.

Detection and enrichment are **decoupled** — enrichment reads from `mooring_fields.db` only. When you improve `best.pt` later, re-run `evaluate` and `enrich-all --only-new`.

See also: [PROSPECT_SCHEMA.md](PROSPECT_SCHEMA.md), [ENRICHMENT_BUDGET.md](ENRICHMENT_BUDGET.md), [GEMINI_PROMPTS.md](GEMINI_PROMPTS.md), [ADR-002](decisions/ADR-002-enrichment-architecture.md).

## Prerequisites

```bash
pip install -e ".[dev,enrichment]"
```

Set in `.env`:

```
GOOGLE_MAPS_API_KEY=your_key
GEMINI_API_KEY=your_gemini_key
```

For offline development, keep `provider: mock` in `config/enrichment.yaml` (default).

## Workflow

### 1. Estimate cost (free tier)

```bash
python -m mooring_fields.cli estimate-enrichment
python -m mooring_fields.cli enrich-all --dry-run
```

### 2. Query current fields

```bash
python -m mooring_fields.cli query-fields
python -m mooring_fields.cli query-fields --format csv > fields.csv
```

### 3. Run enrichment (mock by default)

```bash
python -m mooring_fields.cli enrich-all --limit 5
```

Produces `data/prospects_export.xlsx` with **Fields** and **Prospects** sheets.

### 4. Live APIs (pilot first)

Edit `config/enrichment.yaml`:

```yaml
provider: live
```

Enable Places API + Geocoding in Google Cloud. Set quota caps per [ENRICHMENT_BUDGET.md](ENRICHMENT_BUDGET.md).

```bash
python -m mooring_fields.cli enrich-all --limit 5
```

### 5. Human review

- Open Excel; filter `needs_review = 1`
- Edit and re-import:

```bash
python -m mooring_fields.cli import-prospects --csv corrections.csv
python -m mooring_fields.cli approve-prospect --id 3
python -m mooring_fields.cli export-prospects
```

### 6. Manual CSV path (zero API)

Set `provider: manual` and pass `--csv` with place/research columns.

## Commands

| Command | Purpose |
|---------|---------|
| `query-fields` | List fields from DB |
| `estimate-enrichment` | Preview API call counts |
| `enrich-places` | Places lookup step only |
| `enrich-research` | Gemini research step only |
| `dedupe-prospects` | Merge duplicate businesses |
| `export-prospects` | Excel + CSV export |
| `import-prospects` | CSV corrections |
| `approve-prospect` | Mark prospect approved |
| `enrich-all` | Full pipeline |
| `diff-scans` | Compare two detection scans |

## When a better model is ready

1. Replace `runs/mooring_boats/weights/best.pt`
2. `python -m mooring_fields.cli evaluate`
3. `python -m mooring_fields.cli enrich-all --only-new`
4. `python -m mooring_fields.cli export-prospects`
5. Optional: `python -m mooring_fields.cli diff-scans 1 2`

## Compliance

Use API data per Google and Gemini terms. Verify contact info before outreach. See CAN-SPAM for email campaigns.
