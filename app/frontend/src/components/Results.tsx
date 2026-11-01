// Family score cards, ladder decision and evidence tables.
// All values render straight from the /api/analyze response.

import type { AnalyzePayload, Decision, Finding } from "../types";
import { FAMILY_BLURBS, FAMILY_LABELS, fmtExact, fmtScore } from "../format";
import { ScoreBar } from "./Charts";

const FAMILY_ORDER = ["spatial_lsb", "jpeg_dct", "metadata", "geometric"];

function scalarEntries(record: Record<string, unknown>): [string, unknown][] {
  return Object.entries(record).filter(
    ([, v]) => v === null || ["string", "number", "boolean"].includes(typeof v),
  );
}

function FamilyCard({
  family,
  finding,
  verdict,
}: {
  family: string;
  finding: Finding | undefined;
  verdict: string | undefined;
}) {
  const label = FAMILY_LABELS[family] ?? family;
  return (
    <article className="card family-card" aria-label={`${label} family`}>
      <div className="card-head">
        <h3>{label}</h3>
        {verdict && <span className="chip">ladder: {verdict}</span>}
      </div>
      <p className="note">{FAMILY_BLURBS[family] ?? ""}</p>
      {finding ? (
        <>
          <p className="score-line">
            <span className="score-value" title={String(finding.score)}>
              {fmtScore(finding.score)}
            </span>
            <span className="score-scale"> / 1 evidence score</span>
          </p>
          <ScoreBar score={finding.score} />
          <dl className="kv">
            <div>
              <dt>Detector</dt>
              <dd>
                {finding.detector_name} {finding.detector_version}
              </dd>
            </div>
            <div>
              <dt>Config</dt>
              <dd>{fmtExact(
                finding.coverage.config_version ?? finding.evidence.detector_config_version,
              )}</dd>
            </div>
            {scalarEntries(finding.coverage)
              .filter(([k]) => k !== "config_version")
              .map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{fmtExact(v)}</dd>
                </div>
              ))}
          </dl>
          <h4>Limitations</h4>
          <ul className="tight">
            {finding.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : (
        <p className="not-applicable">
          No finding returned for this family on this input. It is listed so
          the four-family picture is always complete.
        </p>
      )}
    </article>
  );
}

export function FamilyCards({ payload }: { payload: AnalyzePayload }) {
  const findings = payload.analysis?.findings ?? [];
  const perFamily = new Map(
    (payload.decision?.per_family ?? []).map((p) => [p.family, p.verdict]),
  );
  return (
    <section aria-labelledby="families-heading">
      <h2 id="families-heading">Four channel families</h2>
      <p>
        Each family is scored on the original bytes and reported on its own.
        Scores are evidence, never blended into one number.
      </p>
      <div className="card-grid">
        {FAMILY_ORDER.map((family) => (
          <FamilyCard
            key={family}
            family={family}
            finding={findings.find((f) => f.family === family)}
            verdict={perFamily.get(family)}
          />
        ))}
      </div>
    </section>
  );
}

export function DecisionPanel({ decision }: { decision: Decision }) {
  return (
    <section className="card decision" aria-labelledby="decision-heading">
      <div className="card-head">
        <h2 id="decision-heading">Verdict ladder decision</h2>
        <span className="badge badge-verdict">{decision.verdict}</span>
      </div>
      <dl className="kv kv-wide">
        <div><dt>Delivery</dt><dd>{decision.delivery}</dd></div>
        <div><dt>Halts execution</dt><dd>{decision.halt_execution ? "yes" : "no"}</dd></div>
        <div><dt>Enforceable</dt><dd>{decision.enforceable ? "yes" : "no"}</dd></div>
        <div>
          <dt>Equated with collusion</dt>
          <dd>{decision.equated_with_collusion ? "yes" : "no — evidence only"}</dd>
        </div>
        <div><dt>Threshold config</dt><dd>{decision.config_version}</dd></div>
        <div><dt>Ladder version</dt><dd>{decision.ladder_version}</dd></div>
        <div><dt>Findings</dt><dd>{decision.findings_count}</dd></div>
        <div>
          <dt>Families without findings</dt>
          <dd>{decision.families_without_findings.join(", ") || "—"}</dd>
        </div>
      </dl>
      <div className="table-wrap">
        <table>
          <caption>Per-family ladder inputs, exactly as returned</caption>
          <thead>
            <tr>
              <th scope="col">Family</th>
              <th scope="col">Max score</th>
              <th scope="col">Thresholds</th>
              <th scope="col">Triage flag at</th>
              <th scope="col">Quarantine at</th>
              <th scope="col">Fail run at</th>
              <th scope="col">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {decision.per_family.map((row) => (
              <tr key={row.family}>
                <th scope="row">{FAMILY_LABELS[row.family] ?? row.family}</th>
                <td className="num">{String(row.max_score)}</td>
                <td>{row.thresholds_status}</td>
                <td className="num">{fmtExact(row.triage_flag_at)}</td>
                <td className="num">{fmtExact(row.enforcement_quarantine_at)}</td>
                <td className="num">{fmtExact(row.enforcement_fail_run_at)}</td>
                <td>{row.verdict}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EvidenceValue({ value }: { value: unknown }) {
  if (value !== null && typeof value === "object") {
    return <span className="mono-small">{JSON.stringify(value)}</span>;
  }
  return <>{fmtExact(value)}</>;
}

export function EvidenceTables({ payload }: { payload: AnalyzePayload }) {
  const findings = payload.analysis?.findings ?? [];
  if (findings.length === 0) return null;
  return (
    <section aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">Evidence tables</h2>
      <p>
        Detector evidence exactly as returned. Geometric channel detail has
        its own table in the overlay below; nothing here is a decoded message.
      </p>
      {findings.map((finding) => (
        <div className="table-wrap" key={finding.family}>
          <table>
            <caption>
              {FAMILY_LABELS[finding.family] ?? finding.family} —{" "}
              {finding.detector_name} {finding.detector_version}, score{" "}
              {String(finding.score)}
            </caption>
            <thead>
              <tr>
                <th scope="col">Evidence field</th>
                <th scope="col">Value</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(finding.evidence).map(([key, value]) => (
                <tr key={key}>
                  <th scope="row">{key}</th>
                  <td>
                    {key === "channels" ? (
                      "See the channel table in the geometric overlay."
                    ) : (
                      <EvidenceValue value={value} />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  );
}
