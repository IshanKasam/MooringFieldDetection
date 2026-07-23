import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useMemo, useState } from "react";
import type { FieldRow } from "../api/types";
import { useSelection } from "../store/selection";
import { ApproveToggle } from "./ApproveToggle";

type Props = {
  rows: FieldRow[];
};

function csvEscape(v: unknown): string {
  const s = v == null ? "" : String(v);
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

export function FieldTable({ rows }: Props) {
  const selectedFieldId = useSelection((s) => s.selectedFieldId);
  const setField = useSelection((s) => s.setField);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "boat_count", desc: true },
  ]);

  const columns = useMemo<ColumnDef<FieldRow>[]>(
    () => [
      { accessorKey: "field_id", header: "Field", size: 70 },
      {
        accessorKey: "location_name",
        header: "Location",
        size: 310,
        cell: ({ row }) => (
          <div className="location-cell">
            <strong>{row.original.location_name || "Unresolved location"}</strong>
            <small>
              {row.original.latitude.toFixed(5)}, {row.original.longitude.toFixed(5)}
            </small>
          </div>
        ),
      },
      { accessorKey: "state", header: "State", size: 80, cell: (c) => c.getValue() || "—" },
      {
        accessorKey: "country",
        header: "Country",
        size: 130,
        cell: (c) => c.getValue() || "—",
      },
      { accessorKey: "boat_count", header: "Boats", size: 75 },
      {
        accessorKey: "mean_confidence",
        header: "Detection",
        size: 90,
        cell: (c) => {
          const v = c.getValue() as number | null;
          return v == null ? "—" : `${Math.round(v * 100)}%`;
        },
      },
      {
        accessorKey: "harbor_name",
        header: "Harbor",
        size: 180,
        cell: (c) => c.getValue() || "—",
      },
      {
        accessorKey: "controller",
        header: "Controller",
        size: 200,
        cell: (c) => c.getValue() || "—",
      },
      {
        accessorKey: "phone",
        header: "Phone",
        cell: (c) => c.getValue() || "—",
      },
      {
        accessorKey: "operator_type",
        header: "Type",
        size: 125,
        cell: (c) => c.getValue() || "—",
      },
      {
        accessorKey: "email",
        header: "Email",
        cell: (c) => c.getValue() || "—",
      },
      {
        accessorKey: "website",
        header: "Website",
        cell: (c) => {
          const v = c.getValue() as string | null;
          if (!v) return "—";
          return (
            <a href={v} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
              {v.replace(/^https?:\/\//, "").slice(0, 32)}
            </a>
          );
        },
      },
      {
        accessorKey: "confidence",
        header: "Research",
        size: 85,
        cell: (c) => {
          const v = c.getValue() as number | null;
          return v == null ? "—" : `${Math.round(v * 100)}%`;
        },
      },
      {
        accessorKey: "enrichment_status",
        header: "Status",
        size: 120,
        cell: (c) => {
          const v = (c.getValue() as string | null) || "pending";
          return <span className={`status-badge status-${v}`}>{v}</span>;
        },
      },
      {
        id: "approved",
        header: "Approved",
        size: 90,
        cell: ({ row }) => <ApproveToggle row={row.original} />,
      },
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  function downloadCsv() {
    const cols = [
      "field_id",
      "location_name",
      "state",
      "country",
      "boat_count",
      "mean_confidence",
      "harbor_name",
      "controller",
      "phone",
      "email",
      "website",
      "operator_type",
      "confidence",
      "enrichment_status",
      "approved",
    ] as const;
    const lines = [
      cols.join(","),
      ...rows.map((r) => cols.map((c) => csvEscape(r[c])).join(",")),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "mooring_fields.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="table-wrap">
      <div className="table-toolbar">
        <span className="muted">{rows.length} rows</span>
        <button type="button" onClick={downloadCsv}>
          Download CSV
        </button>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th
                    key={h.id}
                    style={{ width: h.getSize() }}
                    onClick={h.column.getToggleSortingHandler()}
                  >
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    {{ asc: " ↑", desc: " ↓" }[h.column.getIsSorted() as string] ??
                      ""}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const selected = row.original.field_id === selectedFieldId;
              return (
                <tr
                  key={row.id}
                  className={selected ? "selected" : undefined}
                  onClick={() =>
                    setField(row.original.field_id, row.original.prospect_id)
                  }
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
