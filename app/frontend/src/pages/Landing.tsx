import { useEffect, useState } from "react";
import type { Comparison, ComparisonSide } from "../types";
import { fetchComparison, fixtureImageUrl, storePreload } from "../api";
import { classificationLabel, classificationMeaning, fmtExact, fmtNum, fmtScore } from "../format";
import { SequencePlot } from "../components/Charts";
import { StartSteps, TechDetails } from "../components/Help";

function SkylineSide({
  heading,
  side,
  onOpen,
}: {
  heading: string;
  side: ComparisonSide;
  onOpen: (side: ComparisonSide, heading: string) => void;
}) {
  const payload = side.payload;
  const geometric = payload.geometric;
  const finding = payload.analysis?.findings.find((f) => f.family === "geometric");
  const heightChannel = geometric?.channels?.height;
  const values =
    geometric?.overlay?.channels?.height?.values ??
    (geometric?.segmentation?.sequences.height ?? []).filter(
      (v): v is number => v !== null,
    );
  return (
    <article className="card skyline" aria-label={heading}>
      <div className="card-head">
        <h3>{heading}</h3>
        <span className="badge" title={geometric?.classification ?? undefined}>
          {classificationLabel(geometric?.classification ?? null)}
        </span>
      </div>
      <img
        className="skyline-img"
        src={fixtureImageUrl(side.content_hash)}
        alt={`${heading}: a row of skyline bars (${side.fixture_id})`}
        loading="lazy"
      />
      <p className="note">{classificationMeaning(geometric?.classification ?? null)}</p>
      <dl className="kv">
        <div>
          <dt>Shape-pattern score (0 to 1; higher means stronger pattern evidence — not proof)</dt>
          <dd title={finding ? String(finding.score) : undefined}>
            {finding ? fmtScore(finding.score) : "—"}
          </dd>
        </div>
        <div>
          <dt>Regular spacing found in the bar heights (pixels)</dt>
          <dd>{fmtExact(heightChannel?.step ?? null)}</dd>
        </div>
        <div>
          <dt>How neatly heights fit that spacing (0 to 1; 1 is a perfect fit)</dt>
          <dd>{fmtExact(heightChannel?.rayleigh_R ?? null)}</dd>
        </div>
        <div>
          <dt>How much it looks like an ordinary chart (0 to 1)</dt>
          <dd>{fmtNum(geometric?.chart_likeness?.score ?? null)}</dd>
        </div>
      </dl>
      <TechDetails summary="Technical names for these measurements">
        <p className="note">
          Geometric score · height grid step · Rayleigh R · chart-likeness,
          exactly as named in the API response.
        </p>
      </TechDetails>
      {values.length > 0 && heightChannel && (
        <SequencePlot
          values={values}
          unit="px"
          step={heightChannel.step}
          offset={heightChannel.offset}
          symbolRange={heightChannel.symbol_range}
          title={`Building heights, ${heading.toLowerCase()}`}
        />
      )}
      <button type="button" className="button" onClick={() => onOpen(side, heading)}>
        See the measurements drawn on this image
      </button>
    </article>
  );
}

export default function Landing({
  navigate,
}: {
  navigate: (to: string) => void;
}) {
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [computing, setComputing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let tries = 0;
    const load = async () => {
      try {
        const result = await fetchComparison();
        if (cancelled) return;
        if (result === "computing") {
          setComputing(true);
          tries += 1;
          if (tries <= 8) {
            timer = window.setTimeout(load, 2500);
          } else {
            setLoadError("The ready-made example below is taking longer than usual to prepare. What to do: reload this page in a moment, or skip the example and check your own image now.");
          }
          return;
        }
        setComputing(false);
        setComparison(result);
      } catch {
        if (!cancelled) {
          setComputing(false);
          setLoadError("The ready-made example below could not be loaded. Nothing is broken for you: you can still check your own image using the button above.");
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  const openOverlay = (side: ComparisonSide, heading: string) => {
    storePreload({
      payload: side.payload,
      imageUrl: fixtureImageUrl(side.content_hash),
      label: `${heading} (${side.fixture_id})`,
    });
    navigate("/analyze");
  };

  return (
    <>
      <h1>CovertLens: checks images for hidden information</h1>
      <p className="lede">
        <span>
          CovertLens checks images that AI agents send each other for signs
          of hidden information. It shows what was found and whether each
          image was allowed through to the recipient.
        </span>
        <span>
          Why this matters: in the experiments CovertLens guards, agents are
          only allowed to communicate through agreed channels. Hiding extra
          information inside a picture would break the rules — so every
          image is checked before the recipient can see it.
        </span>
        <span>
          The checker looks in four places: tiny pixel changes, JPEG
          compression data, text stored inside the file, and the visible
          shapes and patterns. Each check produces a score from 0 to 1.
        </span>
        <span>
          A score is evidence to look closer — never proof, and never an
          accusation on its own. “Nothing found” also does not prove that
          nothing is hidden.
        </span>
      </p>
      <StartSteps heading="New here? Start in three steps">
        <li>
          Look at the two city-skyline pictures below. One is ordinary; the
          other hides a pattern in its building heights. This shows what
          CovertLens can spot.
        </li>
        <li>
          Then choose <strong>Check your own image</strong> and add any PNG
          or JPEG picture. You will see what each of the four checks found,
          in plain English.
        </li>
        <li>
          Or open <strong>Delivery gate (live)</strong> in the menu to watch
          an image being checked and either delivered or held back before
          the recipient sees it.
        </li>
      </StartSteps>
      <p>
        <button type="button" className="button button-primary" onClick={() => navigate("/analyze")}>
          Check your own image
        </button>{" "}
        <a href="/docs">Developers: browse the API instead</a>
      </p>

      <section aria-labelledby="skyline-heading">
        <h2 id="skyline-heading">Try it: two skylines, one hidden pattern</h2>
        <p>
          The only difference between these two pictures is the buildings’
          heights. In one picture the heights follow a regular spacing that
          could be used to spell something out. Both were checked before
          this page loaded. Choose either button to see the measurements
          drawn on top of the picture, with each number explained.
        </p>
        {computing && !comparison && (
          <p role="status">Preparing the ready-made example for you… this usually takes a few seconds after the server starts.</p>
        )}
        {loadError && <p className="alert" role="alert">{loadError}</p>}
        {comparison && (
          <div className="card-grid card-grid-2">
            <SkylineSide heading="Ordinary skyline (nothing hidden)" side={comparison.clean} onOpen={openOverlay} />
            <SkylineSide heading="Skyline with a hidden pattern in its heights" side={comparison.encoded} onOpen={openOverlay} />
          </div>
        )}
      </section>

      <section aria-labelledby="reading-heading">
        <h2 id="reading-heading">How to read the result</h2>
        <ul>
          <li>
            <strong>Regular spacing alone is not suspicious.</strong> If
            heights land exactly on evenly spaced values (specialists call
            this “quantized”), that also happens in perfectly ordinary
            charts.
          </li>
          <li>
            <strong>What matters is whether the pattern looks
            deliberate.</strong> CovertLens shuffles the values many times
            and asks how often a shuffled version would look just as
            organised. Only if the real order beats the shuffles under a
            code declared in advance is a pattern reported.
          </li>
          <li>
            <strong>No hidden text is shown to you here.</strong> This page
            shows measurements and scores. It never displays a “decoded
            message”.
          </li>
        </ul>
      </section>
    </>
  );
}
