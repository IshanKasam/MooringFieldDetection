import { FieldDetailDrawer } from "../components/FieldDetailDrawer";
import { FieldMap } from "../components/FieldMap";
import { useGeojson } from "../hooks/useFields";
import { useSelection } from "../store/selection";

export function MapPage() {
  const { data, isLoading, error } = useGeojson();
  const selectedProspectId = useSelection((s) => s.selectedProspectId);
  const clear = useSelection((s) => s.clear);

  return (
    <div className="page map-page">
      <div className="page-main map-panel">
        {isLoading && <p className="map-overlay muted">Loading map…</p>}
        {error && (
          <p className="map-overlay error">{(error as Error).message}</p>
        )}
        <FieldMap geojson={data} />
      </div>
      {selectedProspectId != null && (
        <FieldDetailDrawer
          prospectId={selectedProspectId}
          onClose={() => clear()}
        />
      )}
    </div>
  );
}
