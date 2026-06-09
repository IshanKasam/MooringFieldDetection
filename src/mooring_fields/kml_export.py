"""Export mooring field clusters to KML."""

from __future__ import annotations

from pathlib import Path

from mooring_fields.cluster_fields import MooringFieldCluster


def clusters_to_kml(
    clusters: list[MooringFieldCluster],
    output_path: Path,
    document_name: str = "Mooring field detections",
) -> Path:
    placemarks = []
    for i, cluster in enumerate(clusters, start=1):
        placemarks.append(
            f"""  <Placemark>
    <name>Field {i} ({cluster.boat_count} boats)</name>
    <description>confidence={cluster.mean_confidence:.2f}</description>
    <Point>
      <coordinates>{cluster.lon},{cluster.lat},0</coordinates>
    </Point>
  </Placemark>"""
        )

    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
<Document>
  <name>{document_name}</name>
{chr(10).join(placemarks)}
</Document>
</kml>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(kml, encoding="utf-8")
    return output_path
