import type {
  AnalyzePayload,
  Comparison,
  FixtureEntry,
  GateDelivery,
  GateRunDetail,
} from "./types";

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
): Promise<GateDelivery> {
  const response = await fetch(
    `/api/gate/deliveries/${encodeURIComponent(deliveryId)}/verdict`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verdict }),
    },
  );
  const body = (await readJson(response)) as Record<string, unknown>;
  if (!response.ok) {
    throw new ApiError(response.status, String(body.detail ?? "Verdict failed."));
  }
  return body as unknown as GateDelivery;
}

export function recipientImageUrl(deliveryId: string): string {
  return `/api/gate/deliveries/${encodeURIComponent(deliveryId)}/recipient-image`;
}

export function reviewerImageUrl(deliveryId: string): string {
  return `/api/gate/deliveries/${encodeURIComponent(deliveryId)}/reviewer-image?actor_id=researcher-1`;
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
