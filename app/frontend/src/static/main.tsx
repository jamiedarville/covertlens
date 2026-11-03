// CL-66: static, zero-server build of the Analyze page. The library runs
// in Pyodide; the service worker caches every file so the page keeps
// working offline after the first visit.
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import Analyze from "../pages/Analyze";
import { STATIC_MAX_BYTES, STATIC_MAX_PIXELS, onRuntimeReady, pyodideEngine, startWorker } from "./pyodideEngine";
import "../styles.css";

export function StaticNotice({ runtime, offline }: { runtime: string; offline: string }) {
  return (
    <div className="card" data-testid="static-notice">
      <p>
        <strong>Runs entirely in your browser.</strong> The CovertLens library
        executes in Pyodide (CPython compiled to WebAssembly); your image is
        never uploaded. Pyodide is several times slower than the server, so
        this page accepts images up to {STATIC_MAX_BYTES / (1024 * 1024)} MiB
        and {(STATIC_MAX_PIXELS / 1_000_000).toFixed(0)} MP; use the server or
        the CLI for larger ones.
      </p>
      <p className="note" data-testid="runtime-status">
        {runtime} · {offline}
      </p>
    </div>
  );
}

function StaticApp() {
  const [runtime, setRuntime] = useState("Python runtime loading…");
  const [offline, setOffline] = useState("offline cache: preparing");
  useEffect(() => {
    startWorker();
    onRuntimeReady(() => setRuntime("Python runtime ready"));
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker
        .register("./sw.js")
        .then(() => navigator.serviceWorker.ready)
        .then(() => setOffline("offline cache: ready"))
        .catch(() => setOffline("offline cache: unavailable"));
    } else {
      setOffline("offline cache: unsupported browser");
    }
  }, []);
  return (
    <>
      <header className="site-header">
        <span className="wordmark">CovertLens</span>
        <nav aria-label="Primary">
          <span>Analyze (in your browser)</span>
        </nav>
      </header>
      <main id="main" className="page">
        <Analyze engine={{ ...pyodideEngine, notice: <StaticNotice runtime={runtime} offline={offline} /> }} />
      </main>
      <footer className="site-footer">
        <p>
          Scores are evidence, never accusations. This static page makes no
          request to an analysis server.
        </p>
      </footer>
    </>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <StaticApp />
  </StrictMode>,
);
