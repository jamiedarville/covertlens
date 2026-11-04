// Trace explorer page (CL-60): one run joined end to end.
// Every delivery lists its content hash, verdict reference and
// parse/next-action linkage, with an explicit reason wherever a
// link is missing. Actions list candidate input artifacts; the
// view states causation_claimed: false and words every link as a
// candidate, never as a cause. Reading a trace needs a demo role
// with trace.read (researcher or reviewer, CL-78).

import { useState } from "react";
import type { TraceDelivery, TraceView } from "../types";
import { ApiError, fetchTraceRun } from "../api";
import { RoleControl } from "../components/RoleControl";
import { useDemoRole } from "../demoRole";
import { humanizeKey, verdictLabel } from "../format";
import { TechnicalBreakdown } from "../components/Help";
import { LightDot, VerdictLight } from "../components/TrafficLight";

// One plain sentence per image. Later actions are only ever possible
// links: the trace never claims causation.
export function whatHappened(d: TraceDelivery): string {
  if (!d.delivered) {
    switch (d.verdict?.verdict) {
      case "fail_run":
        return "Held back, and the session was stopped. The other agent never saw it.";
      case "quarantine":
        return "Held back. The other agent never saw it.";
      default:
        return "Not delivered: no decision to let it through is on record.";
    }
  }
  const opened =
    d.parse.linkage === "linked"
      ? "Delivered, and the other agent opened it."
      : "Delivered. There’s no record of the other agent opening it.";
  const n = d.next_actions.length;
  if (n === 0) return opened;
  return `${opened} Afterwards, the other agent took ${n} action${n === 1 ? "" : "s"} that came after this image. That’s only a possible link, not proof of a connection.`;
}

export function TimelineSummary({ view }: { view: TraceView }) {
  const total = view.deliveries.length;
  const delivered = view.deliveries.filter((d) => d.delivered).length;
  const held = total - delivered;
  const repeated = view.weak_signals.repeated_senders;
  return (
    <section aria-labelledby="trace-summary-heading">
      <h2 id="trace-summary-heading">What happened</h2>
      <p className="summary-line">
        <strong>{total}</strong> image{total === 1 ? "" : "s"} sent ·{" "}
        <strong>{delivered}</strong> delivered · <strong>{held}</strong> not delivered
      </p>
      <ol className="timeline">
        {view.deliveries.map((d, i) => (
          <li key={d.delivery_id} className="timeline-item">
            <p className="item-name" title={d.delivery_id}>
              Image {i + 1}: {d.sender_id ?? "unknown sender"} → {d.recipient_id ?? "unknown recipient"}
            </p>
            <p title={d.verdict?.verdict ?? undefined}>
              <VerdictLight
                verdict={d.verdict?.verdict}
                label={d.verdict?.verdict ? undefined : "No decision on record"}
              />
            </p>
            <p>{whatHappened(d)}</p>
          </li>
        ))}
      </ol>
      {repeated.length > 0 && (
        <p className="result-pill result-orange" data-light="orange">
          <LightDot light="orange" />
          <span>
            <strong>Worth a look:</strong> {repeated.join(", ")} kept sending
            images with small warning signs. That’s a hint where to look first,
            not proof of anything.
          </span>
        </p>
      )}
    </section>
  );
}

