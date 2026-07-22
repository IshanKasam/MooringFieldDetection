import { useMemo, useState } from "react";
import { api } from "../api/client";
import {
  useEnrich,
  useEnrichRuns,
  useScans,
  useStats,
} from "../hooks/useFields";
import { ScanPanel } from "./ScanPanel";

export function Toolbar() {
  const { data: stats } = useStats();
  const { data: scans } = useScans();
  const { data: runs } = useEnrichRuns();
  const enrich = useEnrich();
  const [scanA, setScanA] = useState<number | "">("");
  const [scanB, setScanB] = useState<number | "">("");
  const [diffText, setDiffText] = useState<string>("");
  const [enrichLimit, setEnrichLimit] = useState(5);

  const scanOptions = useMemo(() => scans ?? [], [scans]);
  const running = runs?.some((r) => !r.finished_at) ?? false;

  async function compare() {
    if (scanA === "" || scanB === "") return;
    try {
      const d = await api.scanDiff(Number(scanA), Number(scanB));
      setDiffText(
        `Scan ${d.scan_a}: ${d.fields_a} fields → Scan ${d.scan_b}: ${d.fields_b} fields (Δ ${d.delta >= 0 ? "+" : ""}${d.delta})`,
      );
    } catch (e) {
      setDiffText(`Diff failed: ${e instanceof Error ? e.message : String(e)}`);
    }
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
      <ScanPanel />
      <div className="actions">
        <a className="button" href={api.exportUrl()}>
          Export Excel
        </a>
        <label className="muted">
          Limit{" "}
          <input
            type="number"
            min={1}
            max={100}
            value={enrichLimit}
            onChange={(e) => setEnrichLimit(Number(e.target.value) || 5)}
            style={{ width: "4rem" }}
          />
        </label>
        <button
          type="button"
          disabled={enrich.isPending || running}
          onClick={() => enrich.mutate({ step: "places", limit: enrichLimit })}
        >
          Enrich places
        </button>
        <button
          type="button"
          disabled={enrich.isPending || running}
          onClick={() => enrich.mutate({ step: "research", limit: enrichLimit })}
        >
          Enrich research
        </button>
        <button
          type="button"
          disabled={enrich.isPending || running}
          onClick={() =>
            enrich.mutate({ step: "supply_chain", limit: enrichLimit })
          }
        >
          Enrich supply chain
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
      {enrich.isError && (
        <p className="warn">
          Enrich queue failed:{" "}
          {enrich.error instanceof Error
            ? enrich.error.message
            : String(enrich.error)}
        </p>
      )}
      {runs && runs.length > 0 && (
        <details className="runs">
          <summary>Recent enrichment runs ({runs.length})</summary>
          <ul>
            {runs.slice(0, 5).map((r) => (
              <li key={r.id}>
                #{r.id} {r.provider} — processed {r.fields_processed}
                {r.finished_at
                  ? ` · done ${r.finished_at}`
                  : " · running/queued"}
                {r.notes ? ` · ${r.notes}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
