import { useMemo, useState } from "react";
import type { FieldRow } from "../api/types";

export type TableFilters = {
  query: string;
  harbor: string;
  minBoats: number;
  minConfidence: number;
  needsReviewOnly: boolean;
  country: string;
};

type Props = {
  rows: FieldRow[];
  filters: TableFilters;
  onChange: (next: TableFilters) => void;
};

export function defaultFilters(): TableFilters {
  return {
    query: "",
    harbor: "",
    minBoats: 0,
    minConfidence: 0,
    needsReviewOnly: false,
    country: "",
  };
}

export function applyFilters(rows: FieldRow[], f: TableFilters): FieldRow[] {
  const q = f.query.trim().toLowerCase();
  return rows.filter((r) => {
    if (f.minBoats && r.boat_count < f.minBoats) return false;
    if (f.minConfidence && (r.confidence ?? 0) < f.minConfidence) return false;
    if (f.needsReviewOnly && !r.needs_review) return false;
    if (f.harbor && (r.harbor_name || "") !== f.harbor) return false;
    if (f.country && (r.country || "") !== f.country) return false;
    if (!q) return true;
    const hay = [
      r.location_name,
      r.controller,
      r.harbor_name,
      r.phone,
      r.email,
      r.website,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

export function Filters({ rows, filters, onChange }: Props) {
  const harbors = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => {
      if (r.harbor_name) set.add(r.harbor_name);
    });
    return Array.from(set).sort();
  }, [rows]);

  const countries = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => {
      if (r.country) set.add(r.country);
    });
    return Array.from(set).sort();
  }, [rows]);

  const [local, setLocal] = useState(filters);

  function patch(partial: Partial<TableFilters>) {
    const next = { ...local, ...partial };
    setLocal(next);
    onChange(next);
  }

  return (
    <div className="filters">
      <input
        type="search"
        placeholder="Search location, controller, phone…"
        value={local.query}
        onChange={(e) => patch({ query: e.target.value })}
      />
      <select
        value={local.harbor}
        onChange={(e) => patch({ harbor: e.target.value })}
      >
        <option value="">All harbors</option>
        {harbors.map((h) => (
          <option key={h} value={h}>
            {h}
          </option>
        ))}
      </select>
      <select
        value={local.country}
        onChange={(e) => patch({ country: e.target.value })}
      >
        <option value="">All countries</option>
        {countries.map((c) => (
          <option key={c} value={c}>
            {c}
          </option>
        ))}
      </select>
      <label>
        Min boats
        <input
          type="number"
          min={0}
          value={local.minBoats}
          onChange={(e) => patch({ minBoats: Number(e.target.value) || 0 })}
        />
      </label>
      <label>
        Min confidence
        <input
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={local.minConfidence}
          onChange={(e) =>
            patch({ minConfidence: Number(e.target.value) || 0 })
          }
        />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={local.needsReviewOnly}
          onChange={(e) => patch({ needsReviewOnly: e.target.checked })}
        />
        Needs review
      </label>
    </div>
  );
}