export default function Trace() {
  const [runId, setRunId] = useState("");
  const [view, setView] = useState<TraceView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState("");
  const [role, setRole] = useDemoRole();

  const onLoad = async () => {
    if (!runId.trim()) {
      setError("Type the session name first. It’s the name from the delivery gate page, for example run_live_demo.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await fetchTraceRun(runId.trim(), role);
      setView(next);
      setStatusLine(
        next.deliveries.length === 0
          ? "No images have been sent in this session yet, so there’s no timeline. Send one on the delivery gate page first."
          : `Timeline for session “${next.run_id}” is below.`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? `Not allowed as a ${role}: timelines need Researcher or Reviewer. What to do: change “Who are you in this demo?” and try again.`
          : err instanceof ApiError
            ? err.message
            : "The timeline couldn’t be loaded. What to do: check the session name and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const participants = view ? Object.values(view.context.participants) : [];
  const episodes = view ? Object.values(view.context.episodes) : [];

  return (
    <>
      <h1>Timeline of a session</h1>
      <p className="lede">
        See what happened in one session, step by step: which images were
        sent, what was decided, and whether the other agent saw them.
      </p>

      <section className="card step" aria-labelledby="trace-run-heading">
        <h2 id="trace-run-heading">Choose a session</h2>
        <RoleControl
          role={role}
          onChange={setRole}
          disabled={busy}
          hint="Pick Researcher or Reviewer: viewers can’t see timelines."
        />
        <div className="form-grid">
          <label>
            Session name
            <input
              type="text"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              placeholder="run_live_demo"
            />
            <span className="note">The name from the delivery gate page, for example run_live_demo.</span>
          </label>
        </div>
        <p>
          <button type="button" className="button button-primary" onClick={onLoad} disabled={busy}>
            Show the timeline
          </button>
        </p>
      </section>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && (
        <p className="alert" role="alert">{error}</p>
      )}

      {view && view.deliveries.length > 0 && <TimelineSummary view={view} />}

      {view && (
        <TechnicalBreakdown
          id="trace-breakdown"
          note="exact IDs, fingerprints, missing links, who took part and later actions"
        >
      {view && view.deliveries.length > 0 && (
        <section aria-labelledby="trace-deliveries-heading">
          <h2 id="trace-deliveries-heading">Pictures sent, and what happened to each</h2>
          <div className="table-wrap">
            <table>
              <caption>
                Every picture sent in session {view.run_id}. Read across:
                who sent it to whom, its file fingerprint, the decision
                taken, whether the recipient opened it, and what happened
                next. Anything missing is listed with its reason in the
                last column.
              </caption>
              <thead>
                <tr>
                  <th>Picture (short ID, sender → recipient)</th>
                  <th>File fingerprint</th>
                  <th>Decision on record?</th>
                  <th>Did the recipient open it?</th>
                  <th>Recipient actions afterwards</th>
                  <th>What is missing, and why</th>
                </tr>
              </thead>
              <tbody>
                {view.deliveries.map((d) => (
                  <tr key={d.delivery_id}>
                    <td className="num">
                      {d.delivery_id.slice(0, 18)}…
                      <br />
                      <span className="mono-small">
                        {d.sender_id ?? "—"} → {d.recipient_id ?? "—"}
                        {d.episode_id ? ` · ${d.episode_id}` : ""}
                      </span>
                    </td>
                    <td className="num">{d.content_hash.slice(0, 24)}…</td>
                    <td>
                      {d.verdict_reference_status === "linked" ? (
                        <>
                          yes — {d.verdict?.verdict ? verdictLabel(d.verdict.verdict).toLowerCase() : "recorded"}
                          <br />
                          <span className="mono-small">
                            {d.verdict?.verdict ?? "—"} · {(d.verdict?.verdict_id ?? "").slice(0, 18)}…
                          </span>
                        </>
                      ) : (
                        "no decision on record"
                      )}
                    </td>
                    <td>
                      {d.parse.linkage === "linked"
                        ? `recorded (${humanizeKey(String(d.parse.parse_status)).toLowerCase()})`
                        : `not recorded (${humanizeKey(String(d.parse.parse_status)).toLowerCase()}) — for held-back pictures this is expected: they were never seen`}
                    </td>
                    <td>
                      {d.next_actions.length > 0
                        ? `${d.next_actions.length} later action(s) could have seen this picture`
                        : "none recorded"}
                    </td>
                    <td>
                      {d.missing_reasons.length === 0 ? (
                        "nothing missing"
                      ) : (
                        <ul className="tight">
                          {d.missing_reasons.map((r) => (
                            <li key={r.link}>
                              <strong>{r.link}:</strong> {r.reason}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {view.linkage_errors.length > 0 && (
            <p className="note">
              Notes about records that could not be joined together:{" "}
              {view.linkage_errors.join("; ")}
            </p>
          )}
        </section>
      )}

      {view && (
        <div className="card-grid card-grid-2">
          <section className="card" aria-labelledby="trace-context-heading">
            <h2 id="trace-context-heading">Who took part, grouped by episode</h2>
            <p className="note">An “episode” is an optional label used to group a few deliveries inside the session.</p>
            <h3>Agents in this session</h3>
            {participants.length === 0 ? (
              <p className="note">No agents have been recorded in this session yet.</p>
            ) : (
              <ul className="tight">
                {participants.map((p) => (
                  <li key={p.agent_id}>
                    <strong>{p.agent_id}</strong> — sent {p.sent.length} picture(s),
                    received {p.received.length}, and took {p.actions.length} later action(s)
                  </li>
                ))}
              </ul>
            )}
            <h3>Episodes</h3>
            {episodes.length === 0 ? (
              <p className="note">No episode labels were used in this session. That is normal if the sender left the episode box empty.</p>
            ) : (
              <ul className="tight">
                {episodes.map((e) => (
                  <li key={e.episode_id ?? "(none)"}>
                    <strong>{e.episode_id ?? "(none)"}</strong> —{" "}
                    {e.deliveries.length} deliver
                    {e.deliveries.length === 1 ? "y" : "ies"},{" "}
                    {e.actions.length} action(s)
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="card" aria-labelledby="trace-weak-heading">
            <h2 id="trace-weak-heading">Small signals that keep repeating</h2>
            <p className="note">
              One small score means little on its own. But if the same
              sender keeps producing small-but-not-zero scores, that is
              worth a person’s attention. This table counts, per sender,
              pictures whose strongest check score was small (above 0 but
              below {view.weak_signals.band.max_exclusive}). Two or more is
              marked “repeated”. This is only a hint where to look first —
              it is not a decision and not proof of anything.
            </p>
            {view.weak_signals.per_sender.length === 0 ? (
              <p className="note">No sender activity has been recorded in this session yet.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <caption>Small-signal counts per sender in this session. Scores run from 0 to 1.</caption>
                  <thead>
                    <tr>
                      <th>Sender</th>
                      <th>Pictures sent</th>
                      <th>With a small signal</th>
                      <th>Repeated?</th>
                      <th>Strongest score seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.weak_signals.per_sender.map((r) => (
                      <tr key={r.sender_id}>
                        <td>{r.sender_id}</td>
                        <td>{r.deliveries}</td>
                        <td>{r.weak_signals}</td>
                        <td>{r.repeated_weak ? "yes — worth a closer look" : "no"}</td>
                        <td>{r.max_score.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {view && (
        <section aria-labelledby="trace-actions-heading">
          <h2 id="trace-actions-heading">What recipients did afterwards</h2>
          <p className="note">
            {view.causation_note}. In plain English: for every action
            below, the listed pictures are only ones the recipient{" "}
            <em>could have seen beforehand</em>. This page never claims a
            picture caused an action.
          </p>
          {view.actions.length === 0 ? (
            <p className="note">
              No recipient actions have been recorded in this session, so
              there is nothing to link pictures to. In the table above,
              delivered pictures list this as missing, with the reason.
            </p>
          ) : (
            <div className="table-wrap">
              <table>
                <caption>
                  Each action a recipient took, with the pictures they could
                  have seen before it. “Could have seen” is not the same as
                  “acted on it”.
                </caption>
                <thead>
                  <tr>
                    <th>Action (in order)</th>
                    <th>Who acted</th>
                    <th>Pictures they could have seen before it</th>
                    <th>Do we claim the picture caused it?</th>
                  </tr>
                </thead>
                <tbody>
                  {view.actions.map((a) => (
                    <tr key={a.event_id}>
                      <td className="num">
                        #{a.seq} {a.event_id.slice(0, 18)}…
                      </td>
                      <td>{a.recipient_id ?? "—"}</td>
                      <td>
                        {a.candidate_count === 0
                          ? "none — no picture had been delivered to them before this"
                          : a.candidate_delivery_ids
                              .map((id) => `${id.slice(0, 18)}…`)
                              .join(", ")}
                      </td>
                      <td>{a.causation_claimed ? "yes" : "No — at most a possible link"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
        </TechnicalBreakdown>
      )}
    </>
  );
}
