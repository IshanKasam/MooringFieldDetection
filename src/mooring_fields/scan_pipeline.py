"""Callable scan pipeline used by CLI and in-app jobs."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from mooring_fields.paths import DB_PATH, IMAGERY_DIR


ProgressCb = Callable[[dict[str, Any]], None]


def run_scan_pipeline(
    *,
    kml_path: Path,
    output_dir: Path | None = None,
    weights: Path | None = None,
    max_requests: int | None = None,
    skip_fetch: bool = False,
    db_path: Path | None = None,
    imagery_dir: Path | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """Fetch (optional) + detect + persist scan results. Returns a summary dict."""
    from mooring_fields.cluster_fields import run_on_split
    from mooring_fields.database import save_scan
    from mooring_fields.fetch_imagery import fetch_all as _fetch_all
    from mooring_fields.geocode import Geocoder
    from mooring_fields.kml import clusters_to_kml, load_sites_json, run_parse_and_split

    load_dotenv()
    kml_path = Path(kml_path)
    if not kml_path.is_file():
        raise FileNotFoundError(f"KML file not found: {kml_path}")

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key and not skip_fetch:
        raise EnvironmentError(
            "GOOGLE_MAPS_API_KEY is not set (or use skip_fetch if imagery exists)"
        )

    out = Path(output_dir) if output_dir else Path("./scan_results")
    out.mkdir(parents=True, exist_ok=True)
    imagery_base = Path(imagery_dir) if imagery_dir else IMAGERY_DIR
    imagery_base.mkdir(parents=True, exist_ok=True)

    def _progress(step: str, **extra: Any) -> None:
        if on_progress:
            on_progress({"step": step, **extra})

    def _cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    tmp_dir = Path(tempfile.mkdtemp(prefix="mooring_scan_"))
    try:
        _progress("parse_kml")
        run_parse_and_split(kml_path=kml_path, output_dir=tmp_dir)
        scan_sites = load_sites_json(path=tmp_dir / "sites.json")
        _progress(
            "sites_ready",
            sites=len(scan_sites),
            planned_tiles=len(scan_sites) * 5,
        )
        if _cancelled():
            return {"cancelled": True, "step": "parse_kml"}

        fetch_result: dict[str, Any] = {}
        if not skip_fetch:
            _progress("fetch", maps_used=0)
            fetch_result = _fetch_all(
                input_sites=scan_sites,
                imagery_output_base_dir=imagery_base,
                max_requests=max_requests,
            )
            _progress(
                "fetch_done",
                maps_used=int(fetch_result.get("downloaded") or 0),
                cached=int(fetch_result.get("skipped_cached") or 0),
            )
        else:
            _progress("skip_fetch")

        if _cancelled():
            return {"cancelled": True, "step": "fetch"}

        _progress("detect")
        clusters = run_on_split(
            split="scan",
            weights=weights,
            input_sites=scan_sites,
            imagery_input_base_dir=imagery_base,
        )
        _progress("detect_done", clusters=len(clusters))

        if _cancelled():
            return {"cancelled": True, "step": "detect", "clusters": len(clusters)}

        geocoder = Geocoder(cache_path=out / "geocode_cache.json")
        names = {id(c): geocoder(c.lat, c.lon).get("location_name") for c in clusters}
        kml_out = out / "discovered_fields.kml"
        if clusters:
            clusters_to_kml(
                clusters,
                kml_out,
                document_name=f"Mooring scan: {kml_path.name}",
                names=names,
            )

        db_summary: dict[str, Any] = {}
        if clusters:
            db_summary = save_scan(
                clusters,
                source=f"scan:{kml_path.name}",
                weights=str(weights) if weights else "auto",
                split="scan",
                geocoder=geocoder,
                db_path=db_path if db_path else DB_PATH,
            )

        return {
            "scanned_locations": len(scan_sites),
            "discovered_clusters": len(clusters),
            "kml_output": str(kml_out) if clusters else None,
            "output_dir": str(out),
            "fetch": fetch_result,
            "db": db_summary,
            "cancelled": False,
        }
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def generate_region_kml(
    *,
    region: str | None = None,
    state: str | None = None,
    bbox: str | None = None,
    max_sites: int = 160,
    offset: int = 0,
    types: str = "MO,M",
    out: Path | None = None,
) -> dict[str, Any]:
    """Generate a candidates KML for a named region / state / bbox."""
    from mooring_fields.noaa_candidates import (
        NAMED_REGIONS,
        collect_candidates,
        write_candidates_kml,
    )

    type_list = [t.strip() for t in types.split(",") if t.strip()]
    bbox_tuple = None
    if bbox:
        parts = [float(x.strip()) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError("bbox must be west,south,east,north")
        bbox_tuple = (parts[0], parts[1], parts[2], parts[3])

    result = collect_candidates(
        states=[state] if state else None,
        region=region,
        bbox=bbox_tuple,
        types=type_list,
        max_sites=max_sites,
        offset=offset,
    )
    if out is None:
        label = region or state or "custom"
        out = Path("data") / f"candidates_{label}.kml"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_candidates_kml(result["candidates"], out)
    return {
        "out": str(out),
        "sites": int(result["deduped_count"]),
        "region": region,
        "state": state,
        "has_more": bool(result.get("has_more")),
        "regions": sorted(NAMED_REGIONS.keys()),
    }


def list_scan_regions() -> list[dict[str, Any]]:
    from mooring_fields.noaa_candidates import NAMED_REGIONS, STATE_BBOXES

    return [
        {"id": name, "kind": "region", "bbox": list(box)}
        for name, box in sorted(NAMED_REGIONS.items())
    ] + [
        {"id": st, "kind": "state", "bbox": list(box)}
        for st, box in sorted(STATE_BBOXES.items())
    ]
