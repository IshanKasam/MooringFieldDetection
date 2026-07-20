"""Generate scan candidate sites from NOAA Anchorages + OSM marina/mooring points.

NOAA ESI geodatabases (TYPE=MO/M) are not available as a lightweight nationwide
REST API. This module uses the same *intent* via queryable HTTP sources:

- NOAA MarineCadastre / Hosted Anchorages FeatureServer (official NOAA)
- OpenStreetMap Overpass: leisure=marina and mooring / seamark mooring

Types map to the ESI vocabulary:
  M  = marina
  MO = mooring / anchorage
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import httpx

from mooring_fields.geo_utils import haversine_m

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
NOAA_ANCHORAGES_URL = (
    "https://coast.noaa.gov/arcgis/rest/services/Hosted/Anchorages/"
    "FeatureServer/0/query"
)

# Approximate coastal bboxes (west, south, east, north) for target states.
STATE_BBOXES: dict[str, tuple[float, float, float, float]] = {
    "ME": (-71.1, 43.0, -66.9, 47.5),
    "NH": (-71.0, 42.8, -70.5, 43.2),
    "MA": (-71.5, 41.2, -69.8, 42.9),
    "RI": (-71.9, 41.1, -71.1, 41.9),
    "CT": (-73.7, 40.9, -71.8, 41.6),
    "NY": (-74.3, 40.4, -71.8, 41.4),  # LI / NY harbor focus
    "NJ": (-75.6, 38.8, -73.9, 40.6),
    "FL": (-87.6, 24.4, -79.9, 31.1),
    "TX": (-97.4, 25.8, -93.7, 30.0),
    "CA": (-124.5, 32.5, -116.8, 42.1),
    "WA": (-124.9, 46.2, -122.0, 49.0),
    "OR": (-124.7, 41.9, -123.8, 46.3),
}

DEFAULT_TYPES = ("MO", "M")
USER_AGENT = "MooringFieldDetection/1.0 (educational research)"


@dataclass
class Candidate:
    latitude: float
    longitude: float
    name: str
    source_type: str  # MO | M
    source: str  # noaa_anchorage | osm_marina | osm_mooring
    source_id: str


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16].upper()
    return digest


def _http_client(timeout: float = 90.0) -> httpx.Client:
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )


def fetch_noaa_anchorages(
    bbox: tuple[float, float, float, float],
    *,
    client: httpx.Client | None = None,
) -> list[Candidate]:
    """Fetch NOAA Hosted Anchorages polygons; use returned centroids as MO points."""
    west, south, east, north = bbox
    own = client is None
    client = client or _http_client()
    try:
        features: list[dict] = []
        offset = 0
        page_size = 1000
        while True:
            resp = client.get(
                NOAA_ANCHORAGES_URL,
                params={
                    "where": "1=1",
                    "geometry": f"{west},{south},{east},{north}",
                    "geometryType": "esriGeometryEnvelope",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "outFields": "objectid,anchoragename,anchoragetype,location",
                    "returnGeometry": "true",
                    "returnCentroid": "true",
                    "outSR": "4326",
                    "resultOffset": str(offset),
                    "resultRecordCount": str(page_size),
                    "f": "json",
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("error"):
                raise RuntimeError(f"NOAA Anchorages query failed: {payload['error']}")
            batch = payload.get("features") or []
            features.extend(batch)
            if len(batch) < page_size or not payload.get("exceededTransferLimit"):
                break
            offset += page_size

        out: list[Candidate] = []
        for feat in features:
            attrs = feat.get("attributes") or {}
            centroid = feat.get("centroid")
            if centroid and "x" in centroid and "y" in centroid:
                lon, lat = float(centroid["x"]), float(centroid["y"])
            else:
                # Fallback: average polygon ring if centroid missing
                rings = (feat.get("geometry") or {}).get("rings") or []
                if not rings or not rings[0]:
                    continue
                xs = [p[0] for p in rings[0]]
                ys = [p[1] for p in rings[0]]
                lon, lat = sum(xs) / len(xs), sum(ys) / len(ys)
            name = (
                attrs.get("anchoragename")
                or attrs.get("location")
                or f"Anchorage {attrs.get('objectid', '')}"
            )
            oid = str(attrs.get("objectid", f"{lat:.5f},{lon:.5f}"))
            out.append(
                Candidate(
                    latitude=lat,
                    longitude=lon,
                    name=str(name),
                    source_type="MO",
                    source="noaa_anchorage",
                    source_id=_stable_id("noaa", oid),
                )
            )
        return out
    finally:
        if own:
            client.close()


def _overpass_query(bbox: tuple[float, float, float, float], types: Sequence[str]) -> str:
    west, south, east, north = bbox
    # Overpass bbox order: south,west,north,east
    bb = f"({south},{west},{north},{east})"
    parts: list[str] = []
    if "M" in types:
        parts.extend(
            [
                f'node["leisure"="marina"]{bb};',
                f'way["leisure"="marina"]{bb};',
                f'relation["leisure"="marina"]{bb};',
                f'node["seamark:type"="harbour"]["seamark:harbour:category"~"marina"]{bb};',
            ]
        )
    if "MO" in types:
        parts.extend(
            [
                f'node["mooring"~"yes|buoy|pile|dolphin"]{bb};',
                f'way["mooring"~"yes|buoy|pile|dolphin"]{bb};',
                f'node["seamark:type"="mooring"]{bb};',
            ]
        )
    body = "\n  ".join(parts)
    return f"""
