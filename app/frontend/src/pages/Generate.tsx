// Generate / red-team page (CL-51): try to smuggle a message
// past the gate, then send it to Analyze in one click. Every
// generation is recorded server-side with source "red_team".

import { useState } from "react";
import {
  ApiError,
  generateImage,
  submitToLeaderboard,
  type GenerateResult,
  type LeaderboardEntry,
} from "../api";
import { fmtExact, humanizeKey } from "../format";
import { AdvancedSettings, TechnicalBreakdown } from "../components/Help";
import { VerdictLight } from "../components/TrafficLight";

// The four hiding places, one per check CovertLens runs.
const HIDING_CHOICES = [
  {
    value: "geometric",
    title: "Shapes and patterns",
    about: "In the bars of a chart-like picture: their heights, gaps, colours or tilt.",
  },
  {
    value: "spatial_lsb",
    title: "Tiny colour changes",
    about: "In colour changes too small for the eye to see. Makes a PNG image.",
  },
  {
    value: "jpeg_dct",
    title: "JPEG compression",
    about: "In the way a JPEG photo is compressed. Makes a JPEG image.",
  },
  {
    value: "metadata",
    title: "File details",
    about: "In the text stored inside the file, such as its description.",
  },
];

const SUBFAMILIES = [
  { value: "height_position", label: "In the bar heights" },
  { value: "gap_timing", label: "In the gaps between bars" },
  { value: "lit_dark", label: "In which bars are lit or dark" },
  { value: "colour_code", label: "In the bar colours" },
  { value: "angle_tilt", label: "In how much the bars tilt" },
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
    setStatusLine("Making your test image…");
    try {
      const generated = await generateImage(buildParams());
      setResult(generated);
      setStatusLine("Your test image is ready below. Next: press “Check it now” to see whether CovertLens spots the hidden message.");
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "The image couldn’t be made with those settings. What to do: change one setting (for example, fewer bars) and try again.";
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

  const textHint =
    payloadMode === "word" && subfamily === "height_position"
      ? "Bar heights can only carry the letters A to H, so use those letters (for example, DECAF). Your word is repeated to fill the row of bars."
      : "Your message is repeated to fill the row of bars.";

  return (
    <>
      <h1>Make a test image</h1>
      <p className="lede">
        Hide a secret message in an image yourself, then see whether
        CovertLens catches it. Anything that slips through shows the
        project a blind spot to fix.
      </p>

      <form onSubmit={onGenerate} className="generate-form">
        <fieldset>
          <legend>1. Where should the message be hidden?</legend>
          <div className="choice-list">
            {HIDING_CHOICES.map((choice) => (
              <label
                key={choice.value}
                className={kind === choice.value ? "choice choice-active" : "choice"}
              >
                <input
                  type="radio"
                  name="hiding-place"
                  value={choice.value}
                  checked={kind === choice.value}
                  onChange={() => setKind(choice.value)}
                  disabled={busy}
                />
                <span>
                  <strong>{choice.title}</strong>
                  <span className="choice-about">{choice.about}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend>2. What should be hidden?</legend>
          {kind === "geometric" ? (
            <div className="form-grid">
              <label>
                Which part of the bars?
                <select value={subfamily} onChange={(e) => setSubfamily(e.target.value)} disabled={busy}>
                  {SUBFAMILIES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </label>
              {payloadMode !== "random" && (
                <label>
                  Message to hide (up to 64 characters)
                  <input type="text" value={payloadText} maxLength={64}
                    onChange={(e) => setPayloadText(e.target.value)} disabled={busy} />
                  <span className="note">{textHint}</span>
                </label>
              )}
            </div>
          ) : (
            <div className="form-grid">
              {kind === "metadata" && (
                <label>
                  Make a PNG or a JPEG?
                  <select value={mediaKind} onChange={(e) => setMediaKind(e.target.value)} disabled={busy}>
                    <option value="png">PNG image</option>
                    <option value="jpeg">JPEG photo</option>
                  </select>
                </label>
              )}
              <label>
                How much to hide? (1 to 512 bytes)
                <input type="number" min={1} max={512} value={payloadBytes}
                  onChange={(e) => setPayloadBytes(e.target.value)} disabled={busy} />
                <span className="note">The message is made of random bytes. Hiding a lot is usually easier to catch; hiding a little is the harder test.</span>
              </label>
            </div>
          )}

          <AdvancedSettings id="generate-advanced">
            <p className="note">
              A “seed” is a starting number for the random choices: the same
              seed always makes the same image, so you can share it to let
              someone recreate your exact test.
            </p>
            {kind === "geometric" ? (
              <>
                <div className="form-grid">
                  <label>
                    How many bars? (4 to 40)
                    <input type="number" min={4} max={40} value={nElements}
                      onChange={(e) => setNElements(e.target.value)} disabled={busy} />
                    <span className="note">More bars can carry more hidden information, and give the checker more to measure.</span>
                  </label>
                  <label>
                    Scene seed (for the ordinary parts of the picture)
                    <input type="number" value={sceneSeed}
                      onChange={(e) => setSceneSeed(e.target.value)} disabled={busy} />
                  </label>
                  <label>
                    Message seed (for random messages)
                    <input type="number" value={payloadSeed}
                      onChange={(e) => setPayloadSeed(e.target.value)} disabled={busy} />
                  </label>
                  <label>
                    Kind of message
                    <select value={payloadMode} onChange={(e) => setPayloadMode(e.target.value)} disabled={busy}>
                      <option value="word">A short word, repeated</option>
                      <option value="random">Random symbols (no meaning; hardest to tell from chance)</option>
                      <option value="morse">Text in Morse code</option>
                      <option value="ascii">Text as computer character codes (ASCII)</option>
                      <option value="custom">Your own text (written as ASCII)</option>
                    </select>
                    <span className="note">Words and text are what the “deliberate pattern” check looks for. Random symbols test whether regular spacing alone gets flagged.</span>
                  </label>
                  <label>
                    Which regular spacing (“grid”) should the values follow?
                    <select value={gridAllowed ? gridChoice : "declared"}
                      onChange={(e) => setGridChoice(e.target.value)}
                      disabled={busy || !gridAllowed}>
                      <option value="declared">The published one the checker already knows about</option>
                      <option value="custom">One I choose myself (starting value and step size)</option>
                      <option value="random_hidden">A random one, kept secret from me too</option>
                    </select>
                    {!gridAllowed && (
                      <span className="note">Not available here: lit/dark and colour always use fixed levels, so there’s no spacing to choose.</span>
                    )}
                    {gridAllowed && gridChoice === "random_hidden" && (
                      <span className="note">The spacing won’t be shown to you either. The question is whether the checker can discover it from the picture alone.</span>
                    )}
                    {gridAllowed && gridChoice === "declared" && (
                      <span className="note">Using the spacing the checker already knows makes the pattern easiest to spot: a good first test.</span>
                    )}
                  </label>
                  {gridAllowed && gridChoice === "custom" && (
                    <>
                      <label>
                        Spacing starts at (grid base)
                        <input type="number" step="any" value={gridBase}
                          onChange={(e) => setGridBase(e.target.value)} disabled={busy} />
                        <span className="note">The smallest value, for example a shortest bar of 16 pixels.</span>
                      </label>
                      <label>
                        Step between allowed values (grid step)
                        <input type="number" step="any" value={gridStep}
                          onChange={(e) => setGridStep(e.target.value)} disabled={busy} />
                        <span className="note">For example, 10 means allowed heights are 16, 26, 36, … pixels.</span>
                      </label>
                    </>
                  )}
                </div>
                <p className="note">At this picture size, “gaps” fit at most 10 bars and “tilt” at most 7; if you ask for more, the number is reduced for you.</p>
              </>
            ) : (
              <div className="form-grid">
                <label>
                  Cover seed (for the ordinary picture)
                  <input type="number" value={coverSeed}
                    onChange={(e) => setCoverSeed(e.target.value)} disabled={busy} />
                </label>
                <label>
                  Message seed (for the hidden bytes)
                  <input type="number" value={payloadSeed}
                    onChange={(e) => setPayloadSeed(e.target.value)} disabled={busy} />
                </label>
              </div>
            )}
          </AdvancedSettings>
        </fieldset>

        <p>
          <button type="submit" className="button button-primary button-large" disabled={busy}>
            Make the test image
          </button>
        </p>
        <p className="note">Nothing is sent to anyone. The image is saved, with your settings, so it can be used as test data.</p>
      </form>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && <p className="alert" role="alert">{error}</p>}

      {result && (
        <section aria-labelledby="generated-heading" className="card">
          <h2 id="generated-heading">Your test image</h2>
          <img className="skyline-img" src={result.image_url}
            alt="Your test image, with a message hidden in it" />
          <p>
            It should look ordinary to you: that’s the point. Now find out
            whether CovertLens can tell.
          </p>
          <p>
            <button type="button" className="button button-primary" onClick={sendToAnalyze}>
              Check it now
            </button>{" "}
            <a href={result.image_url} download>Download it</a>
          </p>
          <LeaderboardSubmit
            key={result.artifact_version_id}
            artifactVersionId={result.artifact_version_id}
            navigate={navigate}
          />
          <TechnicalBreakdown
            id="generate-breakdown"
            note="the saved settings and file fingerprint, to recreate this exact test"
          >
            <h3>Saved settings</h3>
            <dl className="kv kv-wide">
              <div><dt>Test image name</dt><dd>{result.fixture_id}</dd></div>
              <div><dt>File fingerprint</dt><dd>{result.content_hash}</dd></div>
              <div><dt>Recorded source</dt><dd>red_team (made for testing the checker)</dd></div>
              {Object.entries(result.parameters).map(([key, value]) => (
                <div key={key}>
                  <dt title={key}>{humanizeKey(key)}</dt>
                  <dd>{typeof value === "object" ? JSON.stringify(value) : fmtExact(value)}</dd>
                </div>
              ))}
            </dl>
          </TechnicalBreakdown>
        </section>
      )}
    </>
  );
}

// Submit this generation to the leaderboard (CL-70). The server
// re-scores the stored bytes; only the artifact id and a name are sent.
function LeaderboardSubmit({
  artifactVersionId,
  navigate,
}: {
  artifactVersionId: string;
  navigate: (to: string) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [entry, setEntry] = useState<LeaderboardEntry | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setMessage(null);
    try {
      setEntry(await submitToLeaderboard(artifactVersionId, name.trim()));
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Your entry couldn’t be added to the leaderboard. What to do: try again in a moment. Your image itself is unaffected.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="leaderboard-entry"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <h3>Optional: enter it in the leaderboard</h3>
      <p className="note">
        The server checks this exact saved image again and ranks it by how
        much hidden information got past. Only the name you choose is sent.
      </p>
      <p className="example-row">
        <label htmlFor="leaderboard-name">Name to show</label>
        <input
          id="leaderboard-name"
          value={name}
          maxLength={40}
          onChange={(e) => setName(e.target.value)}
          placeholder="your team"
          disabled={busy || entry !== null}
        />
        <button type="submit" className="button" disabled={busy || entry !== null}>
          Enter it
        </button>
        {entry !== null && <span className="note">Already entered (one entry per image).</span>}
      </p>
      {entry && (
        <p role="status" className="note">
          {entry.status === "pending" ? (
            "Entered. It will appear on the board once an operator approves it. "
          ) : (
            <>
              Checked again by the server: <VerdictLight verdict={entry.outcome.verdict} />, carrying{" "}
              {entry.outcome.payload.bits} bits of hidden information.{" "}
            </>
          )}
          <a
            href="/leaderboard"
            onClick={(e) => {
              e.preventDefault();
              navigate("/leaderboard");
            }}
          >
            See the leaderboard
          </a>
        </p>
      )}
      {message && <p className="alert" role="alert">{message}</p>}
    </form>
  );
}
