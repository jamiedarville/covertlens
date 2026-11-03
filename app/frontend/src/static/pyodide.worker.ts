// CL-66: the CovertLens library running in Pyodide, in a Web Worker so
// the page stays responsive. It runs app/analysis_worker.py, the exact
// code behind POST /api/analyze, on bytes that never leave the browser.

type PyodideApi = {
  unpackArchive(buffer: Uint8Array, format: string, options: { extractDir: string }): void;
  runPython(code: string): unknown;
  FS: { writeFile(path: string, data: Uint8Array): void; unlink(path: string): void };
};

type Message =
  | { type: "init"; base: string; maxPixels: number }
  | { type: "analyze"; id: number; data: ArrayBuffer };

const ctx = self as unknown as {
  postMessage(message: unknown): void;
  onmessage: ((event: MessageEvent<Message>) => void) | null;
};

let ready: Promise<PyodideApi> | null = null;

async function boot(base: string, maxPixels: number): Promise<PyodideApi> {
  ctx.postMessage({ type: "progress", line: "Loading the Python runtime (first visit only)…" });
  const indexURL = `${base}pyodide/`;
  const module = (await import(/* @vite-ignore */ `${indexURL}pyodide.mjs`)) as {
    loadPyodide(options: { indexURL: string }): Promise<PyodideApi>;
  };
  const py = await module.loadPyodide({ indexURL });
  ctx.postMessage({ type: "progress", line: "Loading the CovertLens library…" });
  const response = await fetch(`${base}covertlens-py.zip`);
  if (!response.ok) throw new Error(`library bundle: ${response.status}`);
  py.unpackArchive(new Uint8Array(await response.arrayBuffer()), "zip", {
    extractDir: "/home/pyodide/covertlens",
  });
  py.runPython(
    [
      "import sys",
      "sys.path.insert(0, '/home/pyodide/covertlens')",
      "from app.analysis_worker import analyze_bytes as _covertlens_analyze",
      `_covertlens_max_pixels = ${Math.floor(maxPixels)}`,
    ].join("\n"),
  );
  ctx.postMessage({ type: "ready" });
  return py;
}

ctx.onmessage = (event) => {
  const message = event.data;
  if (message.type === "init") {
    ready = boot(message.base, message.maxPixels);
    ready.catch((err: unknown) => ctx.postMessage({ type: "fatal", error: String(err) }));
    return;
  }
  if (message.type === "analyze") {
    const run = async () => {
      if (!ready) throw new Error("worker not initialised");
      const py = await ready;
      ctx.postMessage({ type: "progress", line: "Analyzing in your browser…" });
      py.FS.writeFile("/tmp/covertlens-upload", new Uint8Array(message.data));
      try {
        const text = py.runPython(
          [
            "import json",
            "with open('/tmp/covertlens-upload', 'rb') as _f:",
            "    _data = _f.read()",
            "json.dumps(_covertlens_analyze(_data, _covertlens_max_pixels))",
          ].join("\n"),
        );
        return JSON.parse(String(text)) as unknown;
      } finally {
        py.FS.unlink("/tmp/covertlens-upload");
      }
    };
    run()
      .then((payload) => ctx.postMessage({ type: "result", id: message.id, payload }))
      .catch((err: unknown) =>
        ctx.postMessage({ type: "result", id: message.id, error: String(err) }),
      );
  }
};
