"""Download satellite tiles via Google Maps Static API."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

from mooring_fields.geo_utils import offset_latlon, tile_bounds, zoom_from_range
from mooring_fields.kml_parser import Site, load_sites_json
from mooring_fields.paths import CONFIG_DIR, IMAGERY_DIR
from mooring_fields.split_sites import sites_for_split

STATIC_MAPS_URL = "https://maps.googleapis.com/maps/api/staticmap"
PLACEHOLDER_KEYS = {"", "your_api_key_here", "paste_your_key_here"}

DIRECTION_OFFSETS = {
    "center": (0, 0),
    "north": (200, 0),
    "south": (-200, 0),
    "east": (0, 200),
    "west": (0, -200),
}


def load_imagery_config() -> dict:
    return yaml.safe_load((CONFIG_DIR / "imagery.yaml").read_text(encoding="utf-8"))


def get_api_key() -> str:
    load_dotenv()
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key or key in PLACEHOLDER_KEYS:
        raise EnvironmentError(
            "GOOGLE_MAPS_API_KEY is not set. Open .env and paste your regenerated "
            "Maps Static API key on the GOOGLE_MAPS_API_KEY= line."
        )
    return key


def build_static_map_url(
    lat: float,
    lon: float,
    zoom: int,
    api_key: str,
    cfg: dict,
) -> str:
    params = {
        "center": f"{lat},{lon}",
        "zoom": str(zoom),
        "size": f"{cfg['size']}x{cfg['size']}",
        "scale": str(cfg["scale"]),
        "maptype": cfg["maptype"],
        "key": api_key,
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{STATIC_MAPS_URL}?{query}"


def site_zoom(site: Site, cfg: dict) -> int:
    look = site.look_at
    if look.range and look.fovy:
        z = zoom_from_range(
            site.latitude,
            look.range,
            image_size_px=cfg["size"],
            scale=cfg["scale"],
            fovy_deg=look.fovy,
        )
    else:
        z = cfg.get("default_zoom", 19)
    return int(max(cfg["min_zoom"], min(cfg["max_zoom"], z)))


def tile_filename(site: Site, direction: str, zoom: int) -> str:
    return f"{site.slug}_{direction}_z{zoom}.png"


def iter_planned_tiles(
    split: str | None = None,
) -> list[tuple[str, Site, str, int, Path]]:
    """List all tiles with output paths for a split (or train+val)."""
    cfg = load_imagery_config()
    sites = load_sites_json()
    splits = [split] if split else ["train", "val"]
    directions = cfg.get("offset_directions", list(DIRECTION_OFFSETS.keys()))
    planned: list[tuple[str, Site, str, int, Path]] = []

    for sp in splits:
        for site in sites_for_split(sites, sp):
            zoom = site_zoom(site, cfg)
            for direction in directions:
                filename = tile_filename(site, direction, zoom)
                path = IMAGERY_DIR / sp / filename
                planned.append((sp, site, direction, zoom, path))
    return planned


def estimate_fetch(split: str | None = None) -> dict:
    """Estimate API usage before downloading."""
    cfg = load_imagery_config()
    planned = iter_planned_tiles(split)
    total = len(planned)
    cached = sum(1 for *_, path in planned if path.exists() and path.stat().st_size > 0)
    needed = total - cached
    max_per_run = cfg.get("max_api_requests_per_run", 800)
    free_tier = cfg.get("google_free_tier_monthly", 10000)
    load_dotenv()
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()

    return {
        "total_tiles": total,
        "already_cached": cached,
        "api_calls_needed": needed,
        "within_run_cap": needed <= max_per_run,
        "max_api_requests_per_run": max_per_run,
        "within_free_tier": needed <= free_tier,
        "google_free_tier_monthly": free_tier,
        "estimated_cost_usd": 0.0 if needed <= free_tier else "review Google pricing",
        "ready_to_fetch": needed == 0 or (bool(key) and key not in PLACEHOLDER_KEYS),
    }


def _should_retry(status_code: int | None) -> bool:
    """Only retry transient server errors — not billable client errors."""
    if status_code is None:
        return True
    return status_code >= 500


def fetch_tile(
    client: httpx.Client,
    lat: float,
    lon: float,
    zoom: int,
    api_key: str,
    cfg: dict,
    dest: Path,
    api_budget: list[int],
    cap: int,
) -> tuple[Path, bool]:
    """Download tile. Returns (path, whether a billable API call was made)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest, False

    if api_budget[0] >= cap:
        raise RuntimeError(
            f"API request cap ({cap}) reached during fetch. "
            "Cached tiles are kept; re-run to continue."
        )

    url = build_static_map_url(lat, lon, zoom, api_key, cfg)
    max_retries = cfg.get("max_retries", 2)
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            api_budget[0] += 1
            if api_budget[0] > cap:
                raise RuntimeError(f"API request cap ({cap}) exceeded.")

            response = client.get(url, timeout=60.0)
            if not response.is_success:
                if _should_retry(response.status_code) and attempt < max_retries - 1:
                    time.sleep(cfg.get("retry_backoff_seconds", 2) * (attempt + 1))
                    continue
                response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "image" not in content_type:
                raise RuntimeError(
                    f"Expected image, got {content_type}: {response.text[:200]}"
                )
            dest.write_bytes(response.content)
            return dest, True
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(cfg.get("retry_backoff_seconds", 2) * (attempt + 1))
                continue
        except RuntimeError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(cfg.get("retry_backoff_seconds", 2) * (attempt + 1))

    raise RuntimeError(f"Failed to fetch {dest.name}") from last_error


