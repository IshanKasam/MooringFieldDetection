"""Geospatial helpers for tile bounds and coordinate transforms."""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_M = 6_378_137.0


@dataclass
class TileBounds:
    north: float
    south: float
    east: float
    west: float
    center_lat: float
    center_lon: float
    zoom: int
    gsd_meters: float


def meters_per_pixel(lat: float, zoom: int) -> float:
    """Ground sample distance at equator-adjusted latitude."""
    return (
        math.cos(math.radians(lat))
        * 2
        * math.pi
        * EARTH_RADIUS_M
        / (256 * 2**zoom)
    )


def zoom_from_range(
    lat: float,
    range_m: float,
    image_size_px: int = 640,
    scale: int = 2,
    fovy_deg: float = 30.0,
) -> int:
    """Estimate Static Maps zoom from KML LookAt range (meters)."""
    effective_px = image_size_px * scale
    # Approximate ground width visible at range with given vertical FOV
    ground_width_m = 2 * range_m * math.tan(math.radians(fovy_deg / 2))
    if ground_width_m <= 0:
        return 19
    mpp = ground_width_m / effective_px
    zoom = math.log2(
        math.cos(math.radians(lat)) * 2 * math.pi * EARTH_RADIUS_M / (256 * mpp)
    )
    return int(max(17, min(20, round(zoom))))


def offset_latlon(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Offset a WGS84 point by meters (north/east)."""
    d_lat = north_m / EARTH_RADIUS_M * (180 / math.pi)
    d_lon = east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat))) * (180 / math.pi)
    return lat + d_lat, lon + d_lon


def tile_bounds(
    center_lat: float,
    center_lon: float,
    zoom: int,
    width_px: int = 640,
    height_px: int = 640,
    scale: int = 2,
) -> TileBounds:
    """Compute geographic bounds for a Static Maps tile centered on a point."""
    mpp = meters_per_pixel(center_lat, zoom)
    half_w_m = (width_px * scale / 2) * mpp
    half_h_m = (height_px * scale / 2) * mpp

    north, _ = offset_latlon(center_lat, center_lon, half_h_m, 0)
    south, _ = offset_latlon(center_lat, center_lon, -half_h_m, 0)
    _, east = offset_latlon(center_lat, center_lon, 0, half_w_m)
    _, west = offset_latlon(center_lat, center_lon, 0, -half_w_m)

    return TileBounds(
        north=north,
        south=south,
        east=east,
        west=west,
        center_lat=center_lat,
        center_lon=center_lon,
        zoom=zoom,
        gsd_meters=mpp,
    )


def pixel_to_latlon(
    x: float,
    y: float,
    bounds: TileBounds,
    width_px: int,
    height_px: int,
) -> tuple[float, float]:
    """Convert normalized or pixel coords to lat/lon using tile bounds."""
    lon = bounds.west + (x / width_px) * (bounds.east - bounds.west)
    lat = bounds.north - (y / height_px) * (bounds.north - bounds.south)
    return lat, lon


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    r = EARTH_RADIUS_M
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_p = math.radians(lat2 - lat1)
    d_l = math.radians(lon2 - lon1)
    a = math.sin(d_p / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_l / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
