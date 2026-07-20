import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { GeoJsonFeatureCollection } from "../api/types";
import { useSelection } from "../store/selection";

type Props = {
  geojson: GeoJsonFeatureCollection | undefined;
};

const ESRI_SATELLITE = {
  version: 8 as const,
  sources: {
    esri: {
      type: "raster" as const,
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Tiles © Esri",
    },
  },
  layers: [
    {
      id: "esri",
      type: "raster" as const,
      source: "esri",
    },
  ],
};

export function FieldMap({ geojson }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const selectedFieldId = useSelection((s) => s.selectedFieldId);
  const setField = useSelection((s) => s.setField);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: ESRI_SATELLITE,
      center: [-70.85, 42.5],
      zoom: 9,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !geojson) return;

    const ensure = () => {
      if (!map.getSource("fields")) {
        map.addSource("fields", {
          type: "geojson",
          data: geojson,
          cluster: true,
          clusterMaxZoom: 12,
          clusterRadius: 44,
        });
        map.addLayer({
          id: "clusters",
          type: "circle",
          source: "fields",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": "#0ea5e9",
            "circle-radius": ["step", ["get", "point_count"], 16, 10, 22, 50, 28],
            "circle-opacity": 0.85,
          },
        });
        map.addLayer({
          id: "cluster-count",
          type: "symbol",
          source: "fields",
          filter: ["has", "point_count"],
          layout: {
            "text-field": "{point_count_abbreviated}",
            "text-size": 12,
          },
          paint: { "text-color": "#ffffff" },
        });
        map.addLayer({
          id: "unclustered",
          type: "circle",
          source: "fields",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-color": [
              "case",
              ["==", ["get", "approved"], 1],
              "#22c55e",
              ["==", ["get", "needs_review"], 1],
              "#f59e0b",
              "#38bdf8",
            ],
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["coalesce", ["get", "boat_count"], 1],
              1,
              6,
              50,
              16,
            ],
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#0f172a",
          },
        });

        map.on("click", "clusters", (e) => {
          const features = map.queryRenderedFeatures(e.point, {
            layers: ["clusters"],
          });
          const clusterId = features[0]?.properties?.cluster_id;
          const source = map.getSource("fields") as maplibregl.GeoJSONSource;
          if (clusterId == null) return;
          source.getClusterExpansionZoom(clusterId).then((zoom) => {
            const geom = features[0].geometry as {
              type: string;
              coordinates: [number, number];
            };
            map.easeTo({ center: geom.coordinates, zoom });
          });
        });

        map.on("click", "unclustered", (e) => {
          const f = e.features?.[0];
          if (!f) return;
          const props = f.properties ?? {};
          const fieldId = Number(props.field_id);
          const prospectId =
            props.prospect_id != null ? Number(props.prospect_id) : null;
          setField(fieldId, prospectId);
          const geom = f.geometry as { type: string; coordinates: [number, number] };
          const coords = geom.coordinates.slice() as [number, number];
          const html = `
            <strong>${props.harbor_name || props.location_name || "Field " + fieldId}</strong><br/>
            Boats: ${props.boat_count ?? "—"}<br/>
            Controller: ${props.controller || "—"}<br/>
            Phone: ${props.phone || "—"}<br/>
            ${props.website ? `<a href="${props.website}" target="_blank" rel="noreferrer">Website</a><br/>` : ""}
            ${props.needs_review == 1 ? '<span style="color:#f59e0b">Needs review</span>' : ""}
          `;
          new maplibregl.Popup().setLngLat(coords).setHTML(html).addTo(map);
        });

        map.on("mouseenter", "unclustered", () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", "unclustered", () => {
          map.getCanvas().style.cursor = "";
        });
      } else {
        (map.getSource("fields") as maplibregl.GeoJSONSource).setData(geojson);
      }

      if (geojson.features.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        geojson.features.forEach((f) => {
          bounds.extend(f.geometry.coordinates as [number, number]);
        });
        if (!bounds.isEmpty()) {
          map.fitBounds(bounds, { padding: 48, maxZoom: 12 });
        }
      }
    };

    if (map.isStyleLoaded()) ensure();
    else map.once("load", ensure);
  }, [geojson, setField]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || selectedFieldId == null || !geojson) return;
    const feature = geojson.features.find(
      (f) => Number(f.properties.field_id) === selectedFieldId,
    );
    if (!feature) return;
    map.easeTo({
      center: feature.geometry.coordinates as [number, number],
      zoom: Math.max(map.getZoom(), 12),
    });
  }, [selectedFieldId, geojson]);

  return <div className="map-root" ref={containerRef} />;
}