[out:json][timeout:90];
(
  {body}
);
out center tags;
"""


def fetch_osm_candidates(
    bbox: tuple[float, float, float, float],
    types: Sequence[str] = DEFAULT_TYPES,
    *,
    client: httpx.Client | None = None,
) -> list[Candidate]:
    """Fetch OSM marina (M) and mooring (MO) points via Overpass."""
    own = client is None
    client = client or _http_client(timeout=120.0)
    try:
        query = _overpass_query(bbox, types)
        resp = client.get(OVERPASS_URL, params={"data": query})
        resp.raise_for_status()
        elements = resp.json().get("elements") or []
        out: list[Candidate] = []
        for el in elements:
            tags = el.get("tags") or {}
            lat = el.get("lat")
            lon = el.get("lon")
            if lat is None or lon is None:
                center = el.get("center") or {}
                lat, lon = center.get("lat"), center.get("lon")
            if lat is None or lon is None:
                continue
            is_marina = tags.get("leisure") == "marina" or (
                tags.get("seamark:type") == "harbour"
                and "marina" in str(tags.get("seamark:harbour:category", ""))
            )
            is_mooring = ("mooring" in tags) or tags.get("seamark:type") == "mooring"
            if is_marina and "M" in types:
                source_type, source = "M", "osm_marina"
            elif is_mooring and "MO" in types:
                source_type, source = "MO", "osm_mooring"
            else:
                continue
            name = tags.get("name") or tags.get("seamark:name") or f"{source_type} {el.get('id')}"
            out.append(
                Candidate(
                    latitude=float(lat),
                    longitude=float(lon),
                    name=str(name),
                    source_type=source_type,
                    source=source,
                    source_id=_stable_id(source, str(el.get("type")), str(el.get("id"))),
                )
            )
        return out
    finally:
        if own:
            client.close()


def dedupe_candidates(
    candidates: Iterable[Candidate],
    *,
    radius_m: float = 150.0,
) -> list[Candidate]:
    """Greedy spatial dedupe. Prefer marinas (M) over moorings (MO) when close."""
    ranked = sorted(
        candidates,
        key=lambda c: (0 if c.source_type == "M" else 1, c.name.lower()),
    )
    kept: list[Candidate] = []
    for cand in ranked:
        if any(
            haversine_m(cand.latitude, cand.longitude, k.latitude, k.longitude) <= radius_m
            for k in kept
        ):
            continue
        kept.append(cand)
    return kept


def resolve_bbox(
    *,
    states: Sequence[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float]:
    if bbox is not None:
        return bbox
    if not states:
        raise ValueError("Provide --state and/or --bbox")
    boxes = []
    for st in states:
        key = st.strip().upper()
        if key not in STATE_BBOXES:
            raise ValueError(
                f"Unknown state '{st}'. Known: {', '.join(sorted(STATE_BBOXES))}"
            )
        boxes.append(STATE_BBOXES[key])
    west = min(b[0] for b in boxes)
    south = min(b[1] for b in boxes)
    east = max(b[2] for b in boxes)
    north = max(b[3] for b in boxes)
    return west, south, east, north


def collect_candidates(
    *,
    states: Sequence[str] | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    types: Sequence[str] = DEFAULT_TYPES,
    dedupe_meters: float = 150.0,
    max_sites: int | None = None,
    include_noaa: bool = True,
    include_osm: bool = True,
) -> dict:
    """Fetch, filter, dedupe candidates for a region."""
    types = tuple(t.strip().upper() for t in types)
    for t in types:
        if t not in ("MO", "M"):
            raise ValueError(f"Unsupported type '{t}' (use MO and/or M)")
    region_bbox = resolve_bbox(states=states, bbox=bbox)
    raw: list[Candidate] = []
    with _http_client(timeout=120.0) as client:
        if include_noaa and "MO" in types:
            raw.extend(fetch_noaa_anchorages(region_bbox, client=client))
        if include_osm:
            raw.extend(fetch_osm_candidates(region_bbox, types=types, client=client))

    deduped = dedupe_candidates(raw, radius_m=dedupe_meters)
    if max_sites is not None:
        deduped = deduped[: max(0, int(max_sites))]

    by_type = {"M": 0, "MO": 0}
    by_source: dict[str, int] = {}
    for c in deduped:
        by_type[c.source_type] = by_type.get(c.source_type, 0) + 1
        by_source[c.source] = by_source.get(c.source, 0) + 1

    return {
        "bbox": region_bbox,
        "states": list(states or []),
        "types": list(types),
        "raw_count": len(raw),
        "deduped_count": len(deduped),
        "by_type": by_type,
        "by_source": by_source,
        "dedupe_meters": dedupe_meters,
        "candidates": deduped,
        "estimated_tiles": len(deduped) * 5,  # center + N/S/E/W
    }


def write_candidates_kml(
    candidates: Sequence[Candidate],
    output_path: Path,
    *,
    document_name: str = "Mooring scan candidates",
) -> Path:
    """Write a KML that parse_kml() can read (Placemark id + Point coordinates)."""
    ns = "http://www.opengis.net/kml/2.2"
    ET.register_namespace("", ns)
    kml = ET.Element(f"{{{ns}}}kml")
    doc = ET.SubElement(kml, f"{{{ns}}}Document")
    ET.SubElement(doc, f"{{{ns}}}name").text = document_name

    for cand in candidates:
        pm = ET.SubElement(doc, f"{{{ns}}}Placemark", id=cand.source_id)
        safe_name = re.sub(r"\s+", " ", cand.name).strip() or cand.source_id
        ET.SubElement(pm, f"{{{ns}}}name").text = f"{cand.source_type}: {safe_name}"
        point = ET.SubElement(pm, f"{{{ns}}}Point")
        ET.SubElement(point, f"{{{ns}}}coordinates").text = (
            f"{cand.longitude:.7f},{cand.latitude:.7f},0"
        )
        look = ET.SubElement(pm, f"{{{ns}}}LookAt")
        ET.SubElement(look, f"{{{ns}}}longitude").text = f"{cand.longitude:.7f}"
        ET.SubElement(look, f"{{{ns}}}latitude").text = f"{cand.latitude:.7f}"
        ET.SubElement(look, f"{{{ns}}}altitude").text = "0"
        ET.SubElement(look, f"{{{ns}}}range").text = "800"
        ET.SubElement(look, f"{{{ns}}}tilt").text = "0"
        ET.SubElement(look, f"{{{ns}}}heading").text = "0"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(kml)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path
