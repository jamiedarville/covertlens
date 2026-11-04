import { useEffect, useState } from "react";
import type { Comparison, ComparisonSide } from "../types";
import { fetchComparison, fixtureImageUrl, storePreload } from "../api";
import { LIGHT_HEADLINE, LIGHT_NAME } from "../format";
import { ColourKey, LightDot, overallLight } from "../components/TrafficLight";

function SkylineSide({
  heading,
  side,
  onOpen,
}: {
  heading: string;
  side: ComparisonSide;
  onOpen: (side: ComparisonSide, heading: string) => void;
}) {
  const light = overallLight(side.payload);
  return (
    <article className="card skyline" aria-label={heading}>
      <h3>{heading}</h3>
      <img
        className="skyline-img"
        src={fixtureImageUrl(side.content_hash)}
        alt={`${heading}: a row of city-skyline buildings`}
        loading="lazy"
      />
      <p className={`result-pill result-${light}`} data-light={light}>
        <LightDot light={light} />
        <strong>
          {LIGHT_NAME[light]}: {LIGHT_HEADLINE[light]}
        </strong>
      </p>
      <button type="button" className="button" onClick={() => onOpen(side, heading)}>
        See the full result
      </button>
    </article>
  );
}

// Every other page, described in one plain sentence each, so nothing
// in the menu is a mystery.
const OTHER_PAGES: [string, string, string][] = [
  ["/demo", "Two-agent demo", "Watch a sender hide two words in a picture, check it, then see what a receiver can read."],
  ["/generate", "Make a test image", "create an image with a hidden message in it, to see whether CovertLens catches it."],
  ["/gate", "Delivery gate", "watch images being checked as one AI agent sends them to another, and decide which ones get through."],
  ["/review", "Review images", "look at the images that were stopped, and record what you think of each one."],
  ["/trace", "Timeline", "see everything that happened in one session, step by step."],
  ["/benchmarks", "Accuracy", "how often the tests catch hidden messages, and how often they raise a false alarm."],
  ["/leaderboard", "Leaderboard", "which ways of hiding a message got the most past the tests."],
  ["/scorecard", "Release decision", "whether this version of CovertLens meets its accuracy and speed targets, and the evidence."],
];

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
            setLoadError("The example below is taking longer than usual to get ready. What to do: reload this page in a moment, or skip it and check your own image now.");
          }
          return;
        }
        setComputing(false);
        setComparison(result);
      } catch {
        if (!cancelled) {
          setComputing(false);
          setLoadError("The example below couldn’t be loaded. You can still check your own image with the button above.");
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
      label: heading,
    });
    navigate("/analyze");
  };

  const link = (to: string) => (e: React.MouseEvent) => {
    e.preventDefault();
    navigate(to);
  };

  return (
    <>
      <h1>Is an image hiding a secret message?</h1>
      <p className="lede">
        AI agents sometimes send each other images. CovertLens checks those
        images for hidden messages, a sign that the agents may be secretly
        working together. This is called <strong>collusion</strong>.
      </p>
      <p>
        <button
          type="button"
          className="button button-primary button-large"
          onClick={() => navigate("/analyze")}
        >
          Check an image
        </button>
      </p>

      <section aria-labelledby="how-heading">
        <h2 id="how-heading">How it works</h2>
        <ol className="how-steps">
          <li>
            <strong>Add an image.</strong> Any PNG or JPEG picture.
          </li>
          <li>
            <strong>We run four tests on it.</strong> Each test looks for a
            message hidden in a different part of the image.
          </li>
          <li>
            <strong>You get a simple answer:</strong> green, orange or red,
            explained in plain words. If you want the detail behind it, one
            click shows the technical evidence.
          </li>
        </ol>
        <ColourKey />
      </section>

      <section aria-labelledby="skyline-heading">
        <h2 id="skyline-heading">See it in action</h2>
        <p>
          These two city skylines look almost the same. One is ordinary. The
          other has a secret message hidden in the heights of its
          buildings. Under each one is the answer CovertLens gave.
        </p>
        {computing && !comparison && (
          <p role="status">Getting the example ready… this usually takes a few seconds after the server starts.</p>
        )}
        {loadError && <p className="alert" role="alert">{loadError}</p>}
        {comparison && (
          <div className="card-grid card-grid-2">
            <SkylineSide heading="Ordinary skyline" side={comparison.clean} onOpen={openOverlay} />
            <SkylineSide heading="Skyline with a hidden message" side={comparison.encoded} onOpen={openOverlay} />
          </div>
        )}
      </section>

      <section aria-labelledby="more-heading">
        <h2 id="more-heading">Everything else you can do</h2>
        <p>Each of these is also in the menu at the top of every page.</p>
        <ul className="page-list">
          {OTHER_PAGES.map(([to, name, what]) => (
            <li key={to}>
              <a href={to} onClick={link(to)}>
                {name}
              </a>{" "}
              — {what}
            </li>
          ))}
          <li>
            <a href="/docs">API docs</a> — for programmers who want to connect
            their own software to CovertLens.
          </li>
        </ul>
      </section>
    </>
  );
}
