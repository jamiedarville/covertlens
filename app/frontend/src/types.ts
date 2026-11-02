// Shapes of the /api/analyze payload the UI renders (CL-47, CL-48).
// The page only renders values present in the response; these types
// name the fields it reads. Unknown extra fields are ignored.

export type JsonRecord = Record<string, unknown>;

export interface Finding {
  family: string;
  detector_name: string;
  detector_version: string;
  score: number;
  coverage: JsonRecord;
  evidence: JsonRecord;
  limitations: string[];
  schema_version?: string;
}

export interface AnalysisBody {
  media_kind: string;
  status: string;
  content_hash?: string;
  image?: { width?: number; height?: number } | null;
  coverage?: JsonRecord;
  limitations?: string[];
  findings: Finding[];
}

export interface PerFamily {
  family: string;
  max_score: number;
  findings: number;
  detectors: string[];
  thresholds_status: string;
  triage_flag_at: number | null;
  enforcement_quarantine_at: number | null;
  enforcement_fail_run_at: number | null;
  verdict: string;
}

export interface Decision {
  verdict: string;
  delivery: string;
  halt_execution: boolean;
  enforceable: boolean;
  equated_with_collusion: boolean;
  config_version: string;
  ladder_version: string;
  per_family: PerFamily[];
  findings_count: number;
  families_without_findings: string[];
}

export interface GeoChannel {
  step: number | null;
  offset: number | null;
  symbols: number[];
  residuals: number[];
  supporting: number;
  support_fraction: number;
  rms_residual: number;
  levels_used: number;
  rayleigh_R: number;
  null_exceedance: number | null;
  score: number;
  elements: number;
  quantized: boolean;
  applicable: boolean;
  detail?: string;
}

export interface Periodogram {
  available: boolean;
  reason: string | null;
  discovered_step: number | null;
  discovered_rayleigh_R: number | null;
  points: { step: number; rayleigh_R: number }[];
}

export interface OverlayChannel {
  sequence_attribute: string;
  unit: string;
  tolerance: number;
  values: number[];
  periodogram: Periodogram;
  residual_histogram: {
    bin_edges: number[];
    counts: number[];
    tolerance: number;
  };
}

export interface GeoElement {
  index: number;
  left: number;
  top: number;
  width: number;
  height: number;
  area: number;
  gap_to_next: number | null;
  angle_deg: number;
  colour: number[];
  colour_index: number;
  colour_distance: number;
  brightness: number;
}

export interface Geometric {
  status: string;
  classification: string | null;
  // Absent entirely when segmentation fails (minimal report).
  signal_grade?: string | null;
  primary_channel?: string | null;
  channels?: Record<string, GeoChannel>;
  structure: {
    claimed: boolean;
    code: string | null;
    reason: string | null;
    trigram_score: number | null;
    null_exceedance: number | null;
    log_likelihood_ratio: number | null;
    periodicity_stat: number | null;
    printable_fraction: number | null;
    codes_evaluated?: JsonRecord[];
  } | null;
  chart_likeness: {
    score: number;
    features: Record<string, number>;
    baseline_present: boolean;
  } | null;
  segmentation: {
    status: string;
    detail: string;
    width: number;
    height: number;
    element_count: number;
    elements: GeoElement[];
    sequences: Record<string, (number | null)[]>;
  } | null;
  overlay?: {
    version: string;
    channels: Record<string, OverlayChannel>;
  };
}

export interface AnalyzePayload {
  status: string;
  detail?: string;
  analysis: AnalysisBody | null;
  geometric: Geometric | null;
  decision: Decision | null;
}

export interface FixtureEntry {
  fixture_id: string;
  kind: string;
  subfamily: string | null;
  content_hash: string;
  media_type: string;
}

export interface ComparisonSide {
  fixture_id: string;
  content_hash: string;
  payload: AnalyzePayload;
}

export interface Comparison {
  schema: string;
  subfamily: string;
  clean: ComparisonSide;
  encoded: ComparisonSide;
}

export interface GateDelivery {
  delivery_id: string;
  run_id: string;
  episode_id: string | null;
  artifact_id: string;
  artifact_version_id: string;
  content_hash: string;
  sender_id: string;
  recipient_id: string;
  attempt: number;
  state: "pending" | "permitted" | "withheld" | string;
  verdict: string | null;
  verdict_id: string | null;
  infrastructure_error: string | null;
  recipient_message: string;
}

export interface GateEvent {
  event_id: string;
  event_type: string;
  run_id: string;
  seq: number;
  occurred_at: string;
  delivery_id: string | null;
  verdict: string | null;
  sender_id: string | null;
  recipient_id: string | null;
}

export interface GateRunDetail {
  run_id: string;
  deliveries: GateDelivery[];
  events: GateEvent[];
  access_report: Record<string, unknown>;
  access_attempts: Record<string, unknown>[];
  coverage: Record<string, unknown>;
}
