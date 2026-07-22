"""FastAPI application: thin HTTP layer over mooring_fields.database."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from mooring_fields.web import service
from mooring_fields.web.jobs import run_enrichment_job, run_scan_job
from mooring_fields.web.schemas import (
    ApproveRequest,
    BoatPoint,
    EnrichRequest,
    EnrichRun,
    FieldRow,
    JobRow,
    MapsQuota,
    OkResponse,
    ProspectDetail,
    ProspectSummary,
    ProspectUpdate,
    ScanDiff,
    ScanJobRequest,
    ScanRegion,
    ScanRow,
    Stats,
)

app = FastAPI(
    title="Mooring Field Detection",
    description="Map + spreadsheet UI over detection and enrichment data.",
    version="0.1.0",
)

_cors_origins = [
    o.strip()
    for o in os.environ.get(
        "MOORING_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]
if os.environ.get("MOORING_CORS_ALLOW_ALL", "").lower() in ("1", "true"):
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/stats", response_model=Stats)
def api_stats() -> Stats:
    return Stats(**service.stats())


@app.get("/api/table", response_model=list[FieldRow])
def api_table() -> list[FieldRow]:
    return [FieldRow(**row) for row in service.table_rows()]


@app.get("/api/fields.geojson")
def api_fields_geojson() -> dict[str, Any]:
    return service.fields_geojson()


@app.get("/api/boats", response_model=list[BoatPoint])
def api_boats(
    field_id: int | None = None,
    scan_id: int | None = None,
    limit: int = Query(5000, ge=1, le=50000),
) -> list[BoatPoint]:
    return [
        BoatPoint(**row)
        for row in service.boats(field_id=field_id, scan_id=scan_id, limit=limit)
    ]


@app.get("/api/prospects", response_model=list[ProspectSummary])
def api_prospects() -> list[ProspectSummary]:
    return [ProspectSummary(**row) for row in service.prospects()]


@app.get("/api/prospects/{prospect_id}", response_model=ProspectDetail)
def api_prospect_detail(prospect_id: int) -> ProspectDetail:
    detail = service.prospect_detail(prospect_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="prospect not found")
    return ProspectDetail(**detail)


@app.patch("/api/prospects/{prospect_id}", response_model=ProspectDetail)
def api_prospect_update(prospect_id: int, body: ProspectUpdate) -> ProspectDetail:
    updated = service.update_prospect(prospect_id, body.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="prospect not found")
    return ProspectDetail(**updated)


@app.post("/api/prospects/{prospect_id}/approve", response_model=OkResponse)
def api_prospect_approve(prospect_id: int, body: ApproveRequest) -> OkResponse:
    ok = service.set_approved(prospect_id, body.approved)
    if not ok:
        raise HTTPException(status_code=404, detail="prospect not found")
    return OkResponse(ok=True, detail={"prospect_id": prospect_id, "approved": body.approved})


@app.get("/api/export.xlsx")
def api_export() -> FileResponse:
    path = service.build_export()
    if not path.exists():
        raise HTTPException(status_code=500, detail="export failed")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


@app.get("/api/scans", response_model=list[ScanRow])
def api_scans() -> list[ScanRow]:
    return [ScanRow(**row) for row in service.scans()]


@app.get("/api/scans/diff", response_model=ScanDiff)
def api_scan_diff(
    a: int = Query(..., description="scan_id A"),
    b: int = Query(..., description="scan_id B"),
) -> ScanDiff:
    return ScanDiff(**service.scan_diff(a, b))


@app.post("/api/enrich", response_model=OkResponse)
def api_enrich(body: EnrichRequest, background: BackgroundTasks) -> OkResponse:
    background.add_task(
        run_enrichment_job,
        body.step,
        limit=body.limit,
        only_new=body.only_new,
    )
    return OkResponse(
        ok=True,
        detail={"queued": True, "step": body.step, "limit": body.limit},
    )


@app.get("/api/enrich/runs", response_model=list[EnrichRun])
def api_enrich_runs(limit: int = Query(20, ge=1, le=100)) -> list[EnrichRun]:
    return [EnrichRun(**row) for row in service.enrichment_runs(limit=limit)]


@app.get("/api/regions", response_model=list[ScanRegion])
def api_regions() -> list[ScanRegion]:
    return [ScanRegion(**r) for r in service.scan_regions()]


@app.get("/api/quota/maps", response_model=MapsQuota)
def api_maps_quota() -> MapsQuota:
    return MapsQuota(**service.maps_quota())


@app.get("/api/jobs", response_model=list[JobRow])
def api_jobs(
    kind: str | None = None,
    limit: int = Query(20, ge=1, le=100),
) -> list[JobRow]:
    return [JobRow(**row) for row in service.list_jobs(kind=kind, limit=limit)]


@app.get("/api/jobs/{job_id}", response_model=JobRow)
def api_job(job_id: int) -> JobRow:
    row = service.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobRow(**row)


@app.post("/api/jobs/{job_id}/cancel", response_model=OkResponse)
def api_job_cancel(job_id: int) -> OkResponse:
    ok = service.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found or not cancellable")
    return OkResponse(ok=True, detail={"job_id": job_id, "cancel_requested": True})


@app.post("/api/jobs/scan", response_model=OkResponse)
def api_jobs_scan(body: ScanJobRequest, background: BackgroundTasks) -> OkResponse:
    if not body.region and not body.state and not body.bbox and not body.kml_path:
        raise HTTPException(
            status_code=400,
            detail="Provide region, state, bbox, or kml_path",
        )
    try:
        job_id = service.enqueue_scan_job(body.model_dump(exclude_none=True))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background.add_task(run_scan_job, job_id)
    return OkResponse(ok=True, detail={"queued": True, "job_id": job_id})


def create_app() -> FastAPI:
    return app


def run() -> None:
    """Console entrypoint: ``mooring-web``."""
    import uvicorn

    host = os.environ.get("MOORING_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("MOORING_WEB_PORT", "8000"))
    static_dir = Path(__file__).resolve().parents[3] / "web-ui" / "dist"
    if static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")

    uvicorn.run(
        "mooring_fields.web.api:app",
        host=host,
        port=port,
        reload=os.environ.get("MOORING_WEB_RELOAD", "").lower() in ("1", "true"),
    )


if __name__ == "__main__":
    run()


# Allow ``python -m mooring_fields.web.api``
