import { useEffect, useRef, useState, type ReactNode } from "react";
import type { AnalyzePayload, FixtureEntry } from "../types";
import {
  ApiError,
  analyzeFile,
  fetchFixtureFile,
  fetchGeneratedFile,
  listFixtures,
  takePreload,
} from "../api";
import { DecisionPanel, EvidenceTables, FamilyCards } from "../components/Results";
import { Overlay } from "../components/Overlay";
import { TechDetails } from "../components/Help";
import { SimpleResult, notCheckedMessage } from "../components/TrafficLight";

function statusMessage(payload: AnalyzePayload): string {
  return payload.status === "parsed" && payload.decision
    ? "Done. Your result is below."
    : notCheckedMessage(payload);
}

// Everything behind the traffic lights, for specialists: the exact
// decision, per-check scores, shape measurements and raw evidence.
function TechnicalEvidence({
  payload,
  previewUrl,
  label,
}: {
  payload: AnalyzePayload;
  previewUrl: string | null;
  label: string;
}) {
  return (
    <section className="technical-evidence" aria-labelledby="technical-heading">
      <h2 id="technical-heading">Technical evidence (for specialists)</h2>
      <p className="note">
        The exact scores and measurements behind the colours above. You
        don’t need any of this to understand the result. No hidden message
        is ever read out (“decoded”) on this page.
      </p>
      {payload.analysis?.content_hash && (
        <TechDetails summary="File fingerprint (for matching this exact file later)">
          <p className="note hash-line">
            {payload.analysis.content_hash} — a fingerprint computed from the
            file’s exact contents. Changing even one byte produces a
            different fingerprint, so this result is tied to this exact file.
          </p>
        </TechDetails>
      )}
      {payload.decision && <DecisionPanel decision={payload.decision} />}
      <FamilyCards payload={payload} />
      <Overlay geometric={payload.geometric} imageUrl={previewUrl} imageLabel={label} />
      <EvidenceTables payload={payload} />
    </section>
  );
}

// Where analysis runs (CL-66): the server API by default, or Pyodide in
// the browser for the static build. The page and its CL-48 overlay
// components are the same either way.
export interface AnalyzeEngine {
  analyze(file: File, onProgress?: (line: string) => void): Promise<AnalyzePayload>;
  listExamples(): Promise<FixtureEntry[]>;
  fetchExample(entry: FixtureEntry): Promise<File>;
  // Landing-page preload and ?generated= handoff need the server.
  serverHandoffs: boolean;
  maxBytes?: number;
  notice?: ReactNode;
}

// Ready-made examples arrive with machine names such as
// "geometric-height_position-encoded-98ae…". Show a plain
// description instead, with a short id suffix so nearby examples
// stay tellable apart (CL-79).
export function exampleLabel(entry: FixtureEntry): string {
  const where: Record<string, string> = {
    height_position: "pattern in bar heights",
    gap_timing: "pattern in gaps between bars",
    lit_dark: "pattern in lit/dark bars",
    colour_code: "pattern in bar colours",
    angle_tilt: "pattern in bar tilt",
  };
  if (entry.kind.startsWith("benign")) {
    const subject = (entry.kind.split(":")[1] ?? entry.fixture_id)
      .replaceAll("_", " ")
      .replace("benign scene", "scene");
    const num = entry.fixture_id.split("_").pop() ?? "";
    return `ordinary ${subject} picture, nothing hidden (number ${num})`;
  }
  const place = entry.subfamily
    ? (where[entry.subfamily] ?? entry.subfamily.replaceAll("_", " "))
    : null;
  const kind =
    entry.kind === "encoded"
      ? "with hidden information"
      : entry.kind === "clean"
        ? "ordinary, nothing hidden"
        : entry.kind === "negative"
          ? "ordinary variation, nothing hidden"
          : entry.kind.replaceAll("_", " ");
  const short = entry.fixture_id.split("-").pop() ?? "";
  return `${place ? `${place} — ` : ""}${kind} (example …${short.slice(0, 6)})`;
}

