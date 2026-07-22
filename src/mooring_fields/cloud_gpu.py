"""Pluggable cloud GPU adapter for coastal detect (P2).

Local CUDA remains the P1 default via ``scan_pipeline.run_scan_pipeline``.
This module defines the contract for Modal/RunPod/Kaggle-style workers that
accept a packaged scan payload and return a SQLite DB to import.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass
class CloudGpuJobSpec:
    """Inputs for an off-box YOLO detect job (fetch already done locally)."""

    payload_zip: Path
    source_label: str
    notes: str | None = None


@dataclass
class CloudGpuJobResult:
    status: str  # queued | running | succeeded | failed
    remote_id: str | None = None
    result_db: Path | None = None
    error: str | None = None
    raw: dict[str, Any] | None = None


class CloudGpuAdapter(Protocol):
    def submit(self, spec: CloudGpuJobSpec) -> CloudGpuJobResult: ...

    def poll(self, remote_id: str) -> CloudGpuJobResult: ...


class LocalPassthroughAdapter:
    """No remote GPU — documents the escape hatch (run detect on this host)."""

    def submit(self, spec: CloudGpuJobSpec) -> CloudGpuJobResult:
        return CloudGpuJobResult(
            status="failed",
            error=(
                "No cloud GPU configured. Run detect locally "
                "(CUDA preferred) or set MOORING_CLOUD_GPU=modal|runpod later."
            ),
            raw={"payload": str(spec.payload_zip)},
        )

    def poll(self, remote_id: str) -> CloudGpuJobResult:
        return CloudGpuJobResult(
            status="failed",
            remote_id=remote_id,
            error="No cloud GPU configured",
        )


def get_cloud_gpu_adapter() -> CloudGpuAdapter:
    """Factory — currently only local passthrough; Modal/RunPod plug in here."""
    import os

    backend = (os.environ.get("MOORING_CLOUD_GPU") or "local").strip().lower()
    if backend in ("", "local", "none"):
        return LocalPassthroughAdapter()
    # Future: return ModalAdapter() / RunPodAdapter()
    return LocalPassthroughAdapter()
