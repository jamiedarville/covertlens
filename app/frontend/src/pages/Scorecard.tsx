import { useEffect, useState } from "react";
import { ExactData } from "./Benchmarks";
import { humanizeKey, releaseHeadline, releaseLight, targetLabel } from "../format";
import { TechnicalBreakdown } from "../components/Help";
import { LightDot } from "../components/TrafficLight";

export type Card = {
  release: string;
  frozen_config_version: string;
  targets?: Record<string, boolean>;
  decision: {
    value: string;
    rationale: string[];
    limitations: string[];
    target_revisions: { target: string; revision: string; reason: string }[];
  };
  sections: Record<string, unknown>;
};

// The plain answer: the decision as a colour, then which targets were
// met and which were not, in plain words.
export function ReleaseSummary({ card }: { card: Card }) {
  const light = releaseLight(card.decision.value);
  const targets = Object.entries(card.targets ?? {});
  const met = targets.filter(([, ok]) => ok).map(([name]) => name);
  const missed = targets.filter(([, ok]) => !ok).map(([name]) => name);
  const limits = card.decision.limitations.length;
  return (
    <>
      <section
        className={`verdict verdict-${light}`}
        aria-labelledby="release-heading"
        data-testid="release-decision"
        data-light={light}
      >
        <span className="light-dot light-dot-large" aria-hidden="true">
          <LightDot light={light} />
        </span>
        <div className="verdict-text">
          <p className="verdict-question">Is this version ready to use?</p>
          <h2 id="release-heading" className="verdict-headline">
            {releaseHeadline(card.decision.value)}
          </h2>
          <p className="verdict-body">
            {met.length} of {targets.length} targets met.
          </p>
          {limits > 0 && (
            <p className="verdict-next">
              The project also lists {limits} known limitation{limits === 1 ? "" : "s"} in
              its own words. Read them in the technical breakdown before
              relying on this version.
            </p>
          )}
        </div>
      </section>
      <div className="card-grid card-grid-2">
        <section className="card" aria-labelledby="targets-met-heading">
          <h2 id="targets-met-heading">What it does well</h2>
          {met.length === 0 ? (
            <p className="note">No targets were met.</p>
          ) : (
            <ul className="check-list">
              {met.map((name) => (
                <li key={name}>
                  <LightDot light="green" />
                  <span title={name}>{targetLabel(name)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="card" aria-labelledby="targets-missed-heading">
          <h2 id="targets-missed-heading">What it doesn’t do yet</h2>
          <p className="note">Targets that were missed, or deliberately narrowed.</p>
          {missed.length === 0 ? (
            <p className="note">None: every target was met.</p>
          ) : (
            <ul className="check-list">
              {missed.map((name) => (
                <li key={name}>
                  <LightDot light="red" />
                  <span title={name}>{targetLabel(name)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}

export default function Scorecard() {
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const c = new AbortController();
    fetch("/api/scorecard", { signal: c.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Scorecard unavailable (${r.status})`);
        setCard((await r.json()) as Card);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(String(e));
      });
    return () => c.abort();
  }, []);
  const intro = (
    <>
      <h1>Release decision</h1>
      <p className="lede">
        Before a version of CovertLens is released, the project checks it
        against a list of targets. Here’s the decision for this version,
        and which targets it met.
      </p>
    </>
  );
  if (!card)
    return (
      <>
        {intro}
        <p role="status">
          {error
            ? "The release decision couldn’t be loaded. What to do: reload this page to try again."
            : "Loading the release decision…"}
        </p>
      </>
    );
  return (
    <>
      {intro}
      <ReleaseSummary card={card} />
      <TechnicalBreakdown
        id="scorecard-breakdown"
        note="the project’s reasons, its known limitations in its own words, changed targets and the raw evidence"
      >
        <p>
          Release: {card.release} · measured with locked settings version{" "}
          {card.frozen_config_version}.
        </p>
        <h2>Decision (exact value)</h2>
        <p>{card.decision.value}</p>
        <table>
          <caption>The targets set for this release, by their exact names.</caption>
          <thead>
            <tr>
              <th>Target</th>
              <th>Was it met?</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(card.targets ?? {}).map(([name, met]) => (
              <tr key={name}>
                <th title={name}>{humanizeKey(name)} ({name})</th>
                <td>{met ? "Yes, within what was measured" : "No: missed, or the aim was narrowed"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h2>Why this decision? (in the project’s own words)</h2>
        <ul>
          {card.decision.rationale.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
        <h2>Known limitations (in the project’s own words)</h2>
        <p className="note">
          These are the weaknesses this version knowingly ships with. They
          limit every claim made elsewhere in this app.
        </p>
        <ul>
          {card.decision.limitations.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
        <h2>Targets that were changed, and why</h2>
        {card.decision.target_revisions.length === 0 ? (
          <p className="note">No targets were changed for this release.</p>
        ) : (
          card.decision.target_revisions.map((row) => (
            <article className="panel" key={row.target}>
              <h3 title={row.target}>{humanizeKey(row.target)}</h3>
              <p>
                <strong>Changed to:</strong> {row.revision}
              </p>
              <p>
                <strong>Why:</strong> {row.reason}
              </p>
            </article>
          ))
        )}
        <h2>The evidence behind this decision</h2>
        <p className="note">
          Each item expands to the exact recorded numbers. The accuracy page
          tells the same story with explanations.
        </p>
        {Object.entries(card.sections).map(([name, section]) => (
          <article key={name}>
            <h3 title={name}>{humanizeKey(name)}</h3>
            <ExactData value={section} />
          </article>
        ))}
        <p>
          <a href="/api/scorecard" download="covertlens-scorecard.json">
            Download this release decision as a data file (JSON)
          </a>
        </p>
      </TechnicalBreakdown>
    </>
  );
}
