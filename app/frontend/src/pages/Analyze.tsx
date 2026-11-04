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

function statusMessage(payload: AnalyzePayload): string {
  switch (payload.status) {
    case "parsed":
      return "Check finished. Read the decision first, then what each check found.";
    case "oversized":
      return `This image was not checked: it is too large to check safely${payload.detail ? ` (${payload.detail})` : ""}. “Not checked” is not the same as “all clear”. What to do: try a smaller copy of the image.`;
    case "timeout":
      return "This image was not fully checked: the check took too long and was stopped. “Not checked” is not the same as “all clear”. What to do: try a smaller or simpler image.";
    default:
      return `This file could not be checked (the checker reported: ${payload.status}). “Not checked” is not the same as “all clear”. What to do: use an ordinary PNG or JPEG picture.`;
  }
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
  const resultsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const preload = engine.serverHandoffs ? takePreload() : null;
    if (preload) {
      setPayload(preload.payload);
      setPreviewUrl(preload.imageUrl);
      setResultLabel(preload.label);
      setStatusLine(`Showing the ready-made example from the home page: ${preload.label}. Its measurements are drawn on the picture below.`);
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
    setStatusLine(`Checking ${label}… all four checks are running on the file exactly as you provided it.`);
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
          : "The check could not be completed. What to do: check your connection, then try the same image again.";
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
      setError("That file type cannot be checked here. What to do: choose a PNG or JPEG picture (file names ending in .png, .jpg or .jpeg).");
      setStatusLine("Please choose a PNG or JPEG image.");
      return;
    }
    if (engine.maxBytes !== undefined && file.size > engine.maxBytes) {
      const limit = `${Math.round(engine.maxBytes / (1024 * 1024))} MiB`;
      setError(`That file is larger than this page's ${limit} limit, so it was not checked. What to do: export a smaller copy and try again.`);
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

  const parsed = payload?.status === "parsed" && payload.analysis;

  return (
    <>
      <h1>Check an image for hidden information</h1>
      <p>
        Add a PNG or JPEG picture below. CovertLens runs its four checks on
        the file exactly as you provide it (nothing is resized or converted
        first), then explains — in this order — whether the image would be
        delivered, what each check found, and the measurements behind it.
      </p>
      <p>
        Two things to know first: a high score is evidence to look closer,
        never proof that someone hid something; and this page never tries
        to read out (“decode”) any hidden message.
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
        <p className="dropzone-title">Drag and drop a PNG or JPEG picture here</p>
        <p>
          <label className="button button-primary" htmlFor="file-input">
            Choose an image to check
          </label>{" "}
          <span className="note">
            The check starts straight away — there is no separate “upload”
            step. Only PNG and JPEG pictures are accepted.
          </span>
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
        <label htmlFor="fixture-select">
          No image handy? Check a ready-made example instead
        </label>
        <select
          id="fixture-select"
          value={fixtureChoice}
          onChange={(e) => setFixtureChoice(e.target.value)}
          disabled={busy}
        >
          <option value="">{fixtures === null ? "Loading the list of examples…" : "Choose an example…"}</option>
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
          <span className="note">Choose an example from the list first — then this button becomes available.</span>
        )}
        {fixtures !== null && fixtures.length === 0 && (
          <span className="note">The example list could not be loaded. You can still check your own image above.</span>
        )}
      </form>
      {!payload && !busy && (
        <p className="note">
          Nothing has been checked yet. When you add an image, the result
          will appear here, starting with whether the image would be
          delivered.
        </p>
      )}

      <p role="status" aria-live="polite" className="status-line">
        {busy ? statusLine || "Checking your image… larger pictures can take a little while." : statusLine}
      </p>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      {payload && (
        <div ref={resultsRef} tabIndex={-1} className="results">
          <h2>Result for {resultLabel || "your image"}</h2>
          {!parsed ? (
            <p className="alert" role="alert">{statusMessage(payload)}</p>
          ) : (
            <>
              <p className="note">
                {payload.analysis?.media_kind.toUpperCase()} picture
                {payload.analysis?.image?.width
                  ? `, ${payload.analysis.image.width} pixels wide × ${payload.analysis.image.height} pixels tall`
                  : ""}
                .
              </p>
              {payload.analysis?.content_hash && (
                <TechDetails summary="File fingerprint (for matching this exact file later)">
                  <p className="note hash-line">
                    {payload.analysis.content_hash} — a fingerprint computed
                    from the file’s exact contents. Changing even one byte
                    produces a different fingerprint, so this result is tied
                    to this exact file.
                  </p>
                </TechDetails>
              )}
              {payload.decision && <DecisionPanel decision={payload.decision} />}
              <FamilyCards payload={payload} />
              <Overlay
                geometric={payload.geometric}
                imageUrl={previewUrl}
                imageLabel={resultLabel || "Analyzed image"}
              />
              <EvidenceTables payload={payload} />
            </>
          )}
        </div>
      )}
    </>
  );
}
