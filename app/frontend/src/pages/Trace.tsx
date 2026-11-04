// Trace explorer page (CL-60): one run joined end to end.
// Every delivery lists its content hash, verdict reference and
// parse/next-action linkage, with an explicit reason wherever a
// link is missing. Actions list candidate input artifacts; the
// view states causation_claimed: false and words every link as a
// candidate, never as a cause. Reading a trace needs a demo role
// with trace.read (researcher or reviewer, CL-78).

import { useState } from "react";
import type { TraceView } from "../types";
import { ApiError, fetchTraceRun } from "../api";
import { RoleControl } from "../components/RoleControl";
import { useDemoRole } from "../demoRole";
import { humanizeKey, verdictLabel } from "../format";

export default function Trace() {
  const [runId, setRunId] = useState("");
  const [view, setView] = useState<TraceView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState("");
  const [role, setRole] = useDemoRole();

  const onLoad = async () => {
    if (!runId.trim()) {
      setError("Type the session name first. It is the name you chose on the “Delivery gate (live)” page, for example run_live_demo. If you have not run the gate yet, do that first — this page only looks back at what already happened.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await fetchTraceRun(runId.trim(), role);
      setView(next);
      setStatusLine(
        next.deliveries.length === 0
          ? "No pictures have been sent in this session yet, so there is no timeline to show. Send one on the delivery gate page first."
          : `Timeline loaded: ${next.deliveries.length} picture${next.deliveries.length === 1 ? "" : "s"} sent in session “${next.run_id}”. Read the table from left to right: what was sent, what was decided, and whether the recipient ever saw it.`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? `Not allowed while pretending to be a ${role}: reading a session’s timeline needs researcher or reviewer. What to do: change the kind of user below and try again.`
          : err instanceof ApiError
            ? err.message
            : "The timeline could not be loaded. What to do: check the session name and try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  const participants = view ? Object.values(view.context.participants) : [];
  const episodes = view ? Object.values(view.context.episodes) : [];

  return (
    <>
      <h1>Timeline of what happened in one session</h1>
      <p>
        Use this page after running the delivery gate. It puts one whole
        session (a “run”) in order: each picture that was sent, the
        decision taken on it, whether the recipient ever opened it, and
        what the recipient did afterwards. It is the page to use when you
        ask “so what actually happened, step by step?”
      </p>
      <p className="note">
        When something expected is missing — for example, a held-back
        picture was never opened by the recipient — the table says so and
        gives the reason. Gaps are shown, never quietly hidden. One
        caution: where this page links a recipient’s later action to a
        picture, it only means the picture <em>could have been seen
        before</em> that action. It never claims the picture{" "}
        <em>caused</em> the action.
      </p>

      <section className="card" aria-labelledby="trace-run-heading">
        <h2 id="trace-run-heading">Which session do you want to look back at?</h2>
        <div className="form-grid">
          <label>
            Session name (run ID)
            <input
              type="text"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              placeholder="run_live_demo"
            />
            <span className="note">The exact name you used on the delivery gate page, for example run_live_demo. New here? Run the gate first, then come back with that name.</span>
          </label>
        </div>
        <RoleControl
          role={role}
          onChange={setRole}
          disabled={busy}
          hint="For this page: reading a timeline needs researcher or reviewer. As viewer you will be refused."
        />
        <p>
          <button type="button" className="button button-primary" onClick={onLoad} disabled={busy}>
            Show this session’s timeline
          </button>
        </p>
      </section>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && (
        <p className="alert" role="alert">{error}</p>
      )}

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
    </>
  );
}
