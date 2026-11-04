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
        <strong>This version runs entirely in your web browser.</strong>{" "}
        Your picture is never uploaded anywhere — the same CovertLens
        checker runs on your own device (using a technology called
        Pyodide). The trade-off is speed: checking in a browser is
        several times slower, so this page only accepts pictures up to{" "}
        {STATIC_MAX_BYTES / (1024 * 1024)} MiB and{" "}
        {(STATIC_MAX_PIXELS / 1_000_000).toFixed(0)} megapixels. For
        larger pictures, use the normal server version or the
        command-line tool. After your first visit, this page also works
        offline.
      </p>
      <p className="note" data-testid="runtime-status">
        {runtime} · {offline}
      </p>
    </div>
  );
}

function StaticApp() {
  const [runtime, setRuntime] = useState("checker software: still loading — wait for “ready” before adding a large picture");
  const [offline, setOffline] = useState("offline use: being prepared");
  useEffect(() => {
    startWorker();
    onRuntimeReady(() => setRuntime("checker software: ready"));
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker
        .register("./sw.js")
        .then(() => navigator.serviceWorker.ready)
        .then(() => setOffline("offline use: ready — this page will keep working without a connection"))
        .catch(() => setOffline("offline use: unavailable in this browser session — the page still works while you are online"));
    } else {
      setOffline("offline use: your browser does not support it — the page still works while you are online");
    }
  }, []);
  return (
    <>
      <header className="site-header">
        <span className="wordmark">CovertLens</span>
        <nav aria-label="Primary">
          <span>Check an image (runs in your browser — nothing is uploaded)</span>
        </nav>
      </header>
      <main id="main" className="page">
        <Analyze engine={{ ...pyodideEngine, notice: <StaticNotice runtime={runtime} offline={offline} /> }} />
      </main>
      <footer className="site-footer">
        <p>
          Results are warning signs, not proof, and never an accusation on
          their own. This page never sends your image to a server.
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
