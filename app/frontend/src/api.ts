import type { AnalyzePayload, Comparison, FixtureEntry } from "./types";

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
