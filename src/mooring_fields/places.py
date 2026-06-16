"""Google Places API enrichment for mooring fields."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from mooring_fields.enrichment_providers import PlaceResult
from mooring_fields.paths import PLACES_CACHE

PLACEHOLDER_KEYS = {"", "your_api_key_here", "paste_your_key_here"}
NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"


def _cache_key(lat: float, lon: float) -> str:
    return f"{round(lat, 4)},{round(lon, 4)}"


def _load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def get_api_key() -> str:
    load_dotenv()
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key or key in PLACEHOLDER_KEYS:
        raise EnvironmentError("GOOGLE_MAPS_API_KEY is not set for Places API.")
    return key


class LivePlacesProvider:
    """Places API (New) nearby search + place details with disk cache."""

    def __init__(self, cfg: dict, cache_path: Path | None = None):
        self.cfg = cfg
        places_cfg = cfg.get("places", {})
        self.radius = float(places_cfg.get("search_radius_meters", 500))
        self.included_types = places_cfg.get("included_types", ["marina"])
        self.max_results = int(places_cfg.get("max_results", 5))
        self.cache_path = cache_path or PLACES_CACHE
        self.cache = _load_cache(self.cache_path)
        self.calls_made = 0
        self._rps = float(cfg.get("requests_per_second", 2))
        self._last_call = 0.0

    def _throttle(self) -> None:
        if self._rps <= 0:
            return
        gap = 1.0 / self._rps
        elapsed = time.monotonic() - self._last_call
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_call = time.monotonic()

    def lookup(self, lat: float, lon: float, field_id: int) -> PlaceResult | None:
        key = _cache_key(lat, lon)
        if key in self.cache:
            return self._from_cache(self.cache[key])

        api_key = get_api_key()
        self._throttle()
        body = {
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": self.radius,
                }
            },
            "includedTypes": self.included_types,
            "maxResultCount": self.max_results,
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.nationalPhoneNumber,places.websiteUri,places.types"
            ),
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(NEARBY_URL, json=body, headers=headers)
            resp.raise_for_status()
            self.calls_made += 1
            payload = resp.json()

        places = payload.get("places", [])
        if not places:
            self.cache[key] = {"empty": True}
            _save_cache(self.cache_path, self.cache)
            return None

        top = places[0]
        place_id = top.get("id", "").replace("places/", "")
        result = PlaceResult(
            place_id=place_id or None,
            name=(top.get("displayName") or {}).get("text"),
            address=top.get("formattedAddress"),
            phone=top.get("nationalPhoneNumber"),
            website=top.get("websiteUri"),
            types=top.get("types", []),
            raw=top,
        )
        self.cache[key] = {
            "place_id": result.place_id,
            "name": result.name,
            "address": result.address,
            "phone": result.phone,
            "website": result.website,
            "types": result.types,
            "raw": result.raw,
        }
        _save_cache(self.cache_path, self.cache)
        return result

    def _from_cache(self, entry: dict[str, Any]) -> PlaceResult | None:
        if entry.get("empty"):
            return None
        return PlaceResult(
            place_id=entry.get("place_id"),
            name=entry.get("name"),
            address=entry.get("address"),
            phone=entry.get("phone"),
            website=entry.get("website"),
            types=entry.get("types", []),
            raw=entry.get("raw", entry),
        )
