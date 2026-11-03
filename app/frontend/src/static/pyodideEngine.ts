// CL-66: Analyze engine backed by Pyodide in a Web Worker. Examples and
// the Python bundle are files of this static site, cached for offline
// use by the service worker; no request ever goes to an analysis server.
import type { AnalyzeEngine } from "../pages/Analyze";
import type { AnalyzePayload, FixtureEntry } from "../types";

export const STATIC_MAX_BYTES = 5 * 1024 * 1024;
export const STATIC_MAX_PIXELS = 2_000_000;

export interface StaticExample extends FixtureEntry {
  file: string;
  label: string;
}

type Reply =
  | { type: "progress"; line: string }
  | { type: "ready" }
  | { type: "fatal"; error: string }
  | { type: "result"; id: number; payload?: AnalyzePayload; error?: string };

let worker: Worker | null = null;
let nextId = 1;
let progress: ((line: string) => void) | undefined;
const pending = new Map<number, { resolve: (p: AnalyzePayload) => void; reject: (e: Error) => void }>();
const readyListeners: (() => void)[] = [];
let runtimeReady = false;
let fatal: string | null = null;

function base(): string {
  return new URL("./", document.baseURI).href;
}

export function startWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL("./pyodide.worker.ts", import.meta.url), { type: "module" });
  worker.onmessage = (event: MessageEvent<Reply>) => {
    const reply = event.data;
    if (reply.type === "progress") progress?.(reply.line);
    else if (reply.type === "ready") {
      runtimeReady = true;
      readyListeners.splice(0).forEach((fn) => fn());
    }
    else if (reply.type === "fatal") {
      fatal = reply.error;
      pending.forEach(({ reject }) => reject(new Error(reply.error)));
      pending.clear();
    } else if (reply.type === "result") {
      const entry = pending.get(reply.id);
      if (!entry) return;
      pending.delete(reply.id);
      if (reply.payload) entry.resolve(reply.payload);
      else entry.reject(new Error(reply.error ?? "analysis failed"));
    }
  };
  worker.postMessage({ type: "init", base: base(), maxPixels: STATIC_MAX_PIXELS });
  return worker;
}

export function onRuntimeReady(listener: () => void): void {
  if (runtimeReady) listener();
  else readyListeners.push(listener);
}

export const pyodideEngine: AnalyzeEngine = {
  serverHandoffs: false,
  maxBytes: STATIC_MAX_BYTES,
  async analyze(file, onProgress) {
    if (fatal) throw new Error(fatal);
    progress = onProgress;
    const data = await file.arrayBuffer();
    const id = nextId++;
    return new Promise<AnalyzePayload>((resolve, reject) => {
      pending.set(id, { resolve, reject });
      startWorker().postMessage({ type: "analyze", id, data }, [data]);
    });
  },
  async listExamples() {
    const response = await fetch("examples/index.json");
    if (!response.ok) throw new Error("examples unavailable");
    return (await response.json()) as StaticExample[];
  },
  async fetchExample(entry) {
    const example = entry as StaticExample;
    const response = await fetch(`examples/${example.file}`);
    if (!response.ok) throw new Error("example unavailable");
    const blob = await response.blob();
    return new File([blob], example.file, { type: example.media_type });
  },
};
