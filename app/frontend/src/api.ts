import type {
  AnalyzePayload,
  CandidateDecode,
  Comparison,
  DemoRoles,
  FixtureEntry,
  GateDelivery,
  GateRunDetail,
  ReviewAudit,
  ReviewDetail,
  ReviewQueue,
  ReviewRole,
  SecondOpinion,
  SecondOpinionConfig,
  TraceView,
} from "./types";
import { roleHeaders } from "./demoRole";

// Same-origin API client. The Analyze overlay renders from the
// single POST /api/analyze response; the only other reads are the
// fixture list/images and the precomputed landing comparison.

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new ApiError(response.status, `Unexpected response (${response.status})`);
  }
}

export async function analyzeFile(file: File): Promise<AnalyzePayload> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/analyze", { method: "POST", body: form });
  const body = (await readJson(response)) as Record<string, unknown>;
  if (response.status === 413) {
    throw new ApiError(413, "That file is too large to analyze. Try a smaller PNG or JPEG.");
  }
  if (response.status === 429) {
    throw new ApiError(429, "Too many analyses in the last minute. Wait a moment and try again.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, `Analysis failed (${response.status}).`);
  }
  return body as unknown as AnalyzePayload;
}

export async function listFixtures(): Promise<FixtureEntry[]> {
  const response = await fetch("/api/fixtures");
  if (!response.ok) throw new ApiError(response.status, "Could not load examples.");
  return (await readJson(response)) as FixtureEntry[];
}

export function fixtureImageUrl(contentHash: string): string {
  return `/api/fixtures/${contentHash.replace(/^sha256:/, "")}.png`;
}

export async function fetchFixtureFile(entry: FixtureEntry): Promise<File> {
  const response = await fetch(fixtureImageUrl(entry.content_hash));
  if (!response.ok) throw new ApiError(response.status, "Could not load that example image.");
  const blob = await response.blob();
  return new File([blob], `${entry.fixture_id}.png`, { type: "image/png" });
}

export async function fetchComparison(): Promise<Comparison | "computing"> {
  const response = await fetch("/api/comparison");
  if (response.status === 202) return "computing";
  if (!response.ok) throw new ApiError(response.status, "Could not load the comparison.");
  return (await readJson(response)) as Comparison;
}

export interface GenerateResult {
  fixture_id: string;
  content_hash: string;
  media_type: string;
  image_url: string;
  source: string;
  artifact_version_id: string;
  parameters: Record<string, unknown>;
}

export async function generateImage(
  params: Record<string, unknown>,
): Promise<GenerateResult> {
  const response = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  const body = (await readJson(response)) as Record<string, unknown>;
  if (response.status === 400) {
    throw new ApiError(400, String(body.detail ?? "Those parameters cannot be generated."));
  }
  if (response.status === 429) {
    throw new ApiError(429, "Too many requests in the last minute. Wait a moment and try again.");
  }
  if (response.status === 504) {
    throw new ApiError(504, "Generation ran past its time limit. Try simpler parameters.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, `Generation failed (${response.status}).`);
  }
  return body as unknown as GenerateResult;
}

// -- Live Gate (CL-53) ------------------------------------------------

export async function createGateRun(runId?: string): Promise<string> {
  const response = await fetch("/api/gate/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(runId ? { run_id: runId } : {}),
  });
  if (!response.ok) throw new ApiError(response.status, "Could not create the run.");
  const body = (await readJson(response)) as Record<string, unknown>;
  return String(body.run_id);
}

export async function postGateDelivery(params: {
  file: File;
  runId: string;
  senderId: string;
  recipientId: string;
  routeId: string;
  episodeId?: string;
}): Promise<GateDelivery> {
  const form = new FormData();
  form.append("file", params.file);
  form.append("run_id", params.runId);
  form.append("sender_id", params.senderId);
  form.append("recipient_id", params.recipientId);
  form.append("route_id", params.routeId);
  if (params.episodeId) form.append("episode_id", params.episodeId);
  const response = await fetch("/api/gate/deliveries", { method: "POST", body: form });
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Delivery failed."));
  }
  return body as unknown as GateDelivery;
}

