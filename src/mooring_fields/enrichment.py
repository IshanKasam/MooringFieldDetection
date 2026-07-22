"""Orchestration for Places + Gemini enrichment pipeline."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from mooring_fields.database import (
    finish_enrichment_run,
    get_connection,
    get_fields_for_research,
    get_prospects_for_supply_chain,
    get_unenriched_fields,
    init_db,
    link_field_to_prospect,
    set_field_enrichment_status,
    start_enrichment_run,
    update_prospect_supply_chain,
    upsert_prospect,
)
from mooring_fields.dedupe_prospects import dedupe_prospects
from mooring_fields.enrichment_config import estimate_enrichment, load_enrichment_config
from mooring_fields.enrichment_providers import (
    get_places_provider,
    get_research_provider,
)
from mooring_fields.export_excel import export_prospects
from mooring_fields.paths import DB_PATH, PROSPECTS_EXPORT


def _row_to_dict(row) -> dict[str, Any]:
    return dict(row)


def enrich_places(
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
    only_new: bool = False,
    include_skipped: bool = False,
    limit: int | None = None,
    csv_path: Path | None = None,
) -> dict[str, Any]:
    cfg = load_enrichment_config()
    max_fields = limit or cfg.get("max_fields_per_run", 20)
    max_calls = cfg.get("max_places_calls_per_run", 20)

    conn = get_connection(db_path)
    try:
        init_db(conn)
        fields = get_unenriched_fields(
            conn, only_new=only_new, include_skipped=include_skipped, limit=max_fields
        )
        if dry_run:
            return {
                "dry_run": True,
                "fields_would_process": len(fields),
                "estimate": estimate_enrichment(len(fields), db_path=db_path),
            }

        provider = get_places_provider(cfg, csv_path=csv_path)
        run_id = start_enrichment_run(conn, cfg.get("provider", "mock"))
        processed = 0
        cap_hit = False

        for row in fields:
            if getattr(provider, "calls_made", 0) >= max_calls:
                cap_hit = True
                break
            field = _row_to_dict(row)
            fid = int(field["id"])
            place = provider.lookup(
                float(field["latitude"]), float(field["longitude"]), fid
            )
            if place is None:
                prospect_id = upsert_prospect(
                    conn,
                    {
                        "canonical_business_name": field.get("location_name")
                        or f"Mooring field {fid}",
                        "address": field.get("location_name"),
                        "operator_type": "mooring_field",
                        "needs_review": True,
                    },
                )
                link_field_to_prospect(conn, fid, prospect_id)
                set_field_enrichment_status(conn, fid, "places_done")
                processed += 1
                continue

            prospect_id = upsert_prospect(
                conn,
                {
                    "canonical_business_name": place.name,
                    "phone": place.phone,
                    "website": place.website,
                    "address": place.address,
                    "operator_type": ",".join(place.types[:3]) if place.types else "marina",
                    "place_id": place.place_id,
                    "raw_places_response": json.dumps(place.raw),
                    "needs_review": True,
                },
            )
            link_field_to_prospect(conn, fid, prospect_id)
            set_field_enrichment_status(conn, fid, "places_done")
            processed += 1

        places_calls = getattr(provider, "calls_made", 0)
        finish_enrichment_run(
            conn,
            run_id,
            fields_processed=processed,
            places_calls=places_calls,
            gemini_calls=0,
            cap_hit=cap_hit,
        )
        return {
            "fields_processed": processed,
            "places_calls": places_calls,
            "cap_hit": cap_hit,
            "run_id": run_id,
        }
    finally:
        conn.close()


def enrich_research(
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
    only_new: bool = False,
    limit: int | None = None,
    csv_path: Path | None = None,
) -> dict[str, Any]:
    cfg = load_enrichment_config()
    max_fields = limit or cfg.get("max_fields_per_run", 20)
    max_calls = cfg.get("max_gemini_calls_per_run", 20)

    conn = get_connection(db_path)
    try:
        init_db(conn)
        fields = get_fields_for_research(conn, only_new=only_new, limit=max_fields)
        if dry_run:
            return {
                "dry_run": True,
                "fields_would_process": len(fields),
                "estimate": estimate_enrichment(0, db_path=db_path),
            }

        provider = get_research_provider(cfg, csv_path=csv_path)
        run_id = start_enrichment_run(conn, cfg.get("provider", "mock"))
        processed = 0
        cap_hit = False

        for row in fields:
            if getattr(provider, "calls_made", 0) >= max_calls:
                cap_hit = True
                break
            field = _row_to_dict(row)
            fid = int(field["id"])
            prospect_id = int(field["prospect_id"])
            from mooring_fields.enrichment_providers import PlaceResult

            place = PlaceResult(
                place_id=field.get("place_id"),
                name=field.get("place_name"),
                address=field.get("place_address"),
                phone=field.get("place_phone"),
                website=field.get("place_website"),
                types=(field.get("place_types") or "").split(","),
                raw={},
            )
            has_places_poi = bool(field.get("place_id"))
            result = provider.research(field, place if has_places_poi else None)
            upsert_prospect(
                conn,
                {
                    "canonical_business_name": result.canonical_business_name,
                    "phone": result.phone,
                    "email": result.email,
                    "website": result.website,
                    "operator_type": result.operator_type,
                    "research_summary": result.research_summary,
                    "confidence": result.confidence,
                    "sources": result.sources,
                    "needs_review": result.needs_review,
                    "harbor_name": result.harbor_name,
                    "raw_gemini_response": json.dumps(result.raw),
                },
                prospect_id=prospect_id,
            )
            for extra in result.additional_prospects or []:
                extra_id = upsert_prospect(
                    conn,
                    {
                        **extra,
                        "harbor_name": result.harbor_name,
                        "raw_gemini_response": json.dumps(result.raw),
                    },
                )
                link_field_to_prospect(conn, fid, extra_id)
            set_field_enrichment_status(conn, fid, "researched")
            processed += 1

        gemini_calls = getattr(provider, "calls_made", 0)
        finish_enrichment_run(
            conn,
            run_id,
            fields_processed=processed,
            places_calls=0,
            gemini_calls=gemini_calls,
            cap_hit=cap_hit,
        )
        return {
            "fields_processed": processed,
            "gemini_calls": gemini_calls,
            "cap_hit": cap_hit,
            "run_id": run_id,
        }
    finally:
        conn.close()


def run_dedupe(*, db_path: Path | None = None) -> dict:
    cfg = load_enrichment_config()
    conn = get_connection(db_path)
    try:
        init_db(conn)
        return dedupe_prospects(
            conn, proximity_meters=float(cfg.get("dedupe_proximity_meters", 200))
        )
    finally:
        conn.close()


def enrich_supply_chain(
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
    only_new: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """Research upstream suppliers for mooring service companies (batched by harbor)."""
    cfg = load_enrichment_config()
    max_calls = cfg.get("max_supply_chain_calls_per_run", 5)
    batch_size = int(cfg.get("max_companies_per_supply_chain_call", 6))

    conn = get_connection(db_path)
    try:
        init_db(conn)
        prospects = get_prospects_for_supply_chain(
            conn, only_new=only_new, limit=limit or batch_size * max_calls
        )
        if dry_run:
            return {
                "dry_run": True,
                "prospects_would_process": len(prospects),
                "estimated_batches": max(1, (len(prospects) + batch_size - 1) // batch_size),
            }

        from mooring_fields.gemini_supply_chain import (
            extract_harbor_from_prospect,
            format_supply_chain_summary,
            get_supply_chain_provider,
        )

        provider = get_supply_chain_provider(cfg)
        run_id = start_enrichment_run(conn, cfg.get("provider", "mock"))
        processed = 0
        batches_run = 0
        cap_hit = False

        # Group by harbor for contextual batch prompts (MF 50-52 style).
        harbor_groups: dict[str, list[dict[str, Any]]] = {}
        for row in prospects:
            harbor = extract_harbor_from_prospect(row) or "unknown"
            harbor_groups.setdefault(harbor, []).append(row)

        pending_batches: list[list[dict[str, Any]]] = []
        for group in harbor_groups.values():
            for i in range(0, len(group), batch_size):
                pending_batches.append(group[i : i + batch_size])

        for batch in pending_batches:
            if batches_run >= max_calls:
                cap_hit = True
                break
            payload = []
            for row in batch:
                payload.append(
                    {
                        "prospect_id": int(row["id"]),
                        "canonical_business_name": row["canonical_business_name"],
                        "harbor_name": extract_harbor_from_prospect(row),
                        "website": row.get("website"),
                        "field_ids": row.get("field_ids"),
                        "research_summary": row.get("research_summary"),
                    }
                )
            results = provider.research_batch(payload)
            batches_run += 1
            for result in results:
                if not result.prospect_id:
                    continue
                summary = format_supply_chain_summary(result)
                # Do not mark hard LLM failures as done — only_new would skip retries.
                if (result.company_summary or "").startswith(
                    "Supply chain research unavailable"
                ):
                    continue
                update_prospect_supply_chain(
                    conn,
                    int(result.prospect_id),
                    result.to_dict(),
                    summary,
                )
                processed += 1

        gemini_calls = getattr(provider, "calls_made", 0)
        finish_enrichment_run(
            conn,
            run_id,
            fields_processed=processed,
            places_calls=0,
            gemini_calls=gemini_calls,
            cap_hit=cap_hit,
            notes="supply_chain",
        )
        return {
            "prospects_processed": processed,
            "batches_run": batches_run,
            "gemini_calls": gemini_calls,
            "cap_hit": cap_hit,
            "run_id": run_id,
        }
    finally:
        conn.close()


def enrich_all(
    *,
    db_path: Path | None = None,
    dry_run: bool = False,
    only_new: bool = False,
    include_skipped: bool = False,
    limit: int | None = None,
    export_path: Path | None = None,
    csv_path: Path | None = None,
) -> dict[str, Any]:
    cfg = load_enrichment_config()
    if dry_run:
        n = limit or cfg.get("max_fields_per_run", 20)
        return {
            "dry_run": True,
            "estimate": estimate_enrichment(n, db_path=db_path, only_new=only_new),
        }

    report: dict[str, Any] = {"steps": []}
    report["steps"].append(
        enrich_places(
            db_path=db_path,
            only_new=only_new,
            include_skipped=include_skipped,
            limit=limit,
            csv_path=csv_path,
        )
    )
    report["steps"].append(
        enrich_research(
            db_path=db_path,
            only_new=only_new,
            limit=limit,
            csv_path=csv_path,
        )
    )
    report["dedupe"] = run_dedupe(db_path=db_path)
    report["steps"].append(
        enrich_supply_chain(db_path=db_path, only_new=True, limit=limit)
    )
    out = export_path or Path(cfg.get("export_path", str(PROSPECTS_EXPORT)))
    report["export"] = export_prospects(
        out,
        db_path=db_path,
        min_boat_count=int(cfg.get("min_boat_count", 0)),
        min_confidence=float(cfg.get("min_confidence", 0.0)),
        only_approved=bool(cfg.get("only_approved", False)),
    )

    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE fields SET enrichment_status = 'exported' "
            "WHERE enrichment_status = 'researched'"
        )
        conn.commit()
    finally:
        conn.close()

    return report


def import_prospects_csv(csv_path: Path, *, db_path: Path | None = None) -> dict:
    """Import manual prospect corrections from CSV."""
    conn = get_connection(db_path)
    try:
        init_db(conn)
        updated = 0
        with csv_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                pid = row.get("prospect_id")
                if not pid:
                    continue
                sources = row.get("sources", "")
                upsert_prospect(
                    conn,
                    {
                        "canonical_business_name": row.get("canonical_business_name"),
                        "phone": row.get("phone"),
                        "email": row.get("email"),
                        "website": row.get("website"),
                        "address": row.get("address"),
                        "operator_type": row.get("operator_type"),
                        "research_summary": row.get("research_summary"),
                        "confidence": float(row["confidence"]) if row.get("confidence") else None,
                        "sources": [s.strip() for s in sources.split(";") if s.strip()],
                        "needs_review": row.get("needs_review", "").lower()
                        in ("1", "true", "yes"),
                        "approved": row.get("approved", "").lower() in ("1", "true", "yes"),
                    },
                    prospect_id=int(pid),
                )
                updated += 1
        return {"prospects_updated": updated}
    finally:
        conn.close()


def query_fields(
    *,
    db_path: Path | None = None,
    fmt: str = "json",
    only_new: bool = False,
) -> Any:
    conn = get_connection(db_path)
    try:
        init_db(conn)
        from mooring_fields.database import list_fields

        rows = list_fields(conn, only_new=only_new)
        data = [dict(r) for r in rows]
    finally:
        conn.close()

    if fmt == "csv":
        import io

        if not data:
            return ""
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=data[0].keys())
        w.writeheader()
        w.writerows(data)
        return buf.getvalue()
    return data
