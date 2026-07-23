import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProspectUpdate } from "../api/types";

function invalidateFieldQueries(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ["table"] });
  void qc.invalidateQueries({ queryKey: ["geojson"] });
  void qc.invalidateQueries({ queryKey: ["stats"] });
  void qc.invalidateQueries({ queryKey: ["prospect"] });
  void qc.invalidateQueries({ queryKey: ["scans"] });
}

export function useStats() {
  return useQuery({ queryKey: ["stats"], queryFn: api.stats });
}

export function useTable() {
  return useQuery({ queryKey: ["table"], queryFn: api.table });
}

export function useGeojson() {
  return useQuery({ queryKey: ["geojson"], queryFn: api.geojson });
}

export function useProspect(id: number | null) {
  return useQuery({
    queryKey: ["prospect", id],
    queryFn: () => api.prospect(id!),
    enabled: id != null,
  });
}

export function useField(id: number | null) {
  return useQuery({
    queryKey: ["field", id],
    queryFn: async () => {
      const rows = await api.table();
      return rows.find((r) => r.field_id === id) ?? null;
    },
    enabled: id != null,
  });
}

export function useScans() {
  return useQuery({ queryKey: ["scans"], queryFn: api.scans });
}

export function useEnrichRuns() {
  const qc = useQueryClient();
  const prevFinished = useRef<Set<number>>(new Set());
  const query = useQuery({
    queryKey: ["enrichRuns"],
    queryFn: api.enrichRuns,
    refetchInterval: 5000,
  });

  useEffect(() => {
    const runs = query.data;
    if (!runs) return;
    const finished = new Set(
      runs.filter((r) => r.finished_at).map((r) => r.id),
    );
    let newlyDone = false;
    for (const id of finished) {
      if (!prevFinished.current.has(id)) newlyDone = true;
    }
    // After first paint, only invalidate when a run newly finishes
    if (prevFinished.current.size > 0 && newlyDone) {
      invalidateFieldQueries(qc);
    }
    prevFinished.current = finished;
  }, [query.data, qc]);

  return query;
}

export function useApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approved }: { id: number; approved: boolean }) =>
      api.approve(id, approved),
    onSuccess: () => invalidateFieldQueries(qc),
  });
}

export function useUpdateProspect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ProspectUpdate }) =>
      api.updateProspect(id, body),
    onSuccess: () => invalidateFieldQueries(qc),
  });
}

export function useEnrich() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ step, limit }: { step: string; limit?: number }) =>
      api.enrich(step, limit ?? 5),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["enrichRuns"] });
    },
  });
}

export function useRefilterDocks() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body?: import("../api/types").RefilterRequest) =>
      api.refilterDocks(body),
    onSuccess: () => invalidateFieldQueries(qc),
  });
}

export { invalidateFieldQueries };
