"""Reverse geocoding for mooring field locations via Google Geocoding API."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from mooring_fields.paths import GEOCODE_CACHE

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACEHOLDER_KEYS = {"", "your_api_key_here", "paste_your_key_here"}


def _cache_key(lat: float, lon: float) -> str:
    """Round coordinates so nearby detections share one cache entry / API call."""
    return f"{round(lat, 4)},{round(lon, 4)}"


def _load_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache_path: Path, cache: dict) -> None:
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


def _parse_response(payload: dict) -> dict:
    results = payload.get("results", [])
    if not results:
        return {}
    top = results[0]
    location_name = top.get("formatted_address")
    country = None
    for comp in top.get("address_components", []):
        if "country" in comp.get("types", []):
            country = comp.get("long_name")
            break
    return {"location_name": location_name, "country": country}


class Geocoder:
    """Cached reverse geocoder. Falls back to a lat/lon string when unavailable."""

    def __init__(self, api_key: str | None = None, cache_path: Path | None = None):
        load_dotenv()
        self.api_key = (api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")).strip()
        self.cache_path = cache_path or GEOCODE_CACHE
        self.cache = _load_cache(self.cache_path)

    def reverse(self, lat: float, lon: float) -> dict:
        key = _cache_key(lat, lon)
        if key in self.cache:
            return self.cache[key]

        fallback = {"location_name": f"{lat:.5f}, {lon:.5f}", "country": None}
        if not self.api_key or self.api_key in PLACEHOLDER_KEYS:
            return fallback

        try:
            resp = httpx.get(
                GEOCODE_URL,
                params={"latlng": f"{lat},{lon}", "key": self.api_key},
                timeout=30.0,
            )
            if resp.is_success:
                parsed = _parse_response(resp.json())
                result = parsed if parsed.get("location_name") else fallback
            else:
                result = fallback
        except Exception:
            result = fallback

        self.cache[key] = result
        _save_cache(self.cache_path, self.cache)
        return result

    def __call__(self, lat: float, lon: float) -> dict:
        return self.reverse(lat, lon)


def reverse_geocode(lat: float, lon: float, api_key: str | None = None) -> dict:
    """One-off reverse geocode (creates a Geocoder with shared cache)."""
    return Geocoder(api_key=api_key).reverse(lat, lon)
