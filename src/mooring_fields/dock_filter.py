"""Reject boat clusters that look like marina/pier docks rather than moorings.

Primary checks (v1):
  - OSM Overpass proximity (pier, marina, quay, floating_dock, harbour)
  - PCA aspect-ratio (linear = pier-like)

Enhanced checks (v2):
  - Shoreline proximity (OSM coastline/riverbank ways)
  - Boat spacing regularity (nearest-neighbour CV)
  - Convex hull density (boats / hull area)
  - Pier alignment (PCA major axis vs nearest pier bearing)

Soft-fails if Overpass is down.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

import httpx
import numpy as np

from mooring_fields.geo_utils import haversine_m
from mooring_fields.noaa_candidates import OVERPASS_MIRRORS, USER_AGENT
from mooring_fields.paths import DATA_DIR

log = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "cache" / "osm_docks"
SHORELINE_CACHE_DIR = DATA_DIR / "cache" / "osm_shoreline"
CACHE_TTL_SECONDS = 7 * 24 * 3600
# Overpass rejects continent-scale queries (often HTTP 406). Tile around fields.
TILE_DEG = 0.5
TILE_PAD_DEG = 0.05
RETRYABLE_STATUS = frozenset({406, 429, 502, 503, 504})
TILE_SLEEP_S = 0.25
OVERPASS_TIMEOUT_S = 90


@dataclass
class DockPoint:
    lat: float
    lon: float
    kind: str


@dataclass
class ShorelineSegment:
    """A single segment of an OSM coastline/riverbank way."""
    lat1: float
    lon1: float
    lat2: float
    lon2: float


def _http_client(timeout: float = OVERPASS_TIMEOUT_S) -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(timeout, connect=15.0),
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )


def _bbox_hash(bbox: tuple[float, float, float, float]) -> str:
    key = ",".join(f"{v:.5f}" for v in bbox)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _dock_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    west, south, east, north = bbox
    bb = f"({south},{west},{north},{east})"
    # Nodes + ways only (no relations); centers are enough for ~80 m proximity.
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n"
        "(\n"
        f'  node["man_made"="pier"]{bb};\n'
        f'  way["man_made"="pier"]{bb};\n'
        f'  node["man_made"="quay"]{bb};\n'
        f'  way["man_made"="quay"]{bb};\n'
        f'  node["man_made"="floating_dock"]{bb};\n'
        f'  way["man_made"="floating_dock"]{bb};\n'
        f'  node["leisure"="marina"]{bb};\n'
        f'  way["leisure"="marina"]{bb};\n'
        f'  node["seamark:type"="harbour"]{bb};\n'
        f'  way["seamark:type"="harbour"]{bb};\n'
        ");\n"
        "out center tags;\n"
    )


def _shoreline_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """Query OSM for coastline and riverbank ways (geometry, not just centers)."""
    west, south, east, north = bbox
    bb = f"({south},{west},{north},{east})"
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_S}];\n"
        "(\n"
        f'  way["natural"="coastline"]{bb};\n'
        f'  way["natural"="water"]["water"="river"]{bb};\n'
        f'  way["waterway"="riverbank"]{bb};\n'
        f'  way["man_made"="breakwater"]{bb};\n'
        ");\n"
        "out geom;\n"
    )


def _parse_dock_elements(elements: list[dict[str, Any]]) -> list[DockPoint]:
    out: list[DockPoint] = []
    for el in elements:
        tags = el.get("tags") or {}
        lat = el.get("lat")
        lon = el.get("lon")
        if lat is None or lon is None:
            center = el.get("center") or {}
            lat, lon = center.get("lat"), center.get("lon")
        if lat is None or lon is None:
            continue
        kind = (
            tags.get("man_made")
            or tags.get("leisure")
            or tags.get("seamark:type")
            or "dock"
        )
        out.append(DockPoint(lat=float(lat), lon=float(lon), kind=str(kind)))
    return out


def _tiles_covering_points(
    points: Sequence[tuple[float, float]],
    *,
    cell_deg: float = TILE_DEG,
    pad_deg: float = TILE_PAD_DEG,
) -> list[tuple[float, float, float, float]]:
    """Return W,S,E,N tiles that cover sample points (avoids empty ocean queries)."""
    if not points:
        return []
    cells: set[tuple[int, int]] = set()
    for lat, lon in points:
        for dlat in (-pad_deg, 0.0, pad_deg):
            for dlon in (-pad_deg, 0.0, pad_deg):
                i = math.floor((lat + dlat) / cell_deg)
                j = math.floor((lon + dlon) / cell_deg)
                cells.add((i, j))
    tiles: list[tuple[float, float, float, float]] = []
    for i, j in sorted(cells):
        south = i * cell_deg
        west = j * cell_deg
        tiles.append((west, south, west + cell_deg, south + cell_deg))
    return tiles


def _tile_bbox(
    bbox: tuple[float, float, float, float],
    *,
    cell_deg: float = TILE_DEG,
) -> list[tuple[float, float, float, float]]:
    west, south, east, north = bbox
    if east <= west or north <= south:
        return [bbox]
    if (east - west) <= cell_deg and (north - south) <= cell_deg:
        return [bbox]
    tiles: list[tuple[float, float, float, float]] = []
    lat = south
    while lat < north - 1e-12:
        lon = west
        lat2 = min(lat + cell_deg, north)
        while lon < east - 1e-12:
            lon2 = min(lon + cell_deg, east)
            tiles.append((lon, lat, lon2, lat2))
            lon = lon2
        lat = lat2
    return tiles


def _load_tile_cache(cache_path) -> list[DockPoint] | None:
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched_at = float(payload.get("fetched_at") or 0)
        if time.time() - fetched_at >= CACHE_TTL_SECONDS:
            return None
        return [
            DockPoint(
                lat=float(p["lat"]),
                lon=float(p["lon"]),
                kind=str(p.get("kind") or "dock"),
            )
            for p in payload.get("points") or []
        ]
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _save_tile_cache(
    cache_path, bbox: tuple[float, float, float, float], points: list[DockPoint]
) -> None:
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "bbox": list(bbox),
                "fetched_iso": datetime.now(timezone.utc).isoformat(),
                "points": [
                    {"lat": p.lat, "lon": p.lon, "kind": p.kind} for p in points
                ],
            }
        ),
        encoding="utf-8",
    )


def _overpass_elements(
    client: httpx.Client, bbox: tuple[float, float, float, float]
) -> list[dict[str, Any]]:
    query = _dock_overpass_query(bbox)
    last_err: Exception | None = None
    for attempt in range(len(OVERPASS_MIRRORS)):
        url = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        try:
            # POST avoids huge-URL issues; mirrors prefer Accept + User-Agent.
            resp = client.post(url, data={"data": query})
            if resp.status_code in RETRYABLE_STATUS:
                last_err = httpx.HTTPStatusError(
                    f"Overpass {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            return list(resp.json().get("elements") or [])
        except httpx.HTTPError as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    if last_err is not None:
        raise last_err
    return []


def _fetch_one_tile(
    bbox: tuple[float, float, float, float],
    *,
    client: httpx.Client,
    use_cache: bool,
) -> list[DockPoint]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{_bbox_hash(bbox)}.json"
    if use_cache:
        cached = _load_tile_cache(cache_path)
        if cached is not None:
            return cached
    points = _parse_dock_elements(_overpass_elements(client, bbox))
    if use_cache:
        _save_tile_cache(cache_path, bbox, points)
    return points


def fetch_dock_geometries(
    bbox: tuple[float, float, float, float],
    *,
    client: httpx.Client | None = None,
    use_cache: bool = True,
    sample_points: Sequence[tuple[float, float]] | None = None,
) -> list[DockPoint]:
    """Fetch OSM dock/marina/pier points for a W,S,E,N bbox (tiled + cached).

    When ``sample_points`` is set (field/cluster centroids), only tiles that
    cover those points are queried — critical for multi-state DBs.
    """
    if sample_points:
        tiles = _tiles_covering_points(sample_points)
    else:
        tiles = _tile_bbox(bbox)
    if not tiles:
        return []

    own = client is None
    client = client or _http_client()
    try:
        print(
            f"dock filter: fetching OSM docks across {len(tiles)} tile(s)",
            flush=True,
        )
        seen: set[tuple[float, float, str]] = set()
        out: list[DockPoint] = []
        tile_errors: list[str] = []
        for i, tile in enumerate(tiles):
            if i:
                time.sleep(TILE_SLEEP_S)
            try:
                tile_points = _fetch_one_tile(
                    tile, client=client, use_cache=use_cache
                )
            except Exception as exc:  # noqa: BLE001 — continue other tiles
                msg = f"{tile}: {exc}"
                tile_errors.append(msg)
                log.warning("dock filter tile failed (%s)", msg)
                print(f"dock filter: tile {i + 1}/{len(tiles)} failed — {exc}", flush=True)
                continue
            for p in tile_points:
                key = (round(p.lat, 5), round(p.lon, 5), p.kind)
                if key in seen:
                    continue
                seen.add(key)
                out.append(p)
            if (i + 1) % 5 == 0 or i + 1 == len(tiles):
                print(
                    f"dock filter: OSM tiles {i + 1}/{len(tiles)} ({len(out)} points)",
                    flush=True,
                )
        if not out and tile_errors:
            raise RuntimeError(
                f"All {len(tile_errors)} Overpass tile(s) failed; "
                f"first={tile_errors[0]}"
            )
        if tile_errors:
            print(
                f"dock filter: {len(tile_errors)} tile(s) failed; "
                f"using {len(out)} points from successful tiles",
                flush=True,
            )
        return out
    finally:
        if own:
            client.close()


def min_distance_m(lat: float, lon: float, docks: Sequence[DockPoint]) -> float:
    if not docks:
        return float("inf")
    return min(haversine_m(lat, lon, d.lat, d.lon) for d in docks)


def _boats_to_xy(boats: Sequence[Any]) -> np.ndarray:
    """Convert boat lat/lon to local metre coordinates centred on the mean."""
    coords = np.array([[float(b.lat), float(b.lon)] for b in boats], dtype=float)
    mean_lat = float(coords[:, 0].mean())
    x = np.radians(coords[:, 1]) * np.cos(np.radians(mean_lat)) * 6_378_137
    y = np.radians(coords[:, 0]) * 6_378_137
    xy = np.column_stack([x, y])
    return xy - xy.mean(axis=0)


def _pca_eigenvalues(xy: np.ndarray) -> tuple[float, float] | None:
    """Return (min_eig, max_eig) from PCA on metre-space coords, or None."""
    if xy.shape[0] < 2:
        return None
    cov = np.cov(xy, rowvar=False)
    if cov.ndim == 0:
        return None
    eig = np.linalg.eigvalsh(cov)
    eig = np.clip(eig, 1e-9, None)
    return float(eig.min()), float(eig.max())


def _pca_major_axis_angle(xy: np.ndarray) -> float | None:
    """Angle (degrees, 0-180) of the major PCA axis."""
    if xy.shape[0] < 2:
        return None
    cov = np.cov(xy, rowvar=False)
    if cov.ndim == 0:
        return None
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    major = eigenvectors[:, np.argmax(eigenvalues)]
    angle = math.degrees(math.atan2(major[1], major[0])) % 180
    return angle


def cluster_aspect_ratio(boats: Sequence[Any]) -> float:
    """Length/width of boat cloud via PCA eigenvalues (1.0 = round)."""
    if len(boats) < 2:
        return 1.0
    xy = _boats_to_xy(boats)
    eig = _pca_eigenvalues(xy)
    if eig is None:
        return 1.0
    return float(math.sqrt(eig[1] / eig[0]))


# ---------------------------------------------------------------------------
# Enhanced heuristic helpers (v2)
# ---------------------------------------------------------------------------

def _point_to_segment_distance_m(
    lat: float, lon: float, seg: ShorelineSegment
) -> float:
    """Approximate distance from a point to a line segment on Earth's surface.

    Projects the point onto the segment in local-metre space and returns the
    haversine distance to the nearest point on the segment.
    """
    # Convert to local metres around the point
    cos_lat = math.cos(math.radians(lat))
    R = 6_378_137.0
    px = math.radians(lon) * cos_lat * R
    py = math.radians(lat) * R
    ax = math.radians(seg.lon1) * cos_lat * R
    ay = math.radians(seg.lat1) * R
    bx = math.radians(seg.lon2) * cos_lat * R
    by = math.radians(seg.lat2) * R

    dx, dy = bx - ax, by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return haversine_m(lat, lon, seg.lat1, seg.lon1)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
    # Nearest point on segment in metre space → back to degrees
    near_x = ax + t * dx
    near_y = ay + t * dy
    near_lon = math.degrees(near_x / (cos_lat * R))
    near_lat = math.degrees(near_y / R)
    return haversine_m(lat, lon, near_lat, near_lon)


def min_shoreline_distance_m(
    lat: float, lon: float, shoreline: Sequence[ShorelineSegment]
) -> float:
    """Minimum distance in metres from a point to any shoreline segment."""
    if not shoreline:
        return float("inf")
    return min(_point_to_segment_distance_m(lat, lon, s) for s in shoreline)


def boat_spacing_cv(boats: Sequence[Any]) -> float:
    """Coefficient of variation of nearest-neighbour distances.

    Low CV → very regular spacing (dock slips). High CV → natural scatter.
    Returns inf for < 3 boats (not enough data to judge).
    """
    if len(boats) < 3:
        return float("inf")
    xy = _boats_to_xy(boats)
    from scipy.spatial import cKDTree

    tree = cKDTree(xy)
    dists, _ = tree.query(xy, k=2)  # [self, nearest]
    nn = dists[:, 1]  # nearest-neighbour distances
    mean_d = float(nn.mean())
    if mean_d < 1e-6:
        return 0.0  # all boats on top of each other → extremely regular
    return float(nn.std() / mean_d)


def convex_hull_density(boats: Sequence[Any]) -> float:
    """Boats per m² inside their convex hull.

    High density → tightly packed (dock slips). Returns 0.0 if hull is degenerate.
    """
    if len(boats) < 3:
        return 0.0
    xy = _boats_to_xy(boats)
    from scipy.spatial import ConvexHull

    try:
        hull = ConvexHull(xy)
        area = float(hull.volume)  # in 2D, volume = area
    except Exception:  # noqa: BLE001 — degenerate hull
        return 0.0
    if area < 1.0:
        return 0.0
    return len(boats) / area


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing from point 1 to point 2 in degrees (0-360)."""
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(math.radians(lat2))
    x = (
        math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
        - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon)
    )
    return math.degrees(math.atan2(y, x)) % 360


