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
import { DemoRoleSelect } from "../components/DemoRoleSelect";
import { useDemoRole } from "../demoRole";

export default function Trace() {
  const [runId, setRunId] = useState("");
  const [view, setView] = useState<TraceView | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState("");
  const [role, setRole] = useDemoRole();

  const onLoad = async () => {
    if (!runId.trim()) {
      setError("Enter a run ID from the Live Gate.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await fetchTraceRun(runId.trim(), role);
      setView(next);
      setStatusLine(
        next.deliveries.length === 0
          ? "No deliveries recorded for this run yet."
          : `${next.deliveries.length} deliver${next.deliveries.length === 1 ? "y" : "ies"} joined for run ${next.run_id}.`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? `Reading a trace needs the researcher or reviewer demo role (acting as ${role}).`
          : err instanceof ApiError
            ? err.message
            : "Could not load the trace.",
      );
    } finally {
      setBusy(false);
    }
  };

  const participants = view ? Object.values(view.context.participants) : [];
  const episodes = view ? Object.values(view.context.episodes) : [];

  return (
    <>
      <h1>Trace explorer</h1>
      <p>
        Follow one run from artifact creation through delivery,
        verdict, parse and later actions. Missing links stay visible
        with their reason; nothing is dropped silently.
      </p>
      <p className="note">
        Action links list candidate inputs only. This page states
        causation_claimed: false — a candidate is an input visible
        to the recipient before an action, not a cause of it.
      </p>

      <section className="card" aria-labelledby="trace-run-heading">
        <h2 id="trace-run-heading">Run</h2>
        <div className="form-grid">
          <label>
            Run ID
            <input
              type="text"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              placeholder="run_live_demo"
            />
          </label>
        </div>
        <DemoRoleSelect
          role={role}
          onChange={setRole}
          disabled={busy}
          hint="Reading a trace needs researcher or reviewer."
        />
        <p>
          <button type="button" className="button button-primary" onClick={onLoad} disabled={busy}>
            Load trace
          </button>
        </p>
      </section>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && (
        <p className="alert" role="alert">{error}</p>
      )}

      {view && view.deliveries.length > 0 && (
        <section aria-labelledby="trace-deliveries-heading">
          <h2 id="trace-deliveries-heading">Deliveries</h2>
          <div className="table-wrap">
            <table>
              <caption>
                Every attempted delivery in run {view.run_id}, with its
                hash, verdict reference and parse/next-action linkage.
              </caption>
              <thead>
                <tr>
                  <th>Delivery</th>
                  <th>Content hash</th>
                  <th>Verdict reference</th>
                  <th>Parse</th>
                  <th>Next action</th>
                  <th>Missing links</th>
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
                          linked
                          <br />
                          <span className="mono-small">
                            {d.verdict?.verdict ?? "—"} · {(d.verdict?.verdict_id ?? "").slice(0, 18)}…
                          </span>
                        </>
                      ) : (
                        "missing"
                      )}
                    </td>
                    <td>
                      {d.parse.linkage === "linked"
                        ? `linked (${d.parse.parse_status})`
                        : `missing (${d.parse.parse_status})`}
                    </td>
                    <td>
                      {d.next_actions.length > 0
                        ? `${d.next_actions.length} candidate action link(s)`
                        : "missing"}
                    </td>
                    <td>
                      {d.missing_reasons.length === 0 ? (
                        "none"
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
              Linkage notes: {view.linkage_errors.join("; ")}
            </p>
          )}
        </section>
      )}

      {view && (
        <div className="card-grid card-grid-2">
          <section className="card" aria-labelledby="trace-context-heading">
            <h2 id="trace-context-heading">Episode context</h2>
            <h3>Participants</h3>
            {participants.length === 0 ? (
              <p className="note">No participants recorded yet.</p>
            ) : (
              <ul className="tight">
                {participants.map((p) => (
                  <li key={p.agent_id}>
                    <strong>{p.agent_id}</strong> — sent {p.sent.length},
                    received {p.received.length}, actions {p.actions.length}
                  </li>
                ))}
              </ul>
            )}
            <h3>Episodes</h3>
            {episodes.length === 0 ? (
              <p className="note">No episodes recorded yet.</p>
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
            <h2 id="trace-weak-heading">Repeated weak signals</h2>
            <p className="note">
              Per sender, deliveries with a strongest family score in
              the weak band (above 0, below{" "}
              {view.weak_signals.band.max_exclusive}). Two or more mark
              a repeated pattern. Triage aid only — not a verdict and
              not proof of signalling.
            </p>
            {view.weak_signals.per_sender.length === 0 ? (
              <p className="note">No sender activity recorded yet.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <caption>Weak-signal counts per sender for this run.</caption>
                  <thead>
                    <tr>
                      <th>Sender</th>
                      <th>Deliveries</th>
                      <th>Weak signals</th>
                      <th>Repeated</th>
                      <th>Strongest score</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.weak_signals.per_sender.map((r) => (
                      <tr key={r.sender_id}>
                        <td>{r.sender_id}</td>
                        <td>{r.deliveries}</td>
                        <td>{r.weak_signals}</td>
                        <td>{r.repeated_weak ? "yes — repeated" : "no"}</td>
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
          <h2 id="trace-actions-heading">Actions and candidate inputs</h2>
          <p className="note">
            {view.causation_note}. causation_claimed: false for every
            action listed here.
          </p>
          {view.actions.length === 0 ? (
            <p className="note">
              No recipient actions recorded in this run. Delivered
              artifacts list this link as missing with its reason.
            </p>
          ) : (
            <div className="table-wrap">
              <table>
                <caption>
                  Recipient actions with candidate input artifacts.
                  Candidates are visible inputs, not a cause.
                </caption>
                <thead>
                  <tr>
                    <th>Action</th>
                    <th>Recipient</th>
                    <th>Candidate inputs</th>
                    <th>Causation claimed</th>
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
                          ? "none visible before this action"
                          : a.candidate_delivery_ids
                              .map((id) => `${id.slice(0, 18)}…`)
                              .join(", ")}
                      </td>
                      <td>{a.causation_claimed ? "yes" : "false"}</td>
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