def write_metadata(
    meta_path: Path,
    site: Site,
    direction: str,
    lat: float,
    lon: float,
    zoom: int,
    cfg: dict,
    image_path: Path,
) -> None:
    bounds = tile_bounds(
        lat,
        lon,
        zoom,
        width_px=cfg["size"],
        height_px=cfg["size"],
        scale=cfg["scale"],
    )
    payload = {
        "site_id": site.id,
        "site_name": site.name,
        "direction": direction,
        "center_lat": lat,
        "center_lon": lon,
        "zoom": zoom,
        "image_path": str(image_path),
        "bounds": asdict(bounds),
        "look_at_range": site.look_at.range,
    }
    meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def fetch_all(
    split: str | None = None,
    dry_run: bool = False,
    max_requests: int | None = None,
) -> dict:
    cfg = load_imagery_config()
    cap = max_requests if max_requests is not None else cfg.get("max_api_requests_per_run", 800)

    if dry_run:
        est = estimate_fetch(split)
        planned = iter_planned_tiles(split)
        by_split: dict[str, list[str]] = {"train": [], "val": []}
        for sp, site, direction, zoom, _ in planned:
            by_split[sp].append(tile_filename(site, direction, zoom))
        return {"dry_run": True, "estimate": est, "tiles": by_split}

    api_key = get_api_key()
    est = estimate_fetch(split)
    if est["api_calls_needed"] > cap:
        raise RuntimeError(
            f"Refusing to fetch: {est['api_calls_needed']} API calls needed but "
            f"max_api_requests_per_run is {cap}. Use --max-requests to override or "
            "raise max_api_requests_per_run in config/imagery.yaml."
        )

    min_interval = 1.0 / cfg.get("requests_per_second", 10)
    api_budget = [0]
    downloaded = 0
    skipped_cached = 0
    results: dict[str, list[str]] = {"train": [], "val": []}

    with httpx.Client() as client:
        for sp, site, direction, zoom, image_path in iter_planned_tiles(split):
            north_m, east_m = DIRECTION_OFFSETS.get(direction, (0, 0))
            lat, lon = offset_latlon(site.latitude, site.longitude, north_m, east_m)
            meta_path = image_path.with_suffix(".json")

            time.sleep(min_interval)
            was_cached = image_path.exists() and image_path.stat().st_size > 0
            fetch_tile(
                client, lat, lon, zoom, api_key, cfg, image_path, api_budget, cap
            )
            if was_cached:
                skipped_cached += 1
            else:
                downloaded += 1

            if not meta_path.exists() or meta_path.stat().st_size == 0:
                write_metadata(meta_path, site, direction, lat, lon, zoom, cfg, image_path)
            results[sp].append(str(image_path))

    return {
        "train_tiles": len(results["train"]),
        "val_tiles": len(results["val"]),
        "api_calls_made": api_budget[0],
        "downloaded": downloaded,
        "skipped_cached": skipped_cached,
        "output_dir": str(IMAGERY_DIR),
    }
