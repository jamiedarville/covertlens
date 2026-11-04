// Family score cards, ladder decision and evidence tables.
// All values render straight from the /api/analyze response.
// Plain-English wording first (CL-79); exact field names and
// settings versions stay available under "technical details".

import type { AnalyzePayload, Decision, Finding } from "../types";
import {
  FAMILY_BLURBS,
  FAMILY_LABELS,
  fmtExact,
  fmtScore,
  humanizeKey,
  scoreMeaning,
  verdictLabel,
  verdictMeaning,
} from "../format";
import { ScoreBar } from "./Charts";
import { TechDetails } from "./Help";

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
    <article className="card family-card" aria-label={`${label} check`}>
      <div className="card-head">
        <h3>{label}</h3>
        {verdict && (
          <span className="chip" title={`verdict: ${verdict}`}>
            decision: {verdictLabel(verdict).toLowerCase()}
          </span>
        )}
      </div>
      <p className="note">{FAMILY_BLURBS[family] ?? ""}</p>
      {finding ? (
        <>
          <p className="score-line">
            <span className="score-value" title={String(finding.score)}>
              {fmtScore(finding.score)}
            </span>
            <span className="score-scale"> out of 1 — higher means stronger evidence of this kind of hiding</span>
          </p>
          <ScoreBar score={finding.score} />
          <p className="note">{scoreMeaning(finding.score)}</p>
          <h4>What was checked</h4>
          <dl className="kv">
            {scalarEntries(finding.coverage)
              .filter(([k]) => k !== "config_version")
              .map(([k, v]) => (
                <div key={k}>
                  <dt title={k}>{humanizeKey(k)}</dt>
                  <dd>{fmtExact(v)}</dd>
                </div>
              ))}
          </dl>
          <h4>What this check cannot tell you</h4>
          <ul className="tight">
            {finding.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <TechDetails>
            <dl className="kv">
              <div>
                <dt>Detector (the software that ran this check)</dt>
                <dd>
                  {finding.detector_name} {finding.detector_version}
                </dd>
              </div>
              <div>
                <dt>Settings version (config)</dt>
                <dd>{fmtExact(
                  finding.coverage.config_version ?? finding.evidence.detector_config_version,
                )}</dd>
              </div>
            </dl>
          </TechDetails>
        </>
      ) : (
        <p className="not-applicable">
          <strong>Not checked for this file.</strong> This check returned no
          result here — for example, some checks only apply to certain file
          types. “Not checked” is different from “checked and all clear”, so
          all four checks are always listed to make that difference visible.
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
      <h2 id="families-heading">What each of the four checks found</h2>
      <p>
        CovertLens looks for hidden information in four different places.
        Each check is reported separately — the scores are never blended
        into one number, because a strong signal in one place should not
        be hidden by weak signals elsewhere.
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
  const heldBack = decision.delivery !== "permit";
  return (
    <section className="card decision" aria-labelledby="decision-heading">
      <div className="card-head">
        <h2 id="decision-heading">Would this image be delivered?</h2>
        <span className="badge badge-verdict" title={`verdict: ${decision.verdict}`}>
          {verdictLabel(decision.verdict)}
        </span>
      </div>
      <p>
        <strong>
          {heldBack
            ? "No — this image would be held back and the recipient would not see it."
            : "Yes — this image would be delivered to the recipient."}
        </strong>{" "}
        {verdictMeaning(decision.verdict)}
      </p>
      <p className="note">
        How the decision is made: each check’s score is compared with
        cut-off points set in advance (the “verdict ladder”). The most
        serious result across the four checks decides the outcome for the
        whole image.
      </p>
      <dl className="kv kv-wide">
        <div><dt>Delivered to the recipient?</dt><dd>{heldBack ? "No — held back" : "Yes"}</dd></div>
        <div>
          <dt>Would the whole run (experiment session) be stopped?</dt>
          <dd>{decision.halt_execution ? "Yes" : "No"}</dd>
        </div>
        <div>
          <dt>Can this decision actually be enforced at these settings?</dt>
          <dd>{decision.enforceable ? "Yes" : "No — treat it as advice for a person, not an automatic block"}</dd>
        </div>
        <div>
          <dt>Does this prove the sender was secretly communicating?</dt>
          <dd>{decision.equated_with_collusion ? "Yes" : "No — a score is evidence only, never proof on its own"}</dd>
        </div>
        <div>
          <dt>Individual check results behind this decision</dt>
          <dd>{decision.findings_count}</dd>
        </div>
        <div>
          <dt>Checks with no result for this file (not the same as “all clear”)</dt>
          <dd>
            {decision.families_without_findings
              .map((f) => FAMILY_LABELS[f] ?? f)
              .join(", ") || "none — all four checks returned a result"}
          </dd>
        </div>
      </dl>
      <div className="table-wrap">
        <table>
          <caption>
            Each check’s highest score, next to the cut-offs. “Flag” means
            delivered but marked for attention; “hold back” means the
            recipient does not get the image; “stop the run” also ends the
            experiment session.
          </caption>
          <thead>
            <tr>
              <th scope="col">Check</th>
              <th scope="col">Highest score (0 to 1)</th>
              <th scope="col">Are the cut-offs settled (frozen)?</th>
              <th scope="col">Flag for attention at</th>
              <th scope="col">Hold back at</th>
              <th scope="col">Stop the run at</th>
              <th scope="col">Decision for this check</th>
            </tr>
          </thead>
          <tbody>
            {decision.per_family.map((row) => (
              <tr key={row.family}>
                <th scope="row">{FAMILY_LABELS[row.family] ?? row.family}</th>
                <td className="num">{String(row.max_score)}</td>
                <td title={row.thresholds_status}>
                  {row.thresholds_status === "frozen"
                    ? "Yes — locked in advance"
                    : row.thresholds_status.includes("unfrozen")
                      ? "No — provisional, not yet settled"
                      : row.thresholds_status}
                </td>
                <td className="num">{fmtExact(row.triage_flag_at)}</td>
                <td className="num">{fmtExact(row.enforcement_quarantine_at)}</td>
                <td className="num">{fmtExact(row.enforcement_fail_run_at)}</td>
                <td title={`verdict: ${row.verdict}`}>{verdictLabel(row.verdict)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="note">
        What to do next: if the image was held back, a reviewer can open
        the original on the “Review held-back images” page. If it was let
        through with a flag, it is worth a closer look on the timeline
        page. A dash (—) means that cut-off is not set, so that outcome
        cannot be triggered by this check.
      </p>
      <TechDetails>
        <dl className="kv kv-wide">
          <div><dt>Verdict (exact value)</dt><dd>{decision.verdict}</dd></div>
          <div><dt>Delivery (exact value)</dt><dd>{decision.delivery}</dd></div>
          <div><dt>Threshold settings version</dt><dd>{decision.config_version}</dd></div>
          <div><dt>Verdict ladder version</dt><dd>{decision.ladder_version}</dd></div>
        </dl>
      </TechDetails>
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
      <h2 id="evidence-heading">Detailed measurements (for specialists)</h2>
      <p>
        The exact numbers behind the cards above, exactly as the checker
        returned them. You do not need this section to understand the
        result. Field names are written out in plain English; hover or
        inspect a row for the exact name used by the API. None of this is
        a decoded hidden message — no hidden text is shown on this page.
      </p>
      {findings.map((finding) => (
        <div className="table-wrap" key={finding.family}>
          <table>
            <caption>
              {FAMILY_LABELS[finding.family] ?? finding.family} — checked by{" "}
              {finding.detector_name} {finding.detector_version}, score{" "}
              {String(finding.score)} out of 1
            </caption>
            <thead>
              <tr>
                <th scope="col">Measurement</th>
                <th scope="col">Value</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(finding.evidence).map(([key, value]) => (
                <tr key={key}>
                  <th scope="row" title={key}>{humanizeKey(key)}</th>
                  <td>
                    {key === "channels" ? (
                      "See the per-pattern table in the picture measurements section above."
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
