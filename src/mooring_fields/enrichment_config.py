"""Load enrichment configuration and estimate API usage."""

from __future__ import annotations

from pathlib import Path

import yaml

from mooring_fields.database import get_connection, get_unenriched_fields, init_db
from mooring_fields.paths import CONFIG_DIR, DB_PATH


def load_enrichment_config() -> dict:
    path = CONFIG_DIR / "enrichment.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def count_pending_fields(db_path: Path | None = None, only_new: bool = False) -> int:
    conn = get_connection(db_path)
    try:
        init_db(conn)
        return len(get_unenriched_fields(conn, only_new=only_new))
    finally:
        conn.close()


def estimate_enrichment(
    n_fields: int | None = None,
    *,
    db_path: Path | None = None,
    only_new: bool = False,
) -> dict:
    """Estimate Places + Gemini API calls for enrichment."""
    cfg = load_enrichment_config()
    if n_fields is None:
        n_fields = count_pending_fields(db_path, only_new=only_new)

    n_fields = min(n_fields, cfg.get("max_fields_per_run", 20))

    places_per_field = 2  # nearby + details
    gemini_per_field = 1

    return {
        "pending_fields": count_pending_fields(db_path, only_new=only_new),
        "fields_to_process": n_fields,
        "estimated_places_calls": places_per_field * n_fields,
        "estimated_gemini_calls": gemini_per_field * n_fields,
        "max_places_calls_per_run": cfg.get("max_places_calls_per_run", 20),
        "max_gemini_calls_per_run": cfg.get("max_gemini_calls_per_run", 20),
        "provider": cfg.get("provider", "mock"),
        "within_caps": (
            places_per_field * n_fields <= cfg.get("max_places_calls_per_run", 20)
            and gemini_per_field * n_fields <= cfg.get("max_gemini_calls_per_run", 20)
        ),
        "estimated_cost_usd": 0.0,
        "note": "Stay within Google Maps $200/mo credit and Gemini free tier; set quota caps in Cloud Console.",
    }