def pier_alignment_angle(
    boats: Sequence[Any],
    docks: Sequence[DockPoint],
    cluster_lat: float,
    cluster_lon: float,
    max_dock_dist_m: float = 200.0,
) -> float | None:
    """Angle (0-90°) between cluster major axis and nearest dock/pier bearing.

    Returns None if no docks within max_dock_dist_m or < 2 boats.
    Small angle → boats aligned along the pier → likely a dock.
    """
    if len(boats) < 2 or not docks:
        return None
    # Find nearest dock within range
    nearest: DockPoint | None = None
    best_dist = float("inf")
    for d in docks:
        dist = haversine_m(cluster_lat, cluster_lon, d.lat, d.lon)
        if dist < best_dist:
            best_dist = dist
            nearest = d
    if nearest is None or best_dist > max_dock_dist_m:
        return None

    xy = _boats_to_xy(boats)
    pca_angle = _pca_major_axis_angle(xy)
    if pca_angle is None:
        return None

    pier_bearing = _bearing_deg(cluster_lat, cluster_lon, nearest.lat, nearest.lon) % 180
    delta = abs(pca_angle - pier_bearing)
    if delta > 90:
        delta = 180 - delta
    return delta


def _bbox_from_clusters(
    clusters: Sequence[Any], padding_deg: float = 0.02
) -> tuple[float, float, float, float] | None:
    if not clusters:
        return None
    lats = [float(c.lat) for c in clusters]
    lons = [float(c.lon) for c in clusters]
    return (
        min(lons) - padding_deg,
        min(lats) - padding_deg,
        max(lons) + padding_deg,
        max(lats) + padding_deg,
    )


