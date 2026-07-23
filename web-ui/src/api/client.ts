import type {
  EnrichRun,
  FieldRow,
  GeoJsonFeatureCollection,
  ProspectDetail,
  ProspectUpdate,
  ScanDiff,
  ScanRow,
  Stats,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${path}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  stats: () => request<Stats>("/api/stats"),
  table: () => request<FieldRow[]>("/api/table"),
  geojson: () => request<GeoJsonFeatureCollection>("/api/fields.geojson"),
  prospect: (id: number) => request<ProspectDetail>(`/api/prospects/${id}`),
  updateProspect: (id: number, body: ProspectUpdate) =>
    request<ProspectDetail>(`/api/prospects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  approve: (id: number, approved: boolean) =>
    request<{ ok: boolean }>(`/api/prospects/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved }),
    }),
  scans: () => request<ScanRow[]>("/api/scans"),
  scanDiff: (a: number, b: number) =>
    request<ScanDiff>(`/api/scans/diff?a=${a}&b=${b}`),
  enrich: (step: string, limit = 5) =>
    request<{ ok: boolean }>("/api/enrich", {
      method: "POST",
      body: JSON.stringify({ step, limit, only_new: true }),
    }),
  enrichRuns: () => request<EnrichRun[]>("/api/enrich/runs"),
  exportUrl: () => `${BASE}/api/export.xlsx`,
  regions: () => request<import("./types").ScanRegion[]>("/api/regions"),
  mapsQuota: () => request<import("./types").MapsQuota>("/api/quota/maps"),
  jobs: (kind?: string) =>
    request<import("./types").JobRow[]>(
      kind ? `/api/jobs?kind=${encodeURIComponent(kind)}` : "/api/jobs",
    ),
  job: (id: number) => request<import("./types").JobRow>(`/api/jobs/${id}`),
  cancelJob: (id: number) =>
    request<{ ok: boolean }>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  startScan: (body: {
    region?: string;
    state?: string;
    bbox?: string;
    max_sites?: number;
    max_requests?: number;
    skip_fetch?: boolean;
  }) =>
    request<{ ok: boolean; detail: { job_id: number } }>("/api/jobs/scan", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  refilterDocks: (body?: import("./types").RefilterRequest) =>
    request<{ ok: boolean; detail: unknown }>("/api/refilter-docks", {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
};
