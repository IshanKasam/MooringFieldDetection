import { useMemo, useState } from "react";
import { api } from "../api/client";
import {
  useEnrich,
  useEnrichRuns,
  useScans,
  useStats,
} from "../hooks/useFields";

export function Toolbar() {
  const { data: stats } = useStats();
  const { data: scans } = useScans();
  const { data: runs } = useEnrichRuns();
  const enrich = useEnrich();
  const [scanA, setScanA] = useState<number | "">("");
  const [scanB, setScanB] = useState<number | "">("");
  const [diffText, setDiffText] = useState<string>("");

  const scanOptions = useMemo(() => scans ?? [], [scans]);

  async function compare() {
    if (scanA === "" || scanB === "") return;
    const d = await api.scanDiff(Number(scanA), Number(scanB));
    setDiffText(
      `Scan ${d.scan_a}: ${d.fields_a} fields → Scan ${d.scan_b}: ${d.fields_b} fields (Δ ${d.delta >= 0 ? "+" : ""}${d.delta})`,
    );
  }

  return (
    <div className="toolbar">
      <div className="stats">
        <span>
          <strong>{stats?.fields ?? "—"}</strong> fields
        </span>
        <span>
          <strong>{stats?.boats ?? "—"}</strong> boats
        </span>
        <span>
          <strong>{stats?.prospects ?? "—"}</strong> prospects
        </span>
        <span className="warn">
          <strong>{stats?.needs_review ?? "—"}</strong> need review
        </span>
        <span className="ok">
          <strong>{stats?.approved ?? "—"}</strong> approved
        </span>
      </div>
      <div className="actions">
        <a className="button" href={api.exportUrl()}>
          Export Excel
        </a>
        <button
          type="button"
          disabled={enrich.isPending}
          onClick={() => enrich.mutate({ step: "places", limit: 5 })}
        >
          Enrich places
        </button>
        <button
          type="button"
          disabled={enrich.isPending}
          onClick={() => enrich.mutate({ step: "research", limit: 5 })}
        >
          Enrich research
        </button>
        <select
          value={scanA}
          onChange={(e) =>
            setScanA(e.target.value ? Number(e.target.value) : "")
          }
        >
          <option value="">Scan A</option>
          {scanOptions.map((s) => (
            <option key={s.id} value={s.id}>
              #{s.id} ({s.field_count})
            </option>
          ))}
        </select>
        <select
          value={scanB}
          onChange={(e) =>
            setScanB(e.target.value ? Number(e.target.value) : "")
          }
        >
          <option value="">Scan B</option>
          {scanOptions.map((s) => (
            <option key={s.id} value={s.id}>
              #{s.id} ({s.field_count})
            </option>
          ))}
        </select>
        <button type="button" onClick={() => void compare()}>
          Diff scans
        </button>
      </div>
      {diffText && <p className="diff muted">{diffText}</p>}
      {enrich.isSuccess && (
        <p className="ok">Enrichment queued — check runs below.</p>
      )}
      {runs && runs.length > 0 && (
        <details className="runs">
          <summary>Recent enrichment runs ({runs.length})</summary>
          <ul>
            {runs.slice(0, 5).map((r) => (
              <li key={r.id}>
                #{r.id} {r.provider} — processed {r.fields_processed}
                {r.finished_at ? ` · done ${r.finished_at}` : " · running/queued"}
                {r.notes ? ` · ${r.notes}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