# ---------------------------------------------------------------------------
# Shoreline data fetching (v2)
# ---------------------------------------------------------------------------

def _parse_shoreline_elements(elements: list[dict[str, Any]]) -> list[ShorelineSegment]:
    """Parse Overpass way geometry into line segments."""
    out: list[ShorelineSegment] = []
    for el in elements:
        geom = el.get("geometry") or []
        if len(geom) < 2:
            continue
        for i in range(len(geom) - 1):
            a, b = geom[i], geom[i + 1]
            lat1, lon1 = a.get("lat"), a.get("lon")
            lat2, lon2 = b.get("lat"), b.get("lon")
            if None in (lat1, lon1, lat2, lon2):
                continue
            out.append(ShorelineSegment(
                lat1=float(lat1), lon1=float(lon1),
                lat2=float(lat2), lon2=float(lon2),
            ))
    return out


def _load_shoreline_cache(cache_path) -> list[ShorelineSegment] | None:
    if not cache_path.is_file():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched_at = float(payload.get("fetched_at") or 0)
        if time.time() - fetched_at >= CACHE_TTL_SECONDS:
            return None
        return [
            ShorelineSegment(
                lat1=float(s["lat1"]), lon1=float(s["lon1"]),
                lat2=float(s["lat2"]), lon2=float(s["lon2"]),
            )
            for s in payload.get("segments") or []
        ]
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def _save_shoreline_cache(
    cache_path,
    bbox: tuple[float, float, float, float],
    segments: list[ShorelineSegment],
) -> None:
    cache_path.write_text(
        json.dumps(
            {
                "fetched_at": time.time(),
                "bbox": list(bbox),
                "fetched_iso": datetime.now(timezone.utc).isoformat(),
                "segments": [
                    {"lat1": s.lat1, "lon1": s.lon1,
                     "lat2": s.lat2, "lon2": s.lon2}
                    for s in segments
                ],
            }
        ),
        encoding="utf-8",
    )


