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
import { fmtExact, humanizeKey, verdictLabel } from "../format";
import { StartSteps, TechDetails } from "../components/Help";

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
    setStatusLine("Making your test picture…");
    try {
      const generated = await generateImage(buildParams());
      setResult(generated);
      setStatusLine(`Your test picture is ready below (${generated.fixture_id}). It has been saved on the server together with the settings you used, so it can become future test data. Next step: send it to “Check an image” and see whether the checks spot it.`);
    } catch (err) {
      const message =
        err instanceof ApiError ? err.message : "The picture could not be made with those settings. What to do: change one setting (for example fewer bars) and try again.";
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
      <h1>Make a test image with something hidden in it</h1>
      <p>
        This page is for testing the checker: you deliberately hide
        information in a picture (“red-teaming” the gate), then send the
        picture to “Check an image” and see whether CovertLens spots it.
        Anything you manage to smuggle through teaches the project where
        its blind spots are — every picture you make here is saved, with
        the settings you used, as future test data.
      </p>
      <StartSteps heading="Try it in three steps">
        <li>Choose <strong>where to hide the information</strong> below (the visible pattern is the easiest to understand).</li>
        <li>Press <strong>Make the test picture</strong>. The defaults are fine for a first try.</li>
        <li>Choose <strong>Send it to “Check an image”</strong> and see whether the checks find your hiding place.</li>
      </StartSteps>

      <form onSubmit={onGenerate} className="generate-form">
        <div className="form-grid">
          <label>
            Where should the information be hidden?
            <select value={kind} onChange={(e) => setKind(e.target.value)} disabled={busy}>
              <option value="geometric">In the visible pattern itself (bar heights, gaps, colours…)</option>
              <option value="spatial_lsb">In tiny pixel changes in a PNG (spatial LSB)</option>
              <option value="jpeg_dct">In the JPEG compression numbers (DCT)</option>
              <option value="metadata">In text stored inside the file (metadata)</option>
            </select>
            <span className="note">This chooses which of the four checks you are trying to beat. Each hiding place has its own settings below.</span>
          </label>
        </div>

        {kind === "geometric" && (
          <fieldset>
            <legend>The picture and what to hide in it</legend>
            <p className="note">
              The picture will show a row of bars, like a skyline. Your
              hidden information (the “payload”) is written into one
              measurable feature of those bars. A “seed” is simply a
              starting number for the random choices: the same seed always
              makes the same picture, so share the seed to let someone
              else recreate your exact test.
            </p>
            <div className="form-grid">
              <label>
                Hide it in which feature of the bars?
                <select value={subfamily} onChange={(e) => setSubfamily(e.target.value)} disabled={busy}>
                  {SUBFAMILIES.map((s) => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </label>
              <label>
                How many bars? (4 to 40)
                <input type="number" min={4} max={40} value={nElements}
                  onChange={(e) => setNElements(e.target.value)} disabled={busy} />
                <span className="note">More bars can carry more hidden information — and give the checker more to measure.</span>
              </label>
              <label>
                Scene seed (starting number for the ordinary parts)
                <input type="number" value={sceneSeed}
                  onChange={(e) => setSceneSeed(e.target.value)} disabled={busy} />
              </label>
              <label>
                Hidden-content seed (starting number for random hidden content)
                <input type="number" value={payloadSeed}
                  onChange={(e) => setPayloadSeed(e.target.value)} disabled={busy} />
              </label>
              <label>
                What should be hidden?
                <select value={payloadMode} onChange={(e) => setPayloadMode(e.target.value)} disabled={busy}>
                  <option value="random">Random symbols (no meaning — hardest to tell from chance)</option>
                  <option value="word">A short word, repeated</option>
                  <option value="morse">Text in Morse code</option>
                  <option value="ascii">Text as computer character codes (ASCII)</option>
                  <option value="custom">Your own text (written as ASCII)</option>
                </select>
                <span className="note">Meaningful content (words, Morse, text) is what the “deliberate pattern” test looks for. Random symbols test whether spacing alone gets flagged.</span>
              </label>
              {payloadMode !== "random" && (
                <label>
                  Text to hide (up to 64 characters)
                  <input type="text" value={payloadText} maxLength={64}
                    onChange={(e) => setPayloadText(e.target.value)} disabled={busy} />
                  <span className="note">
                    {payloadMode === "word" && subfamily === "height_position"
                      ? "Only the letters A to H can be carried by bar heights here; your word is repeated until the row of bars is filled. For example, DECAF."
                      : "Your text is turned into the symbols this hiding place can carry, and repeated until the row of bars is filled."}
                  </span>
                </label>
              )}
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
                  <span className="note">Not available for this hiding place: lit/dark and colour always use fixed levels, so there is no spacing to choose.</span>
                )}
                {gridAllowed && gridChoice === "random_hidden" && (
                  <span className="note">The spacing will not be shown to you either. The question is whether “Check an image” can discover it from the picture alone.</span>
                )}
                {gridAllowed && gridChoice === "declared" && (
                  <span className="note">Using the spacing the checker already knows makes the pattern easiest to spot — a good first test.</span>
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
                    Step size between allowed values (grid step)
                    <input type="number" step="any" value={gridStep}
                      onChange={(e) => setGridStep(e.target.value)} disabled={busy} />
                    <span className="note">For example 10 means allowed heights are 16, 26, 36, … pixels.</span>
                  </label>
                </>
              )}
            </div>
            <p className="note">At this picture size, “gaps” fit at most 10 bars and “tilt” at most 7; if you ask for more, the number is reduced for you.</p>
          </fieldset>
        )}

        {kind !== "geometric" && (
          <fieldset>
            <legend>The ordinary picture, and what to hide in it</legend>
            <p className="note">
              A plain “cover” picture is generated first, then your hidden
              bytes (the “payload”) are written into it. A seed is a
              starting number for random choices: the same seeds always
              recreate the same test.
            </p>
            <div className="form-grid">
              {kind === "metadata" && (
                <label>
                  File type to produce
                  <select value={mediaKind} onChange={(e) => setMediaKind(e.target.value)} disabled={busy}>
                    <option value="png">PNG picture</option>
                    <option value="jpeg">JPEG picture</option>
                  </select>
                  <span className="note">The hidden bytes go into text fields stored inside the file, in either type.</span>
                </label>
              )}
              <label>
                Cover seed (starting number for the ordinary picture)
                <input type="number" value={coverSeed}
                  onChange={(e) => setCoverSeed(e.target.value)} disabled={busy} />
              </label>
              <label>
                Hidden-content seed (starting number for the hidden bytes)
                <input type="number" value={payloadSeed}
                  onChange={(e) => setPayloadSeed(e.target.value)} disabled={busy} />
              </label>
              <label>
                How much to hide? (1 to 512 bytes)
                <input type="number" min={1} max={512} value={payloadBytes}
                  onChange={(e) => setPayloadBytes(e.target.value)} disabled={busy} />
                <span className="note">The hidden bytes are generated from the seed above. Hiding more is usually easier for the checker to spot; hiding very little is the harder test.</span>
              </label>
            </div>
          </fieldset>
        )}

        <p>
          <button type="submit" className="button button-primary" disabled={busy}>
            Make the test picture
          </button>{" "}
          <span className="note">The picture is saved on the server with these settings. Nothing is sent to any recipient.</span>
        </p>
      </form>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && <p className="alert" role="alert">{error}</p>}

      {result && (
        <section aria-labelledby="generated-heading" className="card">
          <div className="card-head">
            <h2 id="generated-heading">Your test picture, with information hidden in it</h2>
            <span className="chip" title="source: red_team">made for testing the checker</span>
          </div>
          <img className="skyline-img" src={result.image_url}
            alt={`Your generated test picture (${result.fixture_id})`} />
          <p className="note">
            To your eye this should look ordinary — that is the point.
            The next step is to find out whether it also looks ordinary to
            the checker.
          </p>
          <TechDetails summary="Saved settings and file fingerprint (to recreate this exact test)">
            <dl className="kv kv-wide">
              <div><dt>Test picture name</dt><dd>{result.fixture_id}</dd></div>
              <div><dt>File fingerprint</dt><dd>{result.content_hash}</dd></div>
              {Object.entries(result.parameters).map(([key, value]) => (
                <div key={key}>
                  <dt title={key}>{humanizeKey(key)}</dt>
                  <dd>{typeof value === "object" ? JSON.stringify(value) : fmtExact(value)}</dd>
                </div>
              ))}
            </dl>
          </TechDetails>
          <p>
            <button type="button" className="button button-primary" onClick={sendToAnalyze}>
              Send it to “Check an image” — did the checker spot it?
            </button>{" "}
            <a href={result.image_url} download>Download this picture</a>
          </p>
          <p className="note">
            The check page will not read your hidden text back to you. It
            reports whether it found your regular spacing, whether the
            pattern looks deliberate, and whether the picture would be
            delivered or held back.
          </p>
          <LeaderboardSubmit
            key={result.artifact_version_id}
            artifactVersionId={result.artifact_version_id}
            navigate={navigate}
          />
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
      setMessage(err instanceof ApiError ? err.message : "Your entry could not be added to the leaderboard. What to do: try again in a moment — your picture itself is unaffected.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="example-row"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <p className="note">
        Optional competition: enter this picture in the public
        leaderboard. The server re-checks the exact saved picture (you
        cannot upload a substitute), and ranks it by how much hidden
        information it carried past each decision cut-off. Only your
        chosen name is sent.
      </p>
      <label htmlFor="leaderboard-name">Name to show on the leaderboard (optional)</label>
      <input
        id="leaderboard-name"
        value={name}
        maxLength={40}
        onChange={(e) => setName(e.target.value)}
        placeholder="your team"
        disabled={busy || entry !== null}
      />
      <button type="submit" className="button" disabled={busy || entry !== null}>
        Enter this picture in the leaderboard
      </button>
      {entry !== null && (
        <span className="note">Already entered — one entry per picture.</span>
      )}
      {entry && (
        <p role="status" className="note">
          {entry.status === "pending"
            ? "Entered. It will appear on the public board once an operator has approved it. "
            : `It was checked again by the server: decision “${verdictLabel(entry.outcome.verdict).toLowerCase()}”, carrying ${entry.outcome.payload.bits} bits of hidden information. `}
          <a
            href="/leaderboard"
            onClick={(e) => {
              e.preventDefault();
              navigate("/leaderboard");
            }}
          >
            View the leaderboard
          </a>
        </p>
      )}
      {message && <p className="alert" role="alert">{message}</p>}
    </form>
  );
}
