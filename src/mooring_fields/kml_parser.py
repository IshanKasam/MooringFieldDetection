"""Parse mooring field KML into structured site records."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path

from mooring_fields.paths import KML_PATH, SITES_JSON

KML_NS = {
    "kml": "http://www.opengis.net/kml/2.2",
    "gx": "http://www.google.com/kml/ext/2.2",
}


@dataclass
class LookAt:
    longitude: float | None = None
    latitude: float | None = None
    altitude: float | None = None
    heading: float | None = None
    tilt: float | None = None
    fovy: float | None = None
    range: float | None = None


@dataclass
class Site:
    id: str
    name: str
    longitude: float
    latitude: float
    altitude: float | None
    look_at: LookAt

    @property
    def slug(self) -> str:
        safe = re.sub(r"[^\w\-]+", "_", self.name.strip())
        return f"{safe}_{self.id[:8]}"


def _text(element: ET.Element | None, tag: str, ns: str = "kml") -> float | None:
    if element is None:
        return None
    child = element.find(f"{ns}:{tag}", KML_NS)
    if child is None or child.text is None:
        return None
    return float(child.text)


def _parse_coordinates(coords_text: str) -> tuple[float, float, float | None]:
    parts = [p.strip() for p in coords_text.strip().split(",")]
    lon = float(parts[0])
    lat = float(parts[1])
    alt = float(parts[2]) if len(parts) > 2 else None
    return lon, lat, alt


def parse_kml(kml_path: Path | None = None) -> list[Site]:
    """Parse placemarks from KML, including LookAt camera metadata."""
    path = kml_path or KML_PATH
    tree = ET.parse(path)
    root = tree.getroot()
    sites: list[Site] = []

    for placemark in root.findall(".//kml:Placemark", KML_NS):
        site_id = placemark.get("id")
        if not site_id:
            continue

        name_el = placemark.find("kml:name", KML_NS)
        name = name_el.text.strip() if name_el is not None and name_el.text else site_id

        point = placemark.find("kml:Point/kml:coordinates", KML_NS)
        if point is None or point.text is None:
            continue
        lon, lat, alt = _parse_coordinates(point.text)

        look_at_el = placemark.find("kml:LookAt", KML_NS)
        look_at = LookAt(
            longitude=_text(look_at_el, "longitude"),
            latitude=_text(look_at_el, "latitude"),
            altitude=_text(look_at_el, "altitude"),
            heading=_text(look_at_el, "heading"),
            tilt=_text(look_at_el, "tilt"),
            fovy=_text(look_at_el, "fovy", ns="gx") or _text(look_at_el, "fovy"),
            range=_text(look_at_el, "range"),
        )

        sites.append(
            Site(
                id=site_id,
                name=name,
                longitude=lon,
                latitude=lat,
                altitude=alt,
                look_at=look_at,
            )
        )

    return sites


def sites_to_dicts(sites: list[Site]) -> list[dict]:
    return [asdict(site) for site in sites]


def write_sites_json(sites: list[Site], output_path: Path | None = None) -> Path:
    output = output_path or SITES_JSON
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {"count": len(sites), "sites": sites_to_dicts(sites)}
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output


def load_sites_json(path: Path | None = None) -> list[Site]:
    source = path or SITES_JSON
    data = json.loads(source.read_text(encoding="utf-8"))
    sites: list[Site] = []
    for row in data["sites"]:
        look_at = LookAt(**row["look_at"])
        sites.append(
            Site(
                id=row["id"],
                name=row["name"],
                longitude=row["longitude"],
                latitude=row["latitude"],
                altitude=row.get("altitude"),
                look_at=look_at,
            )
        )
    return sites
