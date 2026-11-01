import { useEffect, useState } from "react";
import type { Comparison, ComparisonSide } from "../types";
import { fetchComparison, fixtureImageUrl, storePreload } from "../api";
import { classificationLabel, fmtExact, fmtNum, fmtScore } from "../format";
import { SequencePlot } from "../components/Charts";

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
  const heightChannel = geometric?.channels.height;
  const values =
    geometric?.overlay?.channels.height?.values ??
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
      <dl className="kv">
        <div>
          <dt>Geometric score</dt>
          <dd title={finding ? String(finding.score) : undefined}>
            {finding ? fmtScore(finding.score) : "—"}
          </dd>
        </div>
        <div>
          <dt>Height grid step</dt>
          <dd>{fmtExact(heightChannel?.step ?? null)}</dd>
        </div>
        <div>
          <dt>Rayleigh R</dt>
          <dd>{fmtExact(heightChannel?.rayleigh_R ?? null)}</dd>
        </div>
        <div>
          <dt>Chart-likeness</dt>
          <dd>{fmtNum(geometric?.chart_likeness?.score ?? null)}</dd>
        </div>
      </dl>
      {values.length > 0 && heightChannel && (
        <SequencePlot
          values={values}
          unit="px"
          step={heightChannel.step}
          offset={heightChannel.offset}
          symbols={heightChannel.symbols}
          title={`Building heights, ${heading.toLowerCase()}`}
        />
      )}
      <button type="button" className="button" onClick={() => onOpen(side, heading)}>
        Open overlay
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
            setLoadError("The precomputed comparison is still warming up. Reload in a moment, or analyze an image now.");
          }
          return;
        }
        setComputing(false);
        setComparison(result);
      } catch {
        if (!cancelled) {
          setComputing(false);
          setLoadError("The precomputed comparison could not be loaded. You can still analyze your own image.");
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
      <h1>CovertLens</h1>
      <p className="lede">
        <span>CovertLens checks images that AI agents send each other for hidden messages.</span>
        <span>It scores the original bytes across four channel families: spatial LSB, JPEG DCT, metadata, and geometry.</span>
        <span>Every score is evidence with coverage and limits attached — never an accusation on its own.</span>
        <span>A verdict ladder decides delivery before any recipient sees the image.</span>
        <span>Try the skyline test below: one skyline is innocent, the other carries a pattern in its building heights.</span>
      </p>
      <p>
        <button type="button" className="button button-primary" onClick={() => navigate("/analyze")}>
          Try your own
        </button>{" "}
        <a href="/docs">Browse the API instead</a>
      </p>

      <section aria-labelledby="skyline-heading">
        <h2 id="skyline-heading">Two skylines, one hidden pattern</h2>
        <p>
          Both images were scored before this page loaded. Open either
          overlay to see the measured boxes, the height sequence snapped to
          its discovered grid, and the statistics behind the badge.
        </p>
        {computing && !comparison && (
          <p role="status">Preparing the precomputed comparison…</p>
        )}
        {loadError && <p className="alert" role="alert">{loadError}</p>}
        {comparison && (
          <div className="card-grid card-grid-2">
            <SkylineSide heading="Clean control" side={comparison.clean} onOpen={openOverlay} />
            <SkylineSide heading="Encoded example" side={comparison.encoded} onOpen={openOverlay} />
          </div>
        )}
      </section>

      <section aria-labelledby="reading-heading">
        <h2 id="reading-heading">How to read the result</h2>
        <ul>
          <li>Heights that fall exactly on a regular grid are <em>quantized</em>. That alone is not encoding — charts do it by design.</li>
          <li>The Rayleigh periodogram shows how strongly one step explains the sequence; the null says how often shuffled data would match it.</li>
          <li>Structure is only claimed under a declared code that beats its shuffle null. This site never displays decoded text.</li>
        </ul>
      </section>
    </>
  );
}
