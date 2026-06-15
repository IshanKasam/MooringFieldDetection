"""Export mooring field clusters to KML."""

from __future__ import annotations

from pathlib import Path

from mooring_fields.cluster_fields import MooringFieldCluster


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def clusters_to_kml(
    clusters: list[MooringFieldCluster],
    output_path: Path,
    document_name: str = "Mooring field detections",
    names: dict | None = None,
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
