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
      { accessorKey: "field_id", header: "ID", size: 60 },
      {
        accessorKey: "location_name",
        header: "Location",
        cell: (c) => c.getValue() || "—",
      },
      { accessorKey: "boat_count", header: "Boats", size: 70 },
      {
        accessorKey: "controller",
        header: "Controller",
        cell: (c) => c.getValue() || "—",
      },
      {
        accessorKey: "phone",
        header: "Phone",
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
        accessorKey: "harbor_name",
        header: "Harbor",
        cell: (c) => c.getValue() || "—",
      },
      {
        accessorKey: "confidence",
        header: "Conf.",
        size: 70,
        cell: (c) => {
          const v = c.getValue() as number | null;
          return v == null ? "—" : v.toFixed(2);
        },
      },
      {
        accessorKey: "enrichment_status",
        header: "Status",
        size: 100,
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
      "boat_count",
      "controller",
      "phone",
      "email",
      "website",
      "harbor_name",
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
