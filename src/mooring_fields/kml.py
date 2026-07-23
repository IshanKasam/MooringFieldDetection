"""Unified KML parsing, splitting, and export module."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from sklearn.cluster import KMeans

from mooring_fields.paths import CONFIG_DIR, KML_PATH, SITES_JSON

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


def sites_to_dicts(sites: list[Site]) -> list[dict[str, Any]]:
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


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def clusters_to_kml(
    clusters: list[Any],
    output_path: Path,
    document_name: str = "Mooring field detections",
    names: dict[int, str] | None = None,
    include_boats: bool = True,
) -> Path:
    names = names or {}
    placemarks = []
    for i, cluster in enumerate(clusters, start=1):
        location_name = names.get(id(cluster))
        title = f"{location_name} ({cluster.boat_count} boats)" if location_name else f"Field {i} ({cluster.boat_count} boats)"
        desc = f"boats={cluster.boat_count}, confidence={cluster.mean_confidence:.2f}"
        if location_name:
            desc += f", location={_escape(location_name)}"

        placemarks.append(
            f"""  <Placemark>
    <name>{_escape(title)}</name>
    <description>{desc}</description>
    <Point>
      <coordinates>{cluster.lon},{cluster.lat},0</coordinates>
    </Point>
  </Placemark>"""
        )

        if include_boats and getattr(cluster, "boats", None):
            boat_marks = []
            for j, boat in enumerate(cluster.boats, start=1):
                boat_marks.append(
                    f"""    <Placemark>
      <name>Boat {j}</name>
      <description>confidence={boat.confidence:.2f}</description>
      <Point>
        <coordinates>{boat.lon},{boat.lat},0</coordinates>
      </Point>
    </Placemark>"""
                )
            placemarks.append(
                f"""  <Folder>
    <name>Boats in {_escape(title)}</name>
{chr(10).join(boat_marks)}
  </Folder>"""
            )

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{_escape(document_name)}</name>
{chr(10).join(placemarks)}
</Document>
</kml>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(kml, encoding="utf-8")
    return output_path


def geographic_split(
    sites: list[Site],
    train_ratio: float = 0.8,
    random_seed: int = 42,
    n_clusters: int | None = None,
) -> tuple[list[str], list[str]]:
    """Split sites by geographic clusters."""
    if not sites:
        return [], []

    n_clusters = n_clusters or min(max(5, int(len(sites) ** 0.5)), len(sites))
    coords = [[s.latitude, s.longitude] for s in sites]
    labels = KMeans(n_clusters=n_clusters, random_state=random_seed, n_init=10).fit_predict(coords)

    train_ids: list[str] = []
    val_ids: list[str] = []

    for cluster_id in range(n_clusters):
        cluster_sites = [s for s, lbl in zip(sites, labels) if lbl == cluster_id]
        cluster_sites.sort(key=lambda s: s.id)
        n_val = max(1, round(len(cluster_sites) * (1 - train_ratio)))
        if len(cluster_sites) <= 2:
            n_val = 1
        val_ids.extend(s.id for s in cluster_sites[:n_val])
        train_ids.extend(s.id for s in cluster_sites[n_val:])

    return train_ids, val_ids


def update_split_config(train_ids: list[str], val_ids: list[str], config_path: Path | None = None) -> Path:
    path = config_path or CONFIG_DIR / "split.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["train_ids"] = train_ids
    data["val_ids"] = val_ids
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8")
    return path


def run_parse_and_split(kml_path: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    """Parse a KML and write sites.json + update split config."""
    sites = parse_kml(kml_path)

    sites_out = (output_dir / "sites.json") if output_dir else None
    write_sites_json(sites, sites_out)

    if output_dir is None:
        config_path = CONFIG_DIR / "split.yaml"
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        train_ids, val_ids = geographic_split(
            sites,
            train_ratio=cfg.get("train_ratio", 0.8),
            random_seed=cfg.get("random_seed", 42),
        )
        update_split_config(train_ids, val_ids)
        return {
            "sites_count": len(sites),
            "train_count": len(train_ids),
            "val_count": len(val_ids),
            "sites_json": str(SITES_JSON),
        }

    return {
        "sites_count": len(sites),
        "sites_json": str(output_dir / "sites.json"),
    }


def sites_for_split(sites: list[Site], split: str) -> list[Site]:
    cfg = yaml.safe_load((CONFIG_DIR / "split.yaml").read_text(encoding="utf-8"))
    ids = set(cfg["train_ids"] if split == "train" else cfg["val_ids"])
    return [s for s in sites if s.id in ids]