// The result: the plain traffic-light answer first, then a link that
// opens the technical evidence for specialists.
export function ResultView({
  payload,
  label,
  previewUrl,
  showTechnical,
  onToggleTechnical,
}: {
  payload: AnalyzePayload;
  label: string;
  previewUrl: string | null;
  showTechnical: boolean;
  onToggleTechnical: () => void;
}) {
  const parsed = payload.status === "parsed" && payload.analysis;
  return (
    <>
      <h2>Result for {label || "your image"}</h2>
      {parsed && (
        <p className="note">
          {payload.analysis?.media_kind.toUpperCase()} image
          {payload.analysis?.image?.width
            ? `, ${payload.analysis.image.width} × ${payload.analysis.image.height} pixels`
            : ""}
          .
        </p>
      )}
      <SimpleResult payload={payload} />
      {parsed ? (
        <>
          <p className="technical-toggle">
            <button
              type="button"
              className="link-button"
              aria-expanded={showTechnical}
              aria-controls="technical-evidence"
              onClick={onToggleTechnical}
            >
              {showTechnical ? "Hide the technical evidence" : "See the technical evidence"}
            </button>
            <span className="note">
              {" "}
              — the scores, measurements and charts behind these colours, for specialists.
            </span>
          </p>
          <div id="technical-evidence" hidden={!showTechnical}>
            {showTechnical && (
              <TechnicalEvidence payload={payload} previewUrl={previewUrl} label={label || "Checked image"} />
            )}
          </div>
        </>
      ) : (
        <TechDetails summary="Technical details (for specialists)">
          <p className="note">
            Status reported by the checker: <span className="mono">{payload.status}</span>
            {payload.detail ? ` (${payload.detail})` : ""}.
          </p>
        </TechDetails>
      )}
    </>
  );
}

export const serverEngine: AnalyzeEngine = {
  analyze: (file) => analyzeFile(file),
  listExamples: listFixtures,
  fetchExample: fetchFixtureFile,
  serverHandoffs: true,
};