def _fetch_shoreline_tile(
    bbox: tuple[float, float, float, float],
    *,
    client: httpx.Client,
    use_cache: bool,
) -> list[ShorelineSegment]:
    SHORELINE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tag = "shore_" + _bbox_hash(bbox)
    cache_path = SHORELINE_CACHE_DIR / f"{tag}.json"
    if use_cache:
        cached = _load_shoreline_cache(cache_path)
        if cached is not None:
            return cached
    query = _shoreline_overpass_query(bbox)
    last_err: Exception | None = None
    elements: list[dict[str, Any]] = []
    for attempt in range(len(OVERPASS_MIRRORS)):
        url = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
        try:
            resp = client.post(url, data={"data": query})
            if resp.status_code in RETRYABLE_STATUS:
                last_err = httpx.HTTPStatusError(
                    f"Overpass {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                time.sleep(1.5 * (attempt + 1))
                continue
            resp.raise_for_status()
            elements = list(resp.json().get("elements") or [])
            break
        except httpx.HTTPError as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    segments = _parse_shoreline_elements(elements)
    if use_cache:
        _save_shoreline_cache(cache_path, bbox, segments)
    return segments


def fetch_shoreline_segments(
    bbox: tuple[float, float, float, float],
    *,
    client: httpx.Client | None = None,
    use_cache: bool = True,
    sample_points: Sequence[tuple[float, float]] | None = None,
) -> list[ShorelineSegment]:
    """Fetch OSM shoreline segments for a W,S,E,N bbox (tiled + cached)."""
    if sample_points:
        tiles = _tiles_covering_points(sample_points)
    else:
        tiles = _tile_bbox(bbox)
    if not tiles:
        return []

    own = client is None
    client = client or _http_client()
    try:
        print(
            f"dock filter: fetching OSM shoreline across {len(tiles)} tile(s)",
            flush=True,
        )
        all_segs: list[ShorelineSegment] = []
        for i, tile in enumerate(tiles):
            if i:
                time.sleep(TILE_SLEEP_S)
            try:
                segs = _fetch_shoreline_tile(tile, client=client, use_cache=use_cache)
                all_segs.extend(segs)
            except Exception as exc:  # noqa: BLE001
                log.warning("shoreline tile %d failed: %s", i, exc)
            if (i + 1) % 5 == 0 or i + 1 == len(tiles):
                print(
                    f"dock filter: OSM shoreline tiles {i + 1}/{len(tiles)} ({len(all_segs)} segments)",
                    flush=True,
                )
        print(
            f"dock filter: {len(all_segs)} shoreline segments loaded",
            flush=True,
        )
        return all_segs
    finally:
        if own:
            client.close()


# ---------------------------------------------------------------------------
# Main filter
# ---------------------------------------------------------------------------

def filter_mooring_clusters(
    clusters: list[Any],
    cfg: dict[str, Any],
    *,
    bbox: tuple[float, float, float, float] | None = None,
    docks: Sequence[DockPoint] | None = None,
    shoreline: Sequence[ShorelineSegment] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Drop dock-adjacent / linear pier-shaped clusters.

    v1 checks: OSM dock proximity, PCA aspect ratio.
    v2 checks: shoreline proximity, spacing CV, hull density, pier alignment.

    Returns (kept_clusters, stats). On Overpass failure with soft_fail, keeps all.
    """
    if not cfg.get("dock_filter_enabled", True):
        return clusters, {"enabled": False, "kept": len(clusters), "rejected": 0}

    # --- Config knobs ---
    reject_m = float(cfg.get("reject_near_dock_meters", 80))
    aspect_max = float(cfg.get("reject_linear_aspect_ratio", 4.0))
    soft_fail = bool(cfg.get("dock_filter_soft_fail", True))
    # v2 knobs
    shoreline_m = float(cfg.get("reject_shoreline_meters", 30))
    spacing_cv_min = float(cfg.get("reject_spacing_cv_below", 0.25))
    density_max = float(cfg.get("reject_density_above", 0.005))
    pier_align_deg = float(cfg.get("reject_pier_alignment_deg", 20))

    stats: dict[str, Any] = {
        "enabled": True,
        "kept": 0,
        "rejected": 0,
        "rejected_near_dock": 0,
        "rejected_linear": 0,
        "rejected_shoreline": 0,
        "rejected_spacing": 0,
        "rejected_density": 0,
        "rejected_pier_aligned": 0,
        "dock_points": 0,
        "shoreline_segments": 0,
        "overpass_error": None,
    }

    dock_list: list[DockPoint]
    shore_list: list[ShorelineSegment]
    if docks is not None:
        dock_list = list(docks)
    else:
        use_bbox = bbox or _bbox_from_clusters(clusters)
        if use_bbox is None:
            return clusters, {**stats, "kept": len(clusters)}
        sample = [(float(c.lat), float(c.lon)) for c in clusters]
        try:
            dock_list = fetch_dock_geometries(
                use_bbox, sample_points=sample
            )
        except Exception as exc:  # noqa: BLE001 — soft-fail path
            stats["overpass_error"] = str(exc)
            log.warning("dock filter Overpass failed (%s); soft_fail=%s", exc, soft_fail)
            if not soft_fail:
                raise
            dock_list = []

    # Fetch shoreline (v2)
    if shoreline is not None:
        shore_list = list(shoreline)
    else:
        use_bbox = bbox or _bbox_from_clusters(clusters)
        if use_bbox is None:
            shore_list = []
        else:
            sample = [(float(c.lat), float(c.lon)) for c in clusters]
            try:
                shore_list = fetch_shoreline_segments(
                    use_bbox, sample_points=sample
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("shoreline fetch failed (%s); continuing without", exc)
                shore_list = []

    stats["dock_points"] = len(dock_list)
    stats["shoreline_segments"] = len(shore_list)
    kept: list[Any] = []
    for cluster in clusters:
        clat, clon = float(cluster.lat), float(cluster.lon)
        boats = getattr(cluster, "boats", None) or []

        # --- v1: OSM dock proximity ---
        near = min_distance_m(clat, clon, dock_list)
        if near <= reject_m:
            stats["rejected"] += 1
            stats["rejected_near_dock"] += 1
            continue

        # --- v1: PCA aspect ratio ---
        aspect = cluster_aspect_ratio(boats) if boats else 1.0
        if aspect >= aspect_max:
            stats["rejected"] += 1
            stats["rejected_linear"] += 1
            continue

        # --- v2: Shoreline proximity ---
        if shore_list and shoreline_m > 0:
            shore_dist = min_shoreline_distance_m(clat, clon, shore_list)
            if shore_dist <= shoreline_m:
                stats["rejected"] += 1
                stats["rejected_shoreline"] += 1
                continue

        # --- v2: Boat spacing regularity ---
        if boats and spacing_cv_min > 0:
            cv = boat_spacing_cv(boats)
            if cv < spacing_cv_min:
                stats["rejected"] += 1
                stats["rejected_spacing"] += 1
                continue

        # --- v2: Convex hull density ---
        if boats and density_max > 0:
            dens = convex_hull_density(boats)
            if dens > density_max:
                stats["rejected"] += 1
                stats["rejected_density"] += 1
                continue

        # --- v2: Pier alignment ---
        if boats and dock_list and pier_align_deg > 0:
            align = pier_alignment_angle(boats, dock_list, clat, clon)
            if align is not None and align <= pier_align_deg:
                stats["rejected"] += 1
                stats["rejected_pier_aligned"] += 1
                continue

        kept.append(cluster)
    stats["kept"] = len(kept)
    return kept, stats


@dataclass
class _FieldProxy:
    lat: float
    lon: float
    boats: list[Any]
    field_id: int


def filter_field_rows(
    fields: list[dict[str, Any]],
    cfg: dict[str, Any],
    *,
    docks: Sequence[DockPoint] | None = None,
    boats_by_field: dict[int, list[Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Split DB field rows into keep vs reject (for refilter-docks CLI)."""
    boats_by_field = boats_by_field or {}
    proxies = [
        _FieldProxy(
            lat=float(f["latitude"]),
            lon=float(f["longitude"]),
            boats=list(boats_by_field.get(int(f["id"]), [])),
            field_id=int(f["id"]),
        )
        for f in fields
    ]
    kept_proxies, stats = filter_mooring_clusters(proxies, cfg, docks=docks)
    kept_ids = {p.field_id for p in kept_proxies}
    keep_rows = [f for f in fields if int(f["id"]) in kept_ids]
    reject_rows = [f for f in fields if int(f["id"]) not in kept_ids]
    stats["fields_kept"] = len(keep_rows)
    stats["fields_rejected"] = len(reject_rows)
    return keep_rows, reject_rows, stats


def refilter_db_fields(
    conn: Any,
    cfg: dict[str, Any],
    *,
    scan_id: int | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    docks: Sequence[DockPoint] | None = None,
) -> dict[str, Any]:
    """Mark dock-adjacent / linear fields as enrichment_status=skipped."""
    from mooring_fields.database import list_fields, set_field_enrichment_status

    class _Boat:
        __slots__ = ("lat", "lon")

        def __init__(self, lat: float, lon: float):
            self.lat = lat
            self.lon = lon

    rows = list_fields(conn, scan_id=scan_id)
    # Skip already-skipped; do not touch researched/exported/places_done
    candidates = [
        dict(r)
        for r in rows
        if (r["enrichment_status"] or "pending") == "pending"
    ]
    if limit is not None:
        candidates = candidates[: max(0, int(limit))]
    if not candidates:
        return {
            "scan_id": scan_id,
            "considered": 0,
            "marked_skipped": 0,
            "dry_run": dry_run,
            "limit": limit,
        }

    field_ids = [int(f["id"]) for f in candidates]
    boats_by_field: dict[int, list[_Boat]] = {fid: [] for fid in field_ids}
    placeholders = ",".join("?" for _ in field_ids)
    for r in conn.execute(
        f"SELECT field_id, latitude, longitude FROM boats "
        f"WHERE field_id IN ({placeholders})",
        field_ids,
    ):
        boats_by_field[int(r["field_id"])].append(
            _Boat(float(r["latitude"]), float(r["longitude"]))
        )

    _keep, reject_rows, stats = filter_field_rows(
        candidates, cfg, docks=docks, boats_by_field=boats_by_field
    )
    marked = 0
    if not dry_run:
        for f in reject_rows:
            set_field_enrichment_status(conn, int(f["id"]), "skipped")
            marked += 1
    else:
        marked = len(reject_rows)

    result = {
        "scan_id": scan_id,
        "considered": len(candidates),
        "marked_skipped": marked,
        "dry_run": dry_run,
        "limit": limit,
        "dock_points": stats.get("dock_points"),
        "rejected_near_dock": stats.get("rejected_near_dock"),
        "rejected_linear": stats.get("rejected_linear"),
        "overpass_error": stats.get("overpass_error"),
        "ok": True,
    }
    # Soft-fail during scan keeps clusters; for refilter, zero docks + error is a failure.
    if int(result.get("dock_points") or 0) == 0 and result.get("overpass_error"):
        result["ok"] = False
    return result
