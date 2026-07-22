"""Pydantic request/response models for the web API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Stats(BaseModel):
    fields: int
    boats: int
    prospects: int
    needs_review: int
    approved: int


class FieldRow(BaseModel):
    field_id: int
    latitude: float
    longitude: float
    boat_count: int
    mean_confidence: float | None = None
    location_name: str | None = None
    state: str | None = None
    country: str | None = None
    enrichment_status: str | None = None
    scan_id: int | None = None
    detection_date: str | None = None
    prospect_id: int | None = None
    controller: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    address: str | None = None
    harbor_name: str | None = None
    operator_type: str | None = None
    confidence: float | None = None
    sources: str | None = None
    research_summary: str | None = None
    supply_chain_summary: str | None = None
    needs_review: int | None = None
    approved: int | None = None


class BoatPoint(BaseModel):
    id: int
    scan_id: int
    field_id: int | None = None
    latitude: float
    longitude: float
    confidence: float | None = None
    image_stem: str | None = None


class ProspectSummary(BaseModel):
    prospect_id: int
    canonical_business_name: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    address: str | None = None
    operator_type: str | None = None
    harbor_name: str | None = None
    research_summary: str | None = None
    supply_chain_summary: str | None = None
    confidence: float | None = None
    sources: Any = None
    field_ids: str | None = None
    field_count: int = 0
    needs_review: int | None = None
    approved: int | None = None
    last_enriched: str | None = None


class ProspectDetail(BaseModel):
    prospect_id: int
    canonical_business_name: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    address: str | None = None
    operator_type: str | None = None
    harbor_name: str | None = None
    research_summary: str | None = None
    supply_chain_summary: str | None = None
    supply_chain_json: Any = None
    confidence: float | None = None
    sources: Any = None
    needs_review: int | None = None
    approved: int | None = None
    last_enriched: str | None = None
    field_ids: list[int] = Field(default_factory=list)


class ProspectUpdate(BaseModel):
    canonical_business_name: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    address: str | None = None
    operator_type: str | None = None
    harbor_name: str | None = None
    research_summary: str | None = None
    needs_review: bool | None = None
    approved: bool | None = None


class ApproveRequest(BaseModel):
    approved: bool = True


class ScanRow(BaseModel):
    id: int
    created_at: str | None = None
    source: str | None = None
    weights: str | None = None
    split: str | None = None
    notes: str | None = None
    field_count: int = 0


class ScanDiff(BaseModel):
    scan_a: int
    scan_b: int
    fields_a: int
    fields_b: int
    delta: int


class EnrichRequest(BaseModel):
    step: str = Field(
        default="research",
        description="places | research | supply_chain | all",
    )
    limit: int | None = 5
    only_new: bool = True


class EnrichRun(BaseModel):
    id: int
    started_at: str | None = None
    finished_at: str | None = None
    provider: str | None = None
    fields_processed: int = 0
    places_calls: int = 0
    gemini_calls: int = 0
    cap_hit: int = 0
    notes: str | None = None


class OkResponse(BaseModel):
    ok: bool = True
    detail: Any = None


class ScanJobRequest(BaseModel):
    region: str | None = None
    state: str | None = None
    bbox: str | None = None
    max_sites: int = Field(default=160, ge=1, le=160)
    max_requests: int | None = Field(default=None, ge=1, le=800)
    offset: int = Field(default=0, ge=0)
    skip_fetch: bool = False
    kml_path: str | None = None


class JobRow(BaseModel):
    id: int
    kind: str
    status: str
    params: Any = None
    progress: Any = None
    result: Any = None
    cancel_requested: bool = False
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class MapsQuota(BaseModel):
    day: str
    maps_used: int
    cap: int
    remaining: int


class ScanRegion(BaseModel):
    id: str
    kind: str
    bbox: list[float]
