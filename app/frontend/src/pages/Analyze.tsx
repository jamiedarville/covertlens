import { useEffect, useRef, useState } from "react";
import type { AnalyzePayload, FixtureEntry } from "../types";
import {
  ApiError,
  analyzeFile,
  fetchFixtureFile,
  listFixtures,
  takePreload,
} from "../api";
import { DecisionPanel, EvidenceTables, FamilyCards } from "../components/Results";
import { Overlay } from "../components/Overlay";

function statusMessage(payload: AnalyzePayload): string {
  switch (payload.status) {
    case "parsed":
      return "Analysis complete.";
    case "oversized":
      return `Too large to analyze safely${payload.detail ? `: ${payload.detail}` : ""}. Try a smaller image.`;
    case "timeout":
      return "Analysis ran past its time limit and was stopped. Try a smaller or simpler image.";
    default:
      return `This file could not be analyzed (status: ${payload.status}). PNG and JPEG images are supported.`;
  }
}

export default function Analyze() {
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
    const preload = takePreload();
    if (preload) {
      setPayload(preload.payload);
      setPreviewUrl(preload.imageUrl);
      setResultLabel(preload.label);
      setStatusLine(`Showing the precomputed overlay for ${preload.label}.`);
    }
    let cancelled = false;
    listFixtures()
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
    setStatusLine(`Analyzing ${label}…`);
    setPreviewUrl(await readPreview(file));
    try {
      const result = await analyzeFile(file);
      setPayload(result);
      setResultLabel(label);
      setStatusLine(statusMessage(result));
      requestAnimationFrame(() => resultsRef.current?.focus());
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : "Analysis failed. Check your connection and try again.";
      setError(message);
      setStatusLine(message);
    } finally {
      setBusy(false);
    }
  };

  const takeFile = (file: File | undefined) => {
    if (!file) return;
    const okType = ["image/png", "image/jpeg"].includes(file.type) || /\.(png|jpe?g)$/i.test(file.name);
    if (!okType) {
      setError("Please choose a PNG or JPEG image.");
      setStatusLine("Please choose a PNG or JPEG image.");
      return;
    }
    void run(file, file.name);
  };

  const runExample = async () => {
    const entry = (fixtures ?? []).find((f) => f.fixture_id === fixtureChoice);
    if (!entry) return;
    setBusy(true);
    setError(null);
    setStatusLine(`Loading example ${entry.fixture_id}…`);
    try {
      const file = await fetchFixtureFile(entry);
      await run(file, entry.fixture_id);
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
      <h1>Analyze an image</h1>
      <p>
        Drop a PNG or JPEG below. It is scored on its original bytes across
        the four families, and the geometric overlay is drawn from that one
        response. Nothing you upload is decoded into text here.
      </p>

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
        <p className="dropzone-title">Drag and drop a PNG or JPEG here</p>
        <p>
          <label className="button button-primary" htmlFor="file-input">
            Choose a file
          </label>{" "}
          <span className="note">Analysis starts as soon as you choose.</span>
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
        <label htmlFor="fixture-select">Or analyze a built-in example</label>
        <select
          id="fixture-select"
          value={fixtureChoice}
          onChange={(e) => setFixtureChoice(e.target.value)}
          disabled={busy}
        >
          <option value="">{fixtures === null ? "Loading examples…" : "Choose an example…"}</option>
          {(fixtures ?? []).map((entry) => (
            <option key={entry.fixture_id} value={entry.fixture_id}>
              {entry.fixture_id}
            </option>
          ))}
        </select>
        <button type="submit" className="button" disabled={busy || !fixtureChoice}>
          Analyze example
        </button>
      </form>

      <p role="status" aria-live="polite" className="status-line">
        {busy ? statusLine || "Analyzing…" : statusLine}
      </p>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}

      {payload && (
        <div ref={resultsRef} tabIndex={-1} className="results">
          <h2>Result{resultLabel ? `: ${resultLabel}` : ""}</h2>
          {!parsed ? (
            <p className="alert" role="alert">{statusMessage(payload)}</p>
          ) : (
            <>
              <p className="note hash-line">
                {payload.analysis?.media_kind.toUpperCase()}
                {payload.analysis?.image?.width
                  ? ` · ${payload.analysis.image.width}×${payload.analysis.image.height}px`
                  : ""}
                {payload.analysis?.content_hash
                  ? ` · ${payload.analysis.content_hash}`
                  : ""}
              </p>
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
