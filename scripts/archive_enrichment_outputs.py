"""Archive enrichment outputs to timestamped folder."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "enrichment_outputs" / "2026-06-15_live"


def main() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    copies = [
        (ROOT / "data/prospects_export.xlsx", ARCHIVE / "prospects_export.xlsx"),
        (ROOT / "data/fields_export.csv", ARCHIVE / "fields_export.csv"),
        (ROOT / "data/prospects_export.csv", ARCHIVE / "prospects_export.csv"),
        (ROOT / "data/places_cache.json", ARCHIVE / "places_cache.json"),
        (ROOT / "data/gemini_cache.json", ARCHIVE / "gemini_cache.json"),
        (ROOT / "data/enrichment_outputs/batch_reports.json", ARCHIVE / "batch_reports.json"),
        (
            ROOT / "data/enrichment_outputs/pilot/prospects_export.xlsx",
            ARCHIVE / "pilot_prospects_export.xlsx",
        ),
    ]
    for src, dest in copies:
        if src.exists():
            shutil.copy2(src, dest)

    conn = sqlite3.connect(ROOT / "data/mooring_fields.db")
    try:
        stats = {
            "fields_total": conn.execute("SELECT COUNT(*) FROM fields").fetchone()[0],
            "fields_exported": conn.execute(
                "SELECT COUNT(*) FROM fields WHERE enrichment_status = ?", ("exported",)
            ).fetchone()[0],
            "fields_skipped": conn.execute(
                "SELECT COUNT(*) FROM fields WHERE enrichment_status = ?", ("skipped",)
            ).fetchone()[0],
            "prospects": conn.execute("SELECT COUNT(*) FROM prospects").fetchone()[0],
            "needs_review": conn.execute(
                "SELECT COUNT(*) FROM prospects WHERE needs_review = 1"
            ).fetchone()[0],
            "approved": conn.execute(
                "SELECT COUNT(*) FROM prospects WHERE approved = 1"
            ).fetchone()[0],
            "enrichment_runs": conn.execute(
                "SELECT COUNT(*) FROM enrichment_runs"
            ).fetchone()[0],
        }
    finally:
        conn.close()

    summary = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "live",
        "gemini_note": (
            "Generative Language API not enabled; Places-only fallback used (needs_review=true)"
        ),
        "stats": stats,
        "archive": str(ARCHIVE),
    }
    (ARCHIVE / "enrichment_report.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    (ARCHIVE / "README.txt").write_text(
        "Live enrichment run 2026-06-15\n"
        f"Fields: {stats['fields_total']} total, {stats['fields_exported']} exported, "
        f"{stats['fields_skipped']} skipped (no nearby marina)\n"
        f"Prospects: {stats['prospects']} deduplicated, {stats['needs_review']} need review\n"
        "Deliverable: prospects_export.xlsx (Fields + Prospects sheets)\n"
        "To add Gemini research: enable Generative Language API in Google Cloud, "
        "add GEMINI_API_KEY to .env, then run enrich-research.\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