export async function fetchGateRun(runId: string): Promise<GateRunDetail> {
  const response = await fetch(`/api/gate/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) throw new ApiError(response.status, "Could not load the run.");
  return (await readJson(response)) as unknown as GateRunDetail;
}

export async function analyzeGateDelivery(
  deliveryId: string,
): Promise<{ suggested_verdict: string; decision: Record<string, unknown> }> {
  const response = await fetch(
    `/api/gate/deliveries/${encodeURIComponent(deliveryId)}/analyze`,
    { method: "POST" },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Analysis failed."));
  }
  return body as unknown as {
    suggested_verdict: string;
    decision: Record<string, unknown>;
  };
}

export async function recordGateVerdict(
  deliveryId: string,
  verdict: string,
  role: string,
): Promise<GateDelivery> {
  const response = await fetch(
    `/api/gate/deliveries/${encodeURIComponent(deliveryId)}/verdict`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...roleHeaders(role) },
      body: JSON.stringify({ verdict }),
    },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Verdict failed."));
  }
  return body as unknown as GateDelivery;
}

// -- Trace explorer (CL-60) ----------------------------------------------

export async function fetchTraceRun(runId: string, role: string): Promise<TraceView> {
  const response = await fetch(
    `/api/trace/runs/${encodeURIComponent(runId)}`,
    { headers: roleHeaders(role) },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Could not load the trace."));
  }
  return body as unknown as TraceView;
}

// -- Reviewer (CL-59) ---------------------------------------------------

export async function fetchDemoRoles(): Promise<DemoRoles> {
  const response = await fetch("/api/review/roles");
  if (!response.ok) throw new ApiError(response.status, "Could not load demo roles.");
  const body = (await readJson(response)) as Record<string, unknown>;
  return { roles: body.roles as ReviewRole[], enabled: body.enabled !== false };
}

export async function fetchReviewQueue(
  runId: string,
  role: string,
): Promise<ReviewQueue> {
  const response = await fetch(
    `/api/review/runs/${encodeURIComponent(runId)}/queue`,
    { headers: roleHeaders(role) },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Could not load the queue."));
  }
  return body as unknown as ReviewQueue;
}

export async function fetchReviewDetail(
  deliveryId: string,
  role: string,
): Promise<ReviewDetail> {
  const response = await fetch(
    `/api/review/deliveries/${encodeURIComponent(deliveryId)}`,
    { headers: roleHeaders(role) },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Could not load the delivery."));
  }
  return body as unknown as ReviewDetail;
}

export async function fetchCandidateDecode(
  deliveryId: string,
  role: string,
): Promise<CandidateDecode> {
  const response = await fetch(
    `/api/review/deliveries/${encodeURIComponent(deliveryId)}/candidate-decode`,
    { headers: roleHeaders(role) },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Decode unavailable."));
  }
  return body as unknown as CandidateDecode;
}

export async function fetchReviewOriginal(
  deliveryId: string,
  role: string,
): Promise<Blob> {
  const response = await fetch(
    `/api/review/deliveries/${encodeURIComponent(deliveryId)}/original`,
    { headers: roleHeaders(role) },
  );
  if (!response.ok) {
    const body = (await readJson(response).catch(() => ({}))) as Record<string, unknown>;
    throw new ApiError(response.status, String(body.detail ?? "Original unavailable."));
  }
  return response.blob();
}

export async function postDisposition(
  deliveryId: string,
  role: string,
  payload: { disposition: string; note: string; demonstrated_basis?: string },
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `/api/review/deliveries/${encodeURIComponent(deliveryId)}/disposition`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...roleHeaders(role) },
      body: JSON.stringify(payload),
    },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Disposition failed."));
  }
  return body;
}

export async function fetchSecondOpinionConfig(): Promise<SecondOpinionConfig> {
  const response = await fetch("/api/review/second-opinion/config");
  if (!response.ok) throw new ApiError(response.status, "Could not load second-opinion status.");
  return (await readJson(response)) as unknown as SecondOpinionConfig;
}

export async function requestSecondOpinion(
  deliveryId: string,
  role: string,
): Promise<SecondOpinion> {
  const response = await fetch(
    `/api/review/deliveries/${encodeURIComponent(deliveryId)}/second-opinion`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json", ...roleHeaders(role) },
      body: JSON.stringify({}),
    },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Second opinion failed."));
  }
  return body as unknown as SecondOpinion;
}

export async function fetchSecondOpinions(
  deliveryId: string,
  role: string,
): Promise<{ opinions: SecondOpinion[]; config: SecondOpinionConfig }> {
  const response = await fetch(
    `/api/review/deliveries/${encodeURIComponent(deliveryId)}/second-opinion`,
    { headers: roleHeaders(role) },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Could not load second opinions."));
  }
  return body as unknown as { opinions: SecondOpinion[]; config: SecondOpinionConfig };
}

export async function downloadReviewPackage(
  runId: string,
  role: string,
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(
    `/api/review/runs/${encodeURIComponent(runId)}/export`,
    { headers: roleHeaders(role) },
  );
  if (!response.ok) {
    const body = (await readJson(response).catch(() => ({}))) as Record<string, unknown>;
    throw new ApiError(response.status, String(body.detail ?? "Export unavailable."));
  }
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return { blob: await response.blob(), filename: match?.[1] ?? `review-${runId}.json` };
}

export async function fetchReviewAudit(runId: string, role: string): Promise<ReviewAudit> {
  const response = await fetch(
    `/api/review/audit?run_id=${encodeURIComponent(runId)}`,
    { headers: roleHeaders(role) },
  );
  if (!response.ok) throw new ApiError(response.status, "Could not load the audit chain.");
  return (await readJson(response)) as unknown as ReviewAudit;
}

export function recipientImageUrl(deliveryId: string): string {
  return `/api/gate/deliveries/${encodeURIComponent(deliveryId)}/recipient-image`;
}

// Reviewer evidence view (R-08). The server picks the actor from the
// demo role; a viewer is denied and the attempt is audited (CL-78).
export async function fetchReviewerImage(deliveryId: string, role: string): Promise<Blob> {
  const response = await fetch(
    `/api/gate/deliveries/${encodeURIComponent(deliveryId)}/reviewer-image`,
    { headers: roleHeaders(role) },
  );
  if (!response.ok) {
    const body = (await readJson(response).catch(() => ({}))) as Record<string, unknown>;
    throw new ApiError(response.status, String(body.detail ?? "Original unavailable."));
  }
  return response.blob();
}

export async function fetchGeneratedFile(imageUrl: string, name: string): Promise<File> {
  const response = await fetch(imageUrl);
  if (!response.ok) throw new ApiError(response.status, "Could not load the generated image.");
  const blob = await response.blob();
  return new File([blob], name, { type: blob.type || "image/png" });
}

export async function fetchVersionLine(): Promise<string | null> {
  try {
    const response = await fetch("/api/version");
    if (!response.ok) return null;
    const body = (await readJson(response)) as Record<string, unknown>;
    const version = body.library_version;
    return typeof version === "string" ? `Library ${version}` : null;
  } catch {
    return null;
  }
}

// Hand a precomputed payload from the landing page to /analyze
// without a second analysis request (two-click overlay, CL-48).
const PRELOAD_KEY = "covertlens:preload";

export interface Preload {
  payload: AnalyzePayload;
  imageUrl: string;
  label: string;
}

export function storePreload(preload: Preload): void {
  try {
    sessionStorage.setItem(PRELOAD_KEY, JSON.stringify(preload));
  } catch {
    // Storage unavailable: /analyze still works via upload/examples.
  }
}

export function takePreload(): Preload | null {
  try {
    const raw = sessionStorage.getItem(PRELOAD_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(PRELOAD_KEY);
    return JSON.parse(raw) as Preload;
  } catch {
    return null;
  }
}

// -- Leaderboard (CL-70) ----------------------------------------------

export interface LeaderboardRow {
  rank: number;
  entry_id: string;
  display_name: string | null;
  kind: string;
  subfamily: string | null;
  payload_bits: number;
  bits_per_pixel: number | null;
  verdict: string;
  family_score: number | null;
  submitted_at: string;
}

export type OperatingPoint = "triage" | "quarantine" | "fail_run";

export interface LeaderboardBoard {
  pin_hash: string;
  standings: Record<OperatingPoint, LeaderboardRow[]>;
  entries: number;
  pending: number;
}

export interface LeaderboardBoardInfo {
  pin_hash: string;
  entries: number;
  visible_entries: number;
  first_submission: string;
  last_submission: string;
  threshold_config_version: string;
  detectors: string[];
  current: boolean;
}

export interface LeaderboardView {
  current: {
    pin_hash: string;
    detectors: string[];
    threshold_config_version: string;
    geometric_config_version: string;
  };
  board: LeaderboardBoard;
  boards: LeaderboardBoardInfo[];
  operating_points: OperatingPoint[];
  moderation: boolean;
  can_moderate: boolean;
  submissions_need_sign_in: boolean;
}

export interface LeaderboardEntry {
  entry_id: string;
  status: "visible" | "pending" | "hidden";
  pin_hash: string;
  outcome: {
    verdict: string;
    evades: Record<OperatingPoint, boolean>;
    payload: { bits: number; bits_per_pixel: number | null; derivation: string };
  };
}

export async function fetchLeaderboard(): Promise<LeaderboardView> {
  const response = await fetch("/api/leaderboard", { credentials: "same-origin" });
  if (!response.ok) throw new ApiError(response.status, "Could not load the leaderboard.");
  return (await readJson(response)) as LeaderboardView;
}

export async function fetchLeaderboardBoard(pinHash: string): Promise<LeaderboardBoard> {
  const response = await fetch(`/api/leaderboard/boards/${encodeURIComponent(pinHash)}`, {
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, "That board could not be loaded.");
  return (await readJson(response)) as LeaderboardBoard;
}

export async function submitToLeaderboard(
  artifactVersionId: string,
  displayName: string,
): Promise<LeaderboardEntry> {
  const response = await fetch("/api/leaderboard/submissions", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ artifact_version_id: artifactVersionId, display_name: displayName }),
  });
  const body = (await readJson(response)) as Record<string, unknown>;
  if (response.status === 401) throw new ApiError(401, "Sign in to submit to this leaderboard.");
  if (response.status === 409) throw new ApiError(409, "This image is already on the current board.");
  if (response.status === 429) throw new ApiError(429, "Too many submissions this hour. Try again later.");
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? `Submission failed (${response.status}).`));
  }
  return body as unknown as LeaderboardEntry;
}
