export type FieldRow = {
  field_id: number;
  latitude: number;
  longitude: number;
  boat_count: number;
  mean_confidence: number | null;
  location_name: string | null;
  state: string | null;
  country: string | null;
  enrichment_status: string | null;
  scan_id: number | null;
  detection_date: string | null;
  prospect_id: number | null;
  controller: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  address: string | null;
  harbor_name: string | null;
  operator_type: string | null;
  confidence: number | null;
  sources: string | null;
  research_summary: string | null;
  supply_chain_summary: string | null;
  needs_review: number | null;
  approved: number | null;
};

export type Stats = {
  fields: number;
  boats: number;
  prospects: number;
  needs_review: number;
  approved: number;
};

export type ProspectDetail = {
  prospect_id: number;
  canonical_business_name: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  address: string | null;
  operator_type: string | null;
  harbor_name: string | null;
  research_summary: string | null;
  supply_chain_summary: string | null;
  supply_chain_json: unknown;
  confidence: number | null;
  sources: string[] | string | null;
  needs_review: number | null;
  approved: number | null;
  last_enriched: string | null;
  field_ids: number[];
};

export type ProspectUpdate = {
  canonical_business_name?: string | null;
  phone?: string | null;
  email?: string | null;
  website?: string | null;
  address?: string | null;
  operator_type?: string | null;
  harbor_name?: string | null;
  research_summary?: string | null;
  needs_review?: boolean | null;
  approved?: boolean | null;
};

export type ScanRow = {
  id: number;
  created_at: string | null;
  source: string | null;
  weights: string | null;
  split: string | null;
  notes: string | null;
  field_count: number;
};

export type ScanDiff = {
  scan_a: number;
  scan_b: number;
  fields_a: number;
  fields_b: number;
  delta: number;
};

export type EnrichRun = {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  provider: string | null;
  fields_processed: number;
  places_calls: number;
  gemini_calls: number;
  cap_hit: number;
  notes: string | null;
};

export type GeoJsonFeatureCollection = {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: { type: "Point"; coordinates: [number, number] };
    properties: Record<string, unknown>;
  }>;
};

export type ScanRegion = {
  id: string;
  kind: string;
  bbox: number[];
};

export type MapsQuota = {
  day: string;
  maps_used: number;
  cap: number;
  remaining: number;
};

export type JobRow = {
  id: number;
  kind: string;
  status: string;
  params: unknown;
  progress: unknown;
  result: unknown;
  cancel_requested: boolean;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
};