export default function Analyze({ engine = serverEngine }: { engine?: AnalyzeEngine }) {
  const [payload, setPayload] = useState<AnalyzePayload | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [resultLabel, setResultLabel] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState<string>("");
  const [dragging, setDragging] = useState(false);
  const [fixtures, setFixtures] = useState<FixtureEntry[] | null>(null);
  const [fixtureChoice, setFixtureChoice] = useState<string>("");
  const [showTechnical, setShowTechnical] = useState(false);
  const resultsRef = useRef<HTMLDivElement>(null);

  const toggleTechnical = () => {
    const opening = !showTechnical;
    setShowTechnical(opening);
    if (opening) {
      requestAnimationFrame(() =>
        document.getElementById("technical-heading")?.scrollIntoView({ block: "start" }),
      );
    }
  };

  useEffect(() => {
    const preload = engine.serverHandoffs ? takePreload() : null;
    if (preload) {
      setPayload(preload.payload);
      setPreviewUrl(preload.imageUrl);
      setResultLabel(preload.label);
      setStatusLine(`Showing the example from the home page: ${preload.label}.`);
    }
    let cancelled = false;
    engine
      .listExamples()
      .then((entries) => {
        if (!cancelled) setFixtures(entries);
      })
      .catch(() => {
        if (!cancelled) setFixtures([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Preview via a data: URL: the service CSP allows `data:` images
  // but not `blob:`, and the canvas needs the exact uploaded image.
  const readPreview = (file: File): Promise<string | null> =>
    new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () =>
        resolve(typeof reader.result === "string" ? reader.result : null);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(file);
    });

  const run = async (file: File, label: string) => {
    setBusy(true);
    setError(null);
    setShowTechnical(false);
    setStatusLine(`Checking ${label}… this usually takes a few seconds.`);
    setPreviewUrl(await readPreview(file));
    try {
      const result = await engine.analyze(file, setStatusLine);
      setPayload(result);
      setResultLabel(label);
      setStatusLine(statusMessage(result));
      requestAnimationFrame(() => resultsRef.current?.focus());
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "The check couldn’t be finished. What to do: check your internet connection, then try the same image again.";
      setError(message);
      setStatusLine(message);
    } finally {
      setBusy(false);
    }
  };

  // One-click handoff from /generate (CL-51):
  // /analyze?generated=<digest>.<ext> loads and analyzes it.
  useEffect(() => {
    if (!engine.serverHandoffs) return;
    const generated = new URLSearchParams(window.location.search).get("generated");
    if (!generated || !/^[0-9a-f]{64}\.(png|jpg)$/.test(generated)) return;
    let cancelled = false;
    setStatusLine("Loading your generated image…");
    fetchGeneratedFile(`/api/generated/${generated}`, generated)
      .then((file) => {
        if (!cancelled) return run(file, `Generated image ${generated.slice(0, 12)}…`);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError ? err.message : "The generated image could not be loaded.";
        setError(message);
        setStatusLine(message);
      });
    return () => {
      cancelled = true;
    };
    // Run once on arrival; `run` is stable for this mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const takeFile = (file: File | undefined) => {
    if (!file) return;
    const okType = ["image/png", "image/jpeg"].includes(file.type) || /\.(png|jpe?g)$/i.test(file.name);
    if (!okType) {
      setError("That type of file can’t be checked. What to do: choose a PNG or JPEG image (a file name ending in .png, .jpg or .jpeg).");
      setStatusLine("Please choose a PNG or JPEG image.");
      return;
    }
    if (engine.maxBytes !== undefined && file.size > engine.maxBytes) {
      const limit = `${Math.round(engine.maxBytes / (1024 * 1024))} MiB`;
      setError(`That file is bigger than this page’s ${limit} limit, so it wasn’t checked. What to do: save a smaller copy and try again.`);
      setStatusLine(`That file is larger than this page's ${limit} limit.`);
      return;
    }
    void run(file, file.name);
  };

  const runExample = async () => {
    const entry = (fixtures ?? []).find((f) => f.fixture_id === fixtureChoice);
    if (!entry) return;
    setBusy(true);
    setError(null);
    setStatusLine(`Loading the example “${exampleLabel(entry)}”…`);
    try {
      const file = await engine.fetchExample(entry);
      await run(file, exampleLabel(entry));
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "That example could not be loaded.";
      setError(message);
      setStatusLine(message);
      setBusy(false);
    }
  };

  return (
    <>
      <h1>Check an image for hidden messages</h1>
      <p className="lede">
        AI agents sometimes send each other images. CovertLens checks
        whether an image might be secretly carrying a message from one
        agent to another, a sign the agents may be working together
        behind the scenes. This is called <strong>collusion</strong>.
      </p>
      <p>
        Add an image below and you’ll get a simple answer:{" "}
        <strong>green</strong>, <strong>orange</strong> or{" "}
        <strong>red</strong>, with each colour explained.
      </p>
      {engine.notice}

      <div
        className={dragging ? "dropzone dropzone-active" : "dropzone"}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          takeFile(e.dataTransfer.files[0]);
        }}
      >
        <p className="dropzone-title">Drag and drop an image here</p>
        <p>
          <label className="button button-primary" htmlFor="file-input">
            Choose an image to check
          </label>
        </p>
        <p className="note">
          PNG or JPEG images only. The check starts as soon as you choose
          an image.
        </p>
        <input
          id="file-input"
          className="visually-hidden"
          type="file"
          accept="image/png,image/jpeg,.png,.jpg,.jpeg"
          onChange={(e) => {
            takeFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>

      <form
        className="example-row"
        onSubmit={(e) => {
          e.preventDefault();
          void runExample();
        }}
      >
        <label htmlFor="fixture-select">No image handy? Try one of ours:</label>
        <select
          id="fixture-select"
          value={fixtureChoice}
          onChange={(e) => setFixtureChoice(e.target.value)}
          disabled={busy}
        >
          <option value="">{fixtures === null ? "Loading the examples…" : "Choose an example…"}</option>
          {(fixtures ?? []).map((entry) => (
            <option key={entry.fixture_id} value={entry.fixture_id}>
              {exampleLabel(entry)}
            </option>
          ))}
        </select>
        <button type="submit" className="button" disabled={busy || !fixtureChoice}>
          Check this example
        </button>
        {!fixtureChoice && !busy && (
          <span className="note">Pick an example from the list first, then press the button.</span>
        )}
        {fixtures !== null && fixtures.length === 0 && (
          <span className="note">The examples couldn’t be loaded. You can still check your own image above.</span>
        )}
      </form>
      {!payload && !busy && (
        <p className="note">Nothing has been checked yet. Your result will appear here.</p>
      )}

      <p role="status" aria-live="polite" className="status-line">
        {busy ? statusLine || "Checking your image… larger images can take a little while." : statusLine}
      </p>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      {payload && (
        <div ref={resultsRef} tabIndex={-1} className="results">
          <ResultView
            payload={payload}
            label={resultLabel}
            previewUrl={previewUrl}
            showTechnical={showTechnical}
            onToggleTechnical={toggleTechnical}
          />
        </div>
      )}
    </>
  );
}
