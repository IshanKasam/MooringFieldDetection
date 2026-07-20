import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProspectUpdate } from "../api/types";

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

export function useScans() {
  return useQuery({ queryKey: ["scans"], queryFn: api.scans });
}

export function useEnrichRuns() {
  return useQuery({
    queryKey: ["enrichRuns"],
    queryFn: api.enrichRuns,
    refetchInterval: 5000,
  });
}

export function useApprove() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approved }: { id: number; approved: boolean }) =>
      api.approve(id, approved),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["table"] });
      void qc.invalidateQueries({ queryKey: ["geojson"] });
      void qc.invalidateQueries({ queryKey: ["stats"] });
      void qc.invalidateQueries({ queryKey: ["prospect"] });
    },
  });
}

export function useUpdateProspect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ProspectUpdate }) =>
      api.updateProspect(id, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["table"] });
      void qc.invalidateQueries({ queryKey: ["geojson"] });
      void qc.invalidateQueries({ queryKey: ["prospect"] });
    },
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
