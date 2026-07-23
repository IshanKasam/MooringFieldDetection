"""Background jobs triggered from the web UI (enrich + scan)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def run_enrichment_job(
    step: str,
    *,
    limit: int | None = 5,
    only_new: bool = True,
) -> dict[str, Any]:
    """Run one enrichment step (or all). Intended for BackgroundTasks."""
    from mooring_fields.database import (
        finish_enrichment_run,
        get_connection,
        init_db,
        start_enrichment_run,
    )
    from mooring_fields.enrichment import (
        enrich_all,
        enrich_places,
        enrich_research,
        enrich_supply_chain,
    )
    from mooring_fields.enrichment_config import load_enrichment_config

    step = (step or "research").lower().strip()
    try:
        if step == "places":
            return enrich_places(limit=limit, only_new=only_new)
        if step == "research":
            return enrich_research(limit=limit, only_new=only_new)
        if step in ("supply_chain", "supply-chain"):
            return enrich_supply_chain(limit=limit, only_new=only_new)
        if step == "all":
            return enrich_all(limit=limit, only_new=only_new)
        return {"error": f"unknown step: {step}"}
    except Exception as exc:  # noqa: BLE001
        log.exception("enrichment job failed")
        err = str(exc)
        try:
            cfg = load_enrichment_config()
            if step == "places":
                label = str(cfg.get("provider", "mock"))
            else:
                label = str(cfg.get("research_provider") or cfg.get("provider", "mock"))
            conn = get_connection()
            try:
                init_db(conn)
                run_id = start_enrichment_run(conn, label)
                finish_enrichment_run(
                    conn,
                    run_id,
                    fields_processed=0,
                    places_calls=0,
                    gemini_calls=0,
                    notes=f"ERROR step={step}: {err}",
                )
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            log.exception("failed to persist enrichment error run")
        return {"error": err, "step": step}


def run_scan_job(job_id: int) -> dict[str, Any]:
    """Execute a queued scan job (candidates → fetch → detect → DB)."""
    from mooring_fields.database import get_connection, init_db
    from mooring_fields.jobs_store import (
        add_maps_quota_usage,
        finish_job,
        get_job,
        job_cancel_requested,
        mark_job_running,
        update_job_progress,
    )
    from mooring_fields.scan_pipeline import generate_region_kml, run_scan_pipeline

    conn = get_connection()
    try:
        init_db(conn)
        job = get_job(conn, job_id)
        if job is None:
            return {"error": "job not found"}
        params = job.get("params") or {}
        mark_job_running(conn, job_id)

        def cancel_check() -> bool:
            c = get_connection()
            try:
                init_db(c)
                return job_cancel_requested(c, job_id)
            finally:
                c.close()

        def on_progress(payload: dict[str, Any]) -> None:
            c = get_connection()
            try:
                init_db(c)
                update_job_progress(c, job_id, payload)
                if payload.get("step") == "fetch_done":
                    add_maps_quota_usage(c, int(payload.get("maps_used") or 0))
            finally:
                c.close()

        region = params.get("region")
        state = params.get("state")
        bbox = params.get("bbox")
        max_sites = int(params.get("max_sites") or 160)
        max_requests = params.get("max_requests")
        skip_fetch = bool(params.get("skip_fetch"))
        kml_path = params.get("kml_path")

        if not kml_path:
            on_progress({"step": "generate_candidates", "region": region or state})
            gen = generate_region_kml(
                region=region,
                state=state,
                bbox=bbox,
                max_sites=max_sites,
                offset=int(params.get("offset") or 0),
            )
            kml_path = gen["out"]
            on_progress({"step": "candidates_ready", "sites": gen["sites"], "kml": kml_path})

        if cancel_check():
            finish_job(conn, job_id, status="cancelled", result={"cancelled": True})
            return {"cancelled": True}

        result = run_scan_pipeline(
            kml_path=Path(kml_path),
            max_requests=int(max_requests) if max_requests is not None else None,
            skip_fetch=skip_fetch,
            cancel_check=cancel_check,
            on_progress=on_progress,
        )
        status = "cancelled" if result.get("cancelled") else "succeeded"
        finish_job(conn, job_id, status=status, result=result)
        return result
    except Exception as exc:  # noqa: BLE001
        log.exception("scan job failed")
        try:
            finish_job(conn, job_id, status="failed", result={"error": str(exc)})
        except Exception:  # noqa: BLE001
            log.exception("failed to mark scan job failed")
        return {"error": str(exc)}
    finally:
        conn.close()


def run_refilter_job(
    *,
    scan_id: int | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Run dock/marina refilter. Intended for BackgroundTasks."""
    try:
        from mooring_fields.web.service import refilter_docks

        return refilter_docks(scan_id=scan_id, dry_run=dry_run, limit=limit)
    except Exception as exc:  # noqa: BLE001
        log.exception("refilter job failed")
        return {"error": str(exc)}
