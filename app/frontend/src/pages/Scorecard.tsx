import { useEffect, useState } from "react";
import { ExactData } from "./Benchmarks";
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
        <h1>Release scorecard</h1>
        <p role="status">{error || "Loading published scorecard…"}</p>
      </>
    );
  return (
    <>
      <h1>Release scorecard</h1>
      <p>
        {card.release} · {card.frozen_config_version}
      </p>
      <h2>{card.decision.value.replaceAll("_", " ")}</h2>
      <table>
        <caption>Targets at the recorded configuration</caption>
        <thead>
          <tr>
            <th>Target</th>
            <th>Assessment</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(card.targets ?? {}).map(([name, met]) => (
            <tr key={name}>
              <th>{name.replaceAll("_", " ")}</th>
              <td>
                {met ? "Met within measured scope" : "Missed or narrowed"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Decision rationale</h2>
      <ul>
        {card.decision.rationale.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
      <h2>Limitations</h2>
      <ul>
        {card.decision.limitations.map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
      <h2>Target revisions</h2>
      {card.decision.target_revisions.map((row) => (
        <article className="panel" key={row.target}>
          <h3>{row.target}</h3>
          <p>{row.revision}</p>
          <p>{row.reason}</p>
        </article>
      ))}
      <h2>Source evidence</h2>
      {Object.entries(card.sections).map(([name, section]) => (
        <article key={name}>
          <h3>{name.replaceAll("_", " ")}</h3>
          <ExactData value={section} />
        </article>
      ))}
      <p>
        <a href="/api/scorecard" download="covertlens-scorecard.json">
          Download exact scorecard JSON
        </a>
      </p>
    </>
  );
}
