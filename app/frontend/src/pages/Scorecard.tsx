import { useEffect, useState } from "react";
import { ExactData } from "./Benchmarks";
import { humanizeKey } from "../format";
type Card = {
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

function decisionLabel(value: string): string {
  switch (value) {
    case "release_with_limitations":
      return "Release it, with the known limitations listed below stated openly";
    case "release":
      return "Release it";
    case "do_not_release":
      return "Do not release it yet";
    default:
      return value.replaceAll("_", " ");
  }
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
  if (!card)
    return (
      <>
        <h1>Should this version be released?</h1>
        <p>
          This page gives the project’s own release decision for the
          current version, the targets it aimed for, and — just as
          important — the known limitations it is released with.
        </p>
        <p role="status">
          {error
            ? "The release decision could not be loaded. What to do: reload this page to try again."
            : "Loading the published release decision…"}
        </p>
      </>
    );
  return (
    <>
      <h1>Should this version be released? (release scorecard)</h1>
      <p>
        This is the project’s own, published judgement about the current
        version: what it aimed for, whether it got there, and the
        shortcomings it is honest about. Read the decision first, then
        the limitations — they matter more than the ticks.
      </p>
      <p>
        Release: {card.release} · measured with locked settings version{" "}
        {card.frozen_config_version} (the “frozen” settings explained on
        the accuracy page).
      </p>
      <h2>Decision: {decisionLabel(card.decision.value)}</h2>
      <table>
        <caption>
          The targets set for this release, and whether each was met
          within what was actually measured. “Missed or narrowed” means
          the aim was not reached, or was deliberately reduced — see
          “Targets that were changed” below.
        </caption>
        <thead>
          <tr>
            <th>Target</th>
            <th>Was it met?</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(card.targets ?? {}).map(([name, met]) => (
            <tr key={name}>
              <th title={name}>{humanizeKey(name)}</th>
              <td>
                {met ? "Yes — within what was measured" : "No — missed, or the aim was narrowed"}
              </td>
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
      <h2>Known limitations — read these before relying on it</h2>
      <p className="note">
        These are the weaknesses this version knowingly ships with. They
        are written by the project, in its own words, and they bound
        every claim made elsewhere in this interface.
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
        Each item below expands to the exact recorded numbers for
        specialists. The “How accurate is it?” page presents the same
        story with explanations.
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
    </>
  );
}
