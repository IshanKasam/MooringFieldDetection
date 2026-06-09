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
    if not key:
        raise EnvironmentError(
            "GOOGLE_MAPS_API_KEY not set. Copy .env.example to .env and add your key."
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


def fetch_tile(
    client: httpx.Client,
    lat: float,
    lon: float,
    zoom: int,
    api_key: str,
    cfg: dict,
    dest: Path,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    url = build_static_map_url(lat, lon, zoom, api_key, cfg)
    last_error: Exception | None = None
    for attempt in range(cfg.get("max_retries", 3)):
        try:
            response = client.get(url, timeout=60.0)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type:
                raise RuntimeError(
                    f"Expected image, got {content_type}: {response.text[:200]}"
                )
            dest.write_bytes(response.content)
            return dest
        except Exception as exc:
            last_error = exc
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


def fetch_site_tiles(
    site: Site,
    split: str,
    api_key: str,
    cfg: dict,
    client: httpx.Client,
    min_interval: float,
) -> list[Path]:
    zoom = site_zoom(site, cfg)
    saved: list[Path] = []
    out_dir = IMAGERY_DIR / split

    directions = cfg.get("offset_directions", list(DIRECTION_OFFSETS.keys()))
    for direction in directions:
        north_m, east_m = DIRECTION_OFFSETS.get(direction, (0, 0))
        lat, lon = offset_latlon(site.latitude, site.longitude, north_m, east_m)

        filename = tile_filename(site, direction, zoom)
        image_path = out_dir / filename
        meta_path = out_dir / filename.replace(".png", ".json")

        time.sleep(min_interval)
        fetch_tile(client, lat, lon, zoom, api_key, cfg, image_path)
        write_metadata(meta_path, site, direction, lat, lon, zoom, cfg, image_path)
        saved.append(image_path)

    return saved


def fetch_all(split: str | None = None, dry_run: bool = False) -> dict:
    cfg = load_imagery_config()
    sites = load_sites_json()
    api_key = get_api_key() if not dry_run else ""

    splits = [split] if split else ["train", "val"]
    min_interval = 1.0 / cfg.get("requests_per_second", 10)
    results: dict[str, list[str]] = {"train": [], "val": []}

    if dry_run:
        for sp in splits:
            for site in sites_for_split(sites, sp):
                zoom = site_zoom(site, cfg)
                results[sp].append(tile_filename(site, "center", zoom))
        return {"dry_run": True, "tiles": results}

    with httpx.Client() as client:
        for sp in splits:
            for site in sites_for_split(sites, sp):
                paths = fetch_site_tiles(site, sp, api_key, cfg, client, min_interval)
                results[sp].extend(str(p) for p in paths)

    return {
        "train_tiles": len(results["train"]),
        "val_tiles": len(results["val"]),
        "output_dir": str(IMAGERY_DIR),
    }
