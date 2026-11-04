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
    throw new ApiError(response.status, `The server sent a reply this page could not understand (code ${response.status}). What to do: reload the page and try again.`);
  }
}

export async function analyzeFile(file: File): Promise<AnalyzePayload> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/analyze", { method: "POST", body: form });
  const body = (await readJson(response)) as Record<string, unknown>;
  if (response.status === 413) {
    throw new ApiError(413, "That file is too large to check, so it was not checked. What to do: export a smaller PNG or JPEG and try again.");
  }
  if (response.status === 429) {
    throw new ApiError(429, "Too many checks were requested in the last minute, so this one was not run. What to do: wait a moment, then try the same picture again.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, `The check could not be completed (server code ${response.status}). What to do: try the same picture again in a moment.`);
  }
  return body as unknown as AnalyzePayload;
}

export async function listFixtures(): Promise<FixtureEntry[]> {
  const response = await fetch("/api/fixtures");
  if (!response.ok) throw new ApiError(response.status, "The list of ready-made examples could not be loaded. You can still check your own picture.");
  return (await readJson(response)) as FixtureEntry[];
}

export function fixtureImageUrl(contentHash: string): string {
  return `/api/fixtures/${contentHash.replace(/^sha256:/, "")}.png`;
}

export async function fetchFixtureFile(entry: FixtureEntry): Promise<File> {
  const response = await fetch(fixtureImageUrl(entry.content_hash));
  if (!response.ok) throw new ApiError(response.status, "That example picture could not be loaded. What to do: pick a different example, or check your own picture.");
  const blob = await response.blob();
  return new File([blob], `${entry.fixture_id}.png`, { type: "image/png" });
}

export async function fetchComparison(): Promise<Comparison | "computing"> {
  const response = await fetch("/api/comparison");
  if (response.status === 202) return "computing";
  if (!response.ok) throw new ApiError(response.status, "The ready-made skyline example could not be loaded.");
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
    throw new ApiError(400, String(body.detail ?? "A picture cannot be made with those settings. What to do: change one setting and try again."));
  }
  if (response.status === 429) {
    throw new ApiError(429, "Too many requests in the last minute. Wait a moment and try again.");
  }
  if (response.status === 504) {
    throw new ApiError(504, "Making the picture took too long and was stopped. What to do: try simpler settings, for example fewer bars.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, `The picture could not be made (server code ${response.status}). What to do: try again in a moment.`);
  }
  return body as unknown as GenerateResult;
}

// -- Live Gate (CL-53) ------------------------------------------------

// CL-78: `declaredChannels` declares the run's legitimate geometric
// channels; it must come before the first delivery (409 afterwards).
export async function createGateRun(
  runId?: string,
  declaredChannels: string[] = [],
): Promise<string> {
  const request: Record<string, unknown> = runId ? { run_id: runId } : {};
  if (declaredChannels.length > 0) request.declared_channels = declaredChannels;
  const response = await fetch("/api/gate/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    const detail = ((await readJson(response)) as Record<string, unknown> | null)?.detail;
    throw new ApiError(
      response.status,
      typeof detail === "string"
        ? `The session could not be started: ${detail}`
        : "The session could not be started. What to do: try a different session name.",
    );
  }
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
    throw new ApiError(response.status, String(body.detail ?? "The picture could not be sent to the gate. What to do: start the session first, then try again."));
  }
  return body as unknown as GateDelivery;
}

export async function fetchGateRun(runId: string): Promise<GateRunDetail> {
  const response = await fetch(`/api/gate/runs/${encodeURIComponent(runId)}`);
  if (!response.ok) throw new ApiError(response.status, "That session could not be loaded. What to do: check you typed its name exactly.");
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
    throw new ApiError(response.status, String(body.detail ?? "The check could not be completed. What to do: try again in a moment."));
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
    throw new ApiError(response.status, String(body.detail ?? "Your decision could not be applied. What to do: check it, then try again."));
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
    throw new ApiError(response.status, String(body.detail ?? "That session’s timeline could not be loaded. What to do: check the session name and your kind of user."));
  }
  return body as unknown as TraceView;
}

// -- Reviewer (CL-59) ---------------------------------------------------

export async function fetchDemoRoles(): Promise<DemoRoles> {
  const response = await fetch("/api/review/roles");
  if (!response.ok) throw new ApiError(response.status, "The list of demonstration user kinds could not be loaded.");
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
    throw new ApiError(response.status, String(body.detail ?? "The list of held-back pictures could not be loaded. What to do: check the session name and try again."));
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
    throw new ApiError(response.status, String(body.detail ?? "That picture’s details could not be loaded. What to do: try again in a moment."));
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
    throw new ApiError(response.status, String(body.detail ?? "The possible reading is not available. Only the reviewer kind of user may see it."));
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
    throw new ApiError(response.status, String(body.detail ?? "The original picture is not available to this kind of user."));
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
    throw new ApiError(response.status, String(body.detail ?? "Your judgement could not be saved. What to do: check your kind of user and try again."));
  }
  return body;
}

export async function fetchSecondOpinionConfig(): Promise<SecondOpinionConfig> {
  const response = await fetch("/api/review/second-opinion/config");
  if (!response.ok) throw new ApiError(response.status, "Whether the second-opinion feature is switched on could not be loaded.");
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
    throw new ApiError(response.status, String(body.detail ?? "The second opinion could not be obtained. That is not an all-clear — judge from the check results."));
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
    throw new ApiError(response.status, String(body.detail ?? "Earlier second opinions could not be loaded."));
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
    throw new ApiError(response.status, String(body.detail ?? "The download is not available. It needs the researcher kind of user."));
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
  if (!response.ok) throw new ApiError(response.status, "The audit record could not be loaded. It may only be that your kind of user may not see it.");
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
    throw new ApiError(response.status, String(body.detail ?? "The original picture is not available to this kind of user."));
  }
  return response.blob();
}

export async function fetchGeneratedFile(imageUrl: string, name: string): Promise<File> {
  const response = await fetch(imageUrl);
  if (!response.ok) throw new ApiError(response.status, "Your generated test picture could not be loaded again. What to do: make it again on “Make a test image”.");
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
  if (!response.ok) throw new ApiError(response.status, "The leaderboard could not be loaded. What to do: reload this page.");
  return (await readJson(response)) as LeaderboardView;
}

export async function fetchLeaderboardBoard(pinHash: string): Promise<LeaderboardBoard> {
  const response = await fetch(`/api/leaderboard/boards/${encodeURIComponent(pinHash)}`, {
    credentials: "same-origin",
  });
  if (!response.ok) throw new ApiError(response.status, "That older leaderboard could not be loaded.");
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
    throw new ApiError(response.status, String(body.detail ?? `Your leaderboard entry could not be added (server code ${response.status}). What to do: try again in a moment.`));
  }
  return body as unknown as LeaderboardEntry;
}
