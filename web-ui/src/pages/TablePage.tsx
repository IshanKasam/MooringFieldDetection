import { useMemo, useState } from "react";
import { FieldDetailDrawer } from "../components/FieldDetailDrawer";
import { FieldTable } from "../components/FieldTable";
import {
  applyFilters,
  defaultFilters,
  Filters,
  type TableFilters,
} from "../components/Filters";
import { useTable } from "../hooks/useFields";
import { useSelection } from "../store/selection";

export function TablePage() {
  const { data, isLoading, error } = useTable();
  const [filters, setFilters] = useState<TableFilters>(defaultFilters());
  const selectedProspectId = useSelection((s) => s.selectedProspectId);
  const selectedFieldId = useSelection((s) => s.selectedFieldId);
  const clear = useSelection((s) => s.clear);

  const filtered = useMemo(
    () => applyFilters(data ?? [], filters),
    [data, filters],
  );

  const showDrawer = selectedFieldId != null || selectedProspectId != null;

  return (
    <div className="page table-page">
      <div className="page-main">
        {isLoading && <p className="muted">Loading table…</p>}
        {error && <p className="error">{(error as Error).message}</p>}
        {data && (
          <>
            <Filters rows={data} filters={filters} onChange={setFilters} />
            <FieldTable rows={filtered} />
          </>
        )}
      </div>
      {showDrawer && (
        <FieldDetailDrawer
          prospectId={selectedProspectId}
          fieldId={selectedFieldId}
          onClose={() => clear()}
        />
      )}
    </div>
  );
}
