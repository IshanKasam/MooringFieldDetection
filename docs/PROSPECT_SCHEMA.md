# Prospect Schema

Database and Excel column definitions for the enrichment pipeline.

## Database tables

### `fields` (extended)

| Column | Type | Description |
|--------|------|-------------|
| enrichment_status | TEXT | `pending`, `places_done`, `researched`, `exported`, `skipped` |

### `prospects`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Canonical prospect id |
| canonical_business_name | TEXT | Marina/harbor operator name |
| phone | TEXT | Primary phone |
| email | TEXT | Contact email (only if sourced) |
| website | TEXT | Business website |
| address | TEXT | Formatted address |
| operator_type | TEXT | e.g. marina, yacht_club, harbor, town |
| place_id | TEXT | Google Places id |
| research_summary | TEXT | Gemini narrative summary |
| confidence | REAL | 0–1 combined confidence |
| sources | TEXT | JSON array of source strings/URLs |
| needs_review | INTEGER | 1 if human review required |
| approved | INTEGER | 1 if approved for export |
| raw_places_response | TEXT | JSON audit blob |
| raw_gemini_response | TEXT | JSON audit blob |
| created_at | TEXT | ISO timestamp |
| updated_at | TEXT | ISO timestamp |
| last_enriched | TEXT | ISO timestamp |

### `field_prospect_links`

| Column | Type | Description |
|--------|------|-------------|
| field_id | INTEGER FK | `fields.id` |
| prospect_id | INTEGER FK | `prospects.id` |

Many fields may link to one prospect after deduplication.

### `enrichment_runs`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Run id |
| started_at | TEXT | ISO timestamp |
| finished_at | TEXT | ISO timestamp |
| provider | TEXT | `live`, `mock`, `manual` |
| fields_processed | INTEGER | Count |
| places_calls | INTEGER | API calls made |
| gemini_calls | INTEGER | API calls made |
| cap_hit | INTEGER | 1 if stopped by cap |
| notes | TEXT | Free text |

## Excel export

### Sheet 1: Fields

One row per `fields` row.

| Column | Source |
|--------|--------|
| field_id | fields.id |
| scan_id | fields.scan_id |
| latitude | fields.latitude |
| longitude | fields.longitude |
| boat_count | fields.boat_count |
| mean_confidence | fields.mean_confidence |
| location_name | fields.location_name |
| country | fields.country |
| detection_weights | scans.weights |
| detection_date | scans.created_at |
| enriched_place_name | prospects.canonical_business_name |
| enrichment_status | fields.enrichment_status |
| prospect_id | field_prospect_links.prospect_id |
| needs_review | prospects.needs_review |

### Sheet 2: Prospects

One row per deduplicated `prospects` row.

| Column | Source |
|--------|--------|
| prospect_id | prospects.id |
| canonical_business_name | prospects |
| phone | prospects |
| email | prospects |
| website | prospects |
| address | prospects |
| operator_type | prospects |
| research_summary | prospects |
| confidence | prospects |
| sources | prospects (JSON string) |
| field_ids | comma-separated linked field ids |
| field_count | count of linked fields |
| needs_review | prospects |
| approved | prospects |
| last_enriched | prospects |
