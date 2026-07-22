import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { JobRow, MapsQuota, ScanRegion } from "../api/types";
import { invalidateFieldQueries } from "../hooks/useFields";
import { useQueryClient } from "@tanstack/react-query";

export function ScanPanel() {
  const qc = useQueryClient();
  const [regions, setRegions] = useState<ScanRegion[]>([]);
  const [quota, setQuota] = useState<MapsQuota | null>(null);
  const [regionId, setRegionId] = useState("");
  const [maxSites, setMaxSites] = useState(160);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<JobRow | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const namedRegions = useMemo(
    () => regions.filter((r) => r.kind === "region"),
    [regions],
  );

  useEffect(() => {
    void api.regions().then(setRegions).catch(() => setRegions([]));
    void api.mapsQuota().then(setQuota).catch(() => setQuota(null));
  }, []);

  useEffect(() => {
    if (!activeJob || activeJob.finished_at) return;
    const t = setInterval(() => {
      void api
        .job(activeJob.id)
        .then((j) => {
          setActiveJob(j);
          if (j.finished_at) {
            void api.mapsQuota().then(setQuota).catch(() => undefined);
            if (j.status === "succeeded") {
              invalidateFieldQueries(qc);
              setMessage(
                `Scan #${j.id} done — ${(j.result as { discovered_clusters?: number })?.discovered_clusters ?? "?"} fields`,
              );
            } else if (j.status === "failed") {
              setError(
                String(
                  (j.result as { error?: string })?.error || "Scan failed",
                ),
              );
            } else if (j.status === "cancelled") {
              setMessage(`Scan #${j.id} cancelled`);
            }
            setBusy(false);
          }
        })
        .catch((e) => setError(String(e)));
    }, 3000);
    return () => clearInterval(t);
  }, [activeJob, qc]);

  async function startScan() {
    setError(null);
    setMessage(null);
    if (!regionId) {
      setError("Pick a coastline region");
      return;
    }
    setBusy(true);
    try {
      const selected = regions.find((r) => r.id === regionId);
      const body =
        selected?.kind === "state"
          ? { state: regionId, max_sites: maxSites }
          : { region: regionId, max_sites: maxSites };
      const res = await api.startScan(body);
      const jobId = (res.detail as { job_id?: number })?.job_id;
      if (jobId == null) throw new Error("No job_id returned");
      const job = await api.job(jobId);
      setActiveJob(job);
      setMessage(`Scan job #${jobId} queued`);
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function cancel() {
    if (!activeJob) return;
    try {
      await api.cancelJob(activeJob.id);
      setMessage(`Cancel requested for job #${activeJob.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const progress = activeJob?.progress as { step?: string; sites?: number } | null;

  return (
    <div className="scan-panel">
      <div className="actions">
        <strong>Scan coast</strong>
        <select
          value={regionId}
          onChange={(e) => setRegionId(e.target.value)}
          disabled={busy}
        >
          <option value="">Select region…</option>
          {namedRegions.map((r) => (
            <option key={r.id} value={r.id}>
              {r.id}
            </option>
          ))}
          <optgroup label="States">
            {regions
              .filter((r) => r.kind === "state")
              .map((r) => (
                <option key={r.id} value={r.id}>
                  {r.id}
                </option>
              ))}
          </optgroup>
        </select>
        <label className="muted">
          Max sites{" "}
          <input
            type="number"
            min={1}
            max={160}
            value={maxSites}
            disabled={busy}
            onChange={(e) => setMaxSites(Number(e.target.value) || 160)}
            style={{ width: "4rem" }}
          />
        </label>
        <span className="muted">
          Maps today: {quota ? `${quota.remaining}/${quota.cap}` : "—"}
        </span>
        <button type="button" disabled={busy} onClick={() => void startScan()}>
          {busy ? "Scanning…" : "Start scan"}
        </button>
        {busy && activeJob && (
          <button type="button" onClick={() => void cancel()}>
            Cancel
          </button>
        )}
      </div>
      {progress?.step && (
        <p className="muted">
          Progress: {progress.step}
          {progress.sites != null ? ` · ${progress.sites} sites` : ""}
        </p>
      )}
      {message && <p className="ok">{message}</p>}
      {error && <p className="warn">{error}</p>}
    </div>
  );
}
