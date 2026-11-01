// Generate / red-team page (CL-51): try to smuggle a message
// past the gate, then send it to Analyze in one click. Every
// generation is recorded server-side with source "red_team".

import { useState } from "react";
import { ApiError, generateImage, type GenerateResult } from "../api";
import { fmtExact } from "../format";

const SUBFAMILIES = [
  { value: "height_position", label: "Bar heights" },
  { value: "gap_timing", label: "Gaps between bars" },
  { value: "lit_dark", label: "Lit / dark bars" },
  { value: "colour_code", label: "Bar colours" },
  { value: "angle_tilt", label: "Bar tilt angles" },
];
const GRID_SUBFAMILIES = new Set(["height_position", "gap_timing", "angle_tilt"]);

function num(value: string, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export default function Generate({
  navigate,
}: {
  navigate: (to: string) => void;
}) {
  const [kind, setKind] = useState("geometric");
  const [subfamily, setSubfamily] = useState("height_position");
  const [nElements, setNElements] = useState("12");
  const [sceneSeed, setSceneSeed] = useState("101");
  const [payloadSeed, setPayloadSeed] = useState("202");
  const [payloadMode, setPayloadMode] = useState("word");
  const [payloadText, setPayloadText] = useState("DECAF");
  const [gridChoice, setGridChoice] = useState("declared");
  const [gridBase, setGridBase] = useState("16");
  const [gridStep, setGridStep] = useState("10");
  const [coverSeed, setCoverSeed] = useState("101");
  const [payloadBytes, setPayloadBytes] = useState("64");
  const [mediaKind, setMediaKind] = useState("png");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState("");
  const [result, setResult] = useState<GenerateResult | null>(null);

  const gridAllowed = GRID_SUBFAMILIES.has(subfamily);

  const buildParams = (): Record<string, unknown> => {
    if (kind === "geometric") {
      const params: Record<string, unknown> = {
        kind,
        subfamily,
        n_elements: num(nElements, 12),
        scene_seed: num(sceneSeed, 101),
        payload_seed: num(payloadSeed, 202),
        payload_mode: payloadMode,
        payload_text: payloadText,
        grid_choice: gridAllowed ? gridChoice : "declared",
      };
      if (gridAllowed && gridChoice === "custom") {
        params.grid_base = num(gridBase, 16);
        params.grid_step = num(gridStep, 10);
      }
      return params;
    }
    if (kind === "metadata") {
      return {
        kind,
        media_kind: mediaKind,
        cover_seed: num(coverSeed, 101),
        payload_seed: num(payloadSeed, 202),
        payload_bytes: num(payloadBytes, 32),
      };
    }
    return {
      kind,
      cover_seed: num(coverSeed, 101),
      payload_seed: num(payloadSeed, 202),
      payload_bytes: num(payloadBytes, 64),
    };
  };

  const onGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setStatusLine("Generating…");
    try {
      const generated = await generateImage(buildParams());
      setResult(generated);
      setStatusLine(`Generated ${generated.fixture_id}. Recorded as a red-team fixture.`);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "Generation failed. Try different parameters.";
      setError(message);
      setStatusLine(message);
    } finally {
      setBusy(false);
    }
  };

  const sendToAnalyze = () => {
    if (!result) return;
    const filename = result.image_url.split("/").pop() ?? "";
    navigate(`/analyze?generated=${encodeURIComponent(filename)}`);
  };

  return (
    <>
      <h1>Generate a covert image</h1>
      <p>
        Try to smuggle a message past the gate. Pick an encoder, hide a word
        or a seeded payload, then send the result to Analyze and see whether
        the discovered grid, structure score, and verdict give you away.
        Every image you generate is recorded with its full parameters as a
        red-team fixture, so attacks that work become test data.
      </p>

      <form onSubmit={onGenerate} className="generate-form">
        <div className="form-grid">
          <label>
            Encoder
            <select value={kind} onChange={(e) => setKind(e.target.value)} disabled={busy}>
              <option value="geometric">Geometric (visible pattern)</option>
              <option value="spatial_lsb">Spatial LSB (PNG pixels)</option>
              <option value="jpeg_dct">JPEG DCT (frequency coefficients)</option>
              <option value="metadata">Metadata fields</option>
            </select>
          </label>
        </div>

        {kind === "geometric" && (
          <fieldset>
            <legend>Scene and payload</legend>
            <div className="form-grid">
              <label>
                Subfamily
                <select value={subfamily} onChange={(e) => setSubfamily(e.target.value)} disabled={busy}>
                  {SUBFAMILIES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </label>
              <label>
                Elements (4–40)
                <input type="number" min={4} max={40} value={nElements}
                  onChange={(e) => setNElements(e.target.value)} disabled={busy} />
              </label>
              <label>
                Scene seed
                <input type="number" value={sceneSeed}
                  onChange={(e) => setSceneSeed(e.target.value)} disabled={busy} />
              </label>
              <label>
                Payload seed
                <input type="number" value={payloadSeed}
                  onChange={(e) => setPayloadSeed(e.target.value)} disabled={busy} />
              </label>
              <label>
                Payload mode
                <select value={payloadMode} onChange={(e) => setPayloadMode(e.target.value)} disabled={busy}>
                  <option value="random">Random symbols</option>
                  <option value="word">Word</option>
                  <option value="morse">Morse</option>
                  <option value="ascii">ASCII</option>
                  <option value="custom">Custom text (as ASCII)</option>
                </select>
              </label>
              {payloadMode !== "random" && (
                <label>
                  Payload text
                  <input type="text" value={payloadText} maxLength={64}
                    onChange={(e) => setPayloadText(e.target.value)} disabled={busy} />
                  <span className="note">
                    {payloadMode === "word" && subfamily === "height_position"
                      ? "Bar heights carry letters A–H, repeated to fill the scene."
                      : "Encoded into the subfamily alphabet, repeated to fill the scene."}
                  </span>
                </label>
              )}
              <label>
                Grid
                <select value={gridAllowed ? gridChoice : "declared"}
                  onChange={(e) => setGridChoice(e.target.value)}
                  disabled={busy || !gridAllowed}>
                  <option value="declared">Declared (published grid)</option>
                  <option value="custom">Custom base and step</option>
                  <option value="random_hidden">Random, hidden from you</option>
                </select>
                {!gridAllowed && (
                  <span className="note">Lit/dark and colour use fixed levels.</span>
                )}
                {gridAllowed && gridChoice === "random_hidden" && (
                  <span className="note">You will not be told the grid. See if Analyze finds it.</span>
                )}
              </label>
              {gridAllowed && gridChoice === "custom" && (
                <>
                  <label>
                    Grid base
                    <input type="number" step="any" value={gridBase}
                      onChange={(e) => setGridBase(e.target.value)} disabled={busy} />
                  </label>
                  <label>
                    Grid step
                    <input type="number" step="any" value={gridStep}
                      onChange={(e) => setGridStep(e.target.value)} disabled={busy} />
                  </label>
                </>
              )}
            </div>
            <p className="note">Gap scenes hold at most 10 elements and angle scenes 7 at this canvas size; larger requests are capped.</p>
          </fieldset>
        )}

        {kind !== "geometric" && (
          <fieldset>
            <legend>Cover and payload</legend>
            <div className="form-grid">
              {kind === "metadata" && (
                <label>
                  Media kind
                  <select value={mediaKind} onChange={(e) => setMediaKind(e.target.value)} disabled={busy}>
                    <option value="png">PNG</option>
                    <option value="jpeg">JPEG</option>
                  </select>
                </label>
              )}
              <label>
                Cover seed
                <input type="number" value={coverSeed}
                  onChange={(e) => setCoverSeed(e.target.value)} disabled={busy} />
              </label>
              <label>
                Payload seed
                <input type="number" value={payloadSeed}
                  onChange={(e) => setPayloadSeed(e.target.value)} disabled={busy} />
              </label>
              <label>
                Payload bytes (1–512)
                <input type="number" min={1} max={512} value={payloadBytes}
                  onChange={(e) => setPayloadBytes(e.target.value)} disabled={busy} />
                <span className="note">Classic encoders embed seeded payload bytes.</span>
              </label>
            </div>
          </fieldset>
        )}

        <p>
          <button type="submit" className="button button-primary" disabled={busy}>
            Generate image
          </button>
        </p>
      </form>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && <p className="alert" role="alert">{error}</p>}

      {result && (
        <section aria-labelledby="generated-heading" className="card">
          <div className="card-head">
            <h2 id="generated-heading">Your covert image</h2>
            <span className="chip">source: red_team</span>
          </div>
          <img className="skyline-img" src={result.image_url}
            alt={`Generated ${result.fixture_id}`} />
          <dl className="kv kv-wide">
            <div><dt>Fixture</dt><dd>{result.fixture_id}</dd></div>
            <div><dt>Content hash</dt><dd>{result.content_hash}</dd></div>
            {Object.entries(result.parameters).map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{typeof value === "object" ? JSON.stringify(value) : fmtExact(value)}</dd>
              </div>
            ))}
          </dl>
          <p>
            <button type="button" className="button button-primary" onClick={sendToAnalyze}>
              Send to Analyze
            </button>{" "}
            <a href={result.image_url} download>Download image</a>
          </p>
          <p className="note">
            Analyze never shows decoded text; it reports the discovered
            step, structure score, and verdict as evidence.
          </p>
        </section>
      )}
    </>
  );
}
