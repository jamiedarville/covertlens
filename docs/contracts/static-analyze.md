# Static Pyodide build of the Analyze page (CL-66)

Implements: CL-66 (C-01). A zero-server demo link: the Analyze page
running the CovertLens library in the browser with Pyodide, so the
evidence never leaves the user's machine.

## Build

`cd app/frontend && npm run build:static` writes `dist-static/`, a
plain static site that works from any host path (relative base):

1. `scripts/build_static_bundle.py` (standard library) writes
   `covertlens-py.zip` — the `covertlens` package, `config/` and
   `app/analysis_worker.py`, deterministic — and six built-in example
   fixtures, plus the CPython reference output of each (outside the
   site, for the parity check).
2. The Pyodide runtime is copied from the pinned `pyodide` npm package
   (314.0.7, CPython 3.14): `pyodide.mjs`, `pyodide.asm.mjs`,
   `pyodide.asm.wasm`, `python_stdlib.zip`, `pyodide-lock.json`. No
   extra Pyodide packages are needed: the library is standard-library
   only.
3. Vite builds `static.html` (`vite.static.config.ts`) into
   `index.html`, and `precache.json` lists every file with a content
   revision for the service worker.

CI builds it, runs the parity check and uploads `dist-static/` as the
`covertlens-static-analyze` artifact; host it on any static server
(GitHub Pages, S3, `python -m http.server`).

## Runtime

- The page reuses the Analyze page and the CL-48 overlay components
  unchanged; only its engine differs. A Web Worker loads Pyodide,
  unpacks the bundle and calls `app.analysis_worker.analyze_bytes`,
  the exact code behind `POST /api/analyze`, so the response shape
  and every number match the server's.
- **Offline after first load:** `sw.js` precaches every file on
  install and serves same-origin GETs cache-first.
- **No network to a server:** the page's CSP is
  `connect-src 'self'` (plus `'wasm-unsafe-eval'` for WebAssembly);
  analysis needs only cached files of this origin.
- **Size limits, stated on the page:** Pyodide is several times slower
  than native CPython (about 0.5 s for a 384×128 scene, 40 ms for a
  64×48 cover in Node), so the page accepts up to 5 MiB and 2 MP;
  larger images get an explicit message, and the Python side applies
  the same 2 MP cap as an `oversized` status.
- Server-only conveniences (landing-page preload, `?generated=`
  hand-off, `/api/fixtures`) are off; the six examples are files of
  the site.

## Acceptance mapping

| Criterion | Evidence |
|---|---|
| The page works offline after first load and analyses a fixture without any network request to a server | `tests/test_static_build.py` (slow; Playwright + Chromium): loads `dist-static/` once, waits for the cache and the runtime, stops the HTTP server, switches the browser offline, reloads and analyses an example; no request reaches the server and every response comes from the service worker |
| Same analysis as the service | `npm run test:pyodide`: each example analysed in Pyodide matches CPython's `analyze_bytes` output exactly (wall-clock `elapsed_ms` excepted) |
| Reuses the CL-48 overlay components; clear size-limit notice | `src/static/main.tsx` renders `pages/Analyze.tsx` with `pyodideEngine` and the notice; `AnalyzeEngine` keeps the server page unchanged |

Note: the decision panel shows the analysis worker's ladder as it is
on `main` (the server's `/api/analyze` decision). When the server's
decision config changes, the static page inherits it by bundling the
same file.
