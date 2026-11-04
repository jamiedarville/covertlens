// Live Gate page (CL-53): watch one delivery move pending →
// analysed → verdict → delivered or withheld. The recipient pane
// only ever shows bytes the gate served to the recipient; withheld
// deliveries show the gate's reason and no image. The reviewer
// pane opens the original only on request, as the chosen demo role;
// a viewer is denied and the attempt is audited (CL-78).

import { useCallback, useEffect, useRef, useState } from "react";
import type { GateDelivery, GateEvent, GateRunDetail } from "../types";
import {
  ApiError,
  analyzeGateDelivery,
  createGateRun,
  fetchGateRun,
  fetchReviewerImage,
  postGateDelivery,
  recipientImageUrl,
  recordGateVerdict,
} from "../api";
import { RoleControl } from "../components/RoleControl";
import { useDemoRole } from "../demoRole";
import { gateStateLabel, humanizeKey, verdictLabel, verdictMeaning } from "../format";
import { StartSteps, TechDetails } from "../components/Help";

// How the image travels from sender to recipient (covertlens/routes.py).
// The gate checks the image on every one of these paths.
const ROUTES: { value: string; label: string }[] = [
  { value: "R-01", label: "A tool returns the picture itself in its output (R-01)" },
  { value: "R-02", label: "A tool returns a link to a picture file (R-02)" },
  { value: "R-03", label: "An agent message points to a picture (R-03)" },
  { value: "R-04", label: "The recipient downloads it from storage (R-04)" },
  { value: "R-05", label: "The recipient opens a saved link to it (R-05)" },
  { value: "R-06", label: "The recipient asks for a preview or thumbnail (R-06)" },
  { value: "R-07", label: "The picture is handed to the recipient’s image reader (R-07)" },
];

// Recipient pane: an image only for a permitted delivery whose bytes the
// recipient path served; otherwise the gate's reason and no image.
export function RecipientPane({
  delivery,
  imageUrl,
  note,
}: {
  delivery: GateDelivery | null;
  imageUrl: string | null;
  note: string;
}) {
  return (
    <section className="card" aria-labelledby="recipient-heading">
      <h2 id="recipient-heading">Step 4a — What the recipient sees</h2>
      <p className="note">
        This box fetches the picture exactly the way the recipient
        would. If the gate has not let it through, there is nothing to
        fetch — only an explanation.
      </p>
      {!delivery ? (
        <p className="note">Nothing to show yet: send a picture in step 2 and choose it from the table above.</p>
      ) : delivery.state === "permitted" && imageUrl ? (
        <>
          <img className="skyline-img" src={imageUrl} alt="The picture exactly as delivered to the recipient" />
          <p>{note}</p>
        </>
      ) : (
        <>
          <p data-testid="recipient-withheld">
            <strong>{gateStateLabel(delivery.state)}</strong>
            {" — "}
            {note || delivery.recipient_message}
          </p>
          <p className="note">
            No picture is shown here, and none is hidden in this page
            waiting to be uncovered: the recipient’s request is refused
            by the server. That refusal is written into the audit
            record below.
          </p>
        </>
      )}
    </section>
  );
}

// Reviewer pane: closed until opened, and opened only as the chosen role.
export function ReviewerPane({
  delivery,
  imageUrl,
  note,
  role,
  busy,
  onOpen,
}: {
  delivery: GateDelivery | null;
  imageUrl: string | null;
  note: string;
  role: string;
  busy: boolean;
  onOpen: () => void;
}) {
  return (
    <section className="card" aria-labelledby="reviewer-heading">
      <h2 id="reviewer-heading">Step 4b — What a reviewer may open</h2>
      <p className="note">
        Held-back pictures are not deleted. An authorised person can
        still open the original through a separate, reviewers-only
        path (route R-08) to judge it. Recipients can never use this
        path, and every use is recorded.
      </p>
      {!delivery ? (
        <p className="note">Nothing to open yet: choose a picture from the table above first.</p>
      ) : (
        <>
          {imageUrl ? (
            <img className="skyline-img" src={imageUrl} alt="The original picture, opened by the reviewer" />
          ) : (
            <p>
              <button type="button" className="button" onClick={onOpen} disabled={busy}>
                Open the original picture (you are pretending to be a {role})
              </button>{" "}
              <span className="note">Works only as researcher or reviewer; as viewer you will be refused — try it and watch the audit record below.</span>
            </p>
          )}
          {note && <p data-testid="reviewer-note">{note}</p>}
        </>
      )}
    </section>
  );
}
const VERDICTS = ["log", "flag", "quarantine", "fail_run"];

export default function LiveGate() {
  const [runId, setRunId] = useState("");
  const [senderId, setSenderId] = useState("agent-a");
  const [recipientId, setRecipientId] = useState("agent-b");
  const [episodeId, setEpisodeId] = useState("");
  const [declared, setDeclared] = useState("");
  const [routeId, setRouteId] = useState("R-01");
  const [file, setFile] = useState<File | null>(null);
  const [detail, setDetail] = useState<GateRunDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [verdictChoice, setVerdictChoice] = useState("log");
  const [suggested, setSuggested] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState("");
  const [recipientUrl, setRecipientUrl] = useState<string | null>(null);
  const [recipientNote, setRecipientNote] = useState("");
  const [role, setRole] = useDemoRole();
  const [reviewerUrl, setReviewerUrl] = useState<string | null>(null);
  const [reviewerNote, setReviewerNote] = useState("");
  const sourceRef = useRef<EventSource | null>(null);

  const selected: GateDelivery | null =
    detail?.deliveries.find((d) => d.delivery_id === selectedId) ?? null;

  const refresh = useCallback(async (id: string) => {
    if (!id) return;
    const next = await fetchGateRun(id);
    setDetail(next);
  }, []);

  // SSE timeline: append streamed events without refetching all.
  useEffect(() => {
    if (!runId) return;
    sourceRef.current?.close();
    const source = new EventSource(
      `/api/gate/runs/${encodeURIComponent(runId)}/events/stream`,
    );
    sourceRef.current = source;
    source.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as GateEvent;
        setDetail((prev) => {
          if (!prev || prev.run_id !== runId) return prev;
          if (prev.events.some((e) => e.seq === event.seq)) return prev;
          return { ...prev, events: [...prev.events, event] };
        });
      } catch {
        // Keep-alive or malformed frame: ignore.
      }
    };
    return () => source.close();
  }, [runId]);

  // Recipient pane: fetch bytes only through the recipient path.
  // A withheld/pending delivery returns the gate's reason as JSON;
  // the pane shows that text and never an image.
  useEffect(() => {
    if (!selected) {
      setRecipientUrl(null);
      setRecipientNote("");
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setRecipientUrl(null);
    if (selected.state === "permitted") {
      fetch(recipientImageUrl(selected.delivery_id))
        .then(async (response) => {
          if (!response.ok) throw new Error("recipient fetch failed");
          const blob = await response.blob();
          if (cancelled) return;
          objectUrl = URL.createObjectURL(blob);
          setRecipientUrl(objectUrl);
          setRecipientNote("Delivered — this is exactly the picture the recipient received.");
        })
        .catch(() => {
          if (!cancelled) setRecipientNote(selected.recipient_message);
        });
    } else {
      setRecipientNote(selected.recipient_message);
      // Record the denied attempt so the audit shows it.
      fetch(recipientImageUrl(selected.delivery_id)).catch(() => undefined);
    }
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selected]);

  // Reviewer pane: closed until the operator opens it, and closed
  // again whenever the delivery or the demo role changes.
  const selectedDeliveryId = selected?.delivery_id ?? null;
  useEffect(() => {
    setReviewerUrl(null);
    setReviewerNote("");
  }, [selectedDeliveryId, role]);
  useEffect(() => {
    return () => {
      if (reviewerUrl) URL.revokeObjectURL(reviewerUrl);
    };
  }, [reviewerUrl]);

  const onOpenOriginal = async () => {
    if (!selected) return;
    setReviewerNote("");
    try {
      const blob = await fetchReviewerImage(selected.delivery_id, role);
      setReviewerUrl(URL.createObjectURL(blob));
      setReviewerNote(`You opened the original picture while pretending to be a ${role}, through the reviewers-only path (route R-08). This opening has been written into the audit record below.`);
    } catch (err) {
      setReviewerUrl(null);
      setReviewerNote(
        err instanceof ApiError && err.status === 403
          ? `Not allowed while pretending to be a ${role}: opening the original needs researcher or reviewer. What to do: change the kind of user above and try again. This refused attempt has also been written into the audit record.`
          : "The original picture could not be opened just now. What to do: try again in a moment.",
      );
    } finally {
      await refresh(runId.trim()).catch(() => undefined);
    }
  };

  const onCreateRun = async () => {
    setBusy(true);
    setError(null);
    try {
      const channels = declared
        .split(",")
        .map((name) => name.trim())
        .filter(Boolean);
      const id = await createGateRun(runId.trim() || undefined, channels);
      setRunId(id);
      setDetail(null);
      setSelectedId(null);
      setStatusLine(`Your session “${id}” is ready. Next step: send a picture through the gate using the form below. Remember this name — the timeline and review pages will ask for it.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The session could not be started. What to do: try again, or type a different session name.");
    } finally {
      setBusy(false);
    }
  };

  const onPost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!runId.trim()) {
      setError("Start a session first: use “Start a new session” above. Every picture belongs to a named session so you can find it again later.");
      return;
    }
    if (!file) {
      setError("Choose a picture to send first (PNG or JPEG).");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const delivery = await postGateDelivery({
        file,
        runId: runId.trim(),
        senderId,
        recipientId,
        routeId,
        episodeId: episodeId.trim() || undefined,
      });
      setSelectedId(delivery.delivery_id);
      setSuggested(null);
      await refresh(runId.trim());
      setStatusLine("The picture is now waiting at the gate — the recipient cannot see it yet. Next step: choose “Check this picture”, then decide whether it may go through.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The picture could not be sent. What to do: check it is a PNG or JPEG and try again.");
    } finally {
      setBusy(false);
    }
  };

  const onAnalyze = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const result = await analyzeGateDelivery(selected.delivery_id);
      setSuggested(result.suggested_verdict);
      setVerdictChoice(result.suggested_verdict);
      setStatusLine(
        `Check finished. Based on the scores, we suggest: “${verdictLabel(result.suggested_verdict)}”. Nothing has been decided yet — choose a decision below and apply it.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The check could not be completed. What to do: try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  const onVerdict = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await recordGateVerdict(selected.delivery_id, verdictChoice, role);
      await refresh(runId.trim());
      setStatusLine(
        updated.state === "permitted"
          ? "Decision applied: the picture was let through. You can see exactly what the recipient received in the “What the recipient sees” box below."
          : `Decision applied: the picture was held back. ${updated.recipient_message}`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? `Not allowed while pretending to be a ${role}: deciding deliveries needs the researcher kind of user. What to do: change the kind of user above to researcher, then apply the decision again.`
          : err instanceof ApiError
            ? err.message
            : "The decision could not be applied. What to do: try again in a moment.",
      );
    } finally {
      setBusy(false);
    }
  };

  const onLoadRun = async () => {
    if (!runId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await refresh(runId.trim());
      setStatusLine(`Session “${runId.trim()}” loaded. Its pictures and history are shown below.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That session could not be loaded. What to do: check you typed its name exactly as when you created it.");
    } finally {
      setBusy(false);
    }
  };

  const report = detail?.access_report ?? {};
  const unauthorized = Number(report.unauthorized_served ?? 0);

  return (
    <>
      <h1>Watch an image go through the delivery gate</h1>
      <p>
        This page demonstrates the checkpoint every image passes before a
        recipient can see it. You play all the parts: you send a picture,
        run the checks on it, decide whether it may go through, and then
        see exactly what the recipient gets. The most important thing to
        notice: <strong>the recipient can never open a picture that was
        held back</strong> — but an authorised reviewer still can, and
        every opening (and every refused attempt) is written into an
        audit record.
      </p>
      <StartSteps heading="Do it in four steps">
        <li><strong>Start a session</strong> (called a “run”): a named experiment session that groups related pictures so you can find them again later.</li>
        <li><strong>Send a picture</strong> from the sender to the recipient. It waits at the gate — the recipient cannot see it yet.</li>
        <li><strong>Check it, then decide</strong>: let it through, let it through but flag it, hold it back for review, or hold it back and stop the session.</li>
        <li><strong>Compare the two boxes</strong> at the bottom: what the recipient sees, and what a reviewer may open.</li>
      </StartSteps>
      <p className="note">
        Everything is saved on the server, so you can reload this page and
        carry on where you left off using the same session name.
      </p>

      <section className="card" aria-labelledby="gate-run-heading">
        <h2 id="gate-run-heading">Step 1 — Your session (“run”)</h2>
        <div className="form-grid">
          <label>
            Session name (run ID)
            <input
              type="text"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              placeholder="run_live_demo"
            />
            <span className="note">Any name you will remember, for example run_live_demo. Leave empty and one is made for you. The timeline and review pages will ask for this exact name.</span>
          </label>
          <label>
            Sender (who sends the picture)
            <input type="text" value={senderId} onChange={(e) => setSenderId(e.target.value)} />
            <span className="note">A name for the sending agent, for example agent-a.</span>
          </label>
          <label>
            Recipient (who the picture is for)
            <input
              type="text"
              value={recipientId}
              onChange={(e) => setRecipientId(e.target.value)}
            />
            <span className="note">A name for the receiving agent, for example agent-b.</span>
          </label>
          <label>
            Episode label (optional)
            <input
              type="text"
              value={episodeId}
              onChange={(e) => setEpisodeId(e.target.value)}
              placeholder="ep_1"
            />
            <span className="note">An optional extra label to group a few deliveries inside the session, for example ep_1. You can leave this empty.</span>
          </label>
          <label>
            Shape measurements openly used by the task (optional)
            <input
              type="text"
              value={declared}
              onChange={(e) => setDeclared(e.target.value)}
              placeholder="height"
              aria-describedby="declared-help"
            />
          </label>
        </div>
        <p className="note" id="declared-help">
          If the task openly uses shape measurements, list them here before
          sending the first picture: height, gap (spacing), lit (brightness),
          colour, or angle. Separate names with commas. Leave empty if none
          apply. Regular spacing in a listed measurement is recorded without
          blocking delivery on its own. Patterns within it are still checked,
          using a stricter threshold.
        </p>
        <RoleControl
          role={role}
          onChange={setRole}
          disabled={busy}
          hint="For this page: deciding a delivery needs researcher. Opening a held-back original needs researcher or reviewer."
        />
        <p>
          <button type="button" className="button button-primary" onClick={onCreateRun} disabled={busy}>
            Start a new session
          </button>{" "}
          <button type="button" className="button" onClick={onLoadRun} disabled={busy || !runId.trim()}>
            Re-open an existing session
          </button>
          {!runId.trim() && (
            <span className="note"> To re-open an old session, type its name above first.</span>
          )}
        </p>
      </section>

      <form onSubmit={onPost} className="generate-form">
        <fieldset>
          <legend>Step 2 — The sender sends a picture</legend>
          <div className="form-grid">
            <label>
              How does the picture travel to the recipient?
              <select value={routeId} onChange={(e) => setRouteId(e.target.value)} disabled={busy}>
                {ROUTES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
              <span className="note">CovertLens checks the picture on every one of these paths, so there is no unchecked way around the gate. Leave the first choice if you are unsure.</span>
            </label>
            <label>
              Picture to send (PNG or JPEG)
              <input
                type="file"
                accept="image/png,image/jpeg,.png,.jpg,.jpeg"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                disabled={busy}
              />
              <span className="note">Tip: use “Make a test image” in the menu to create a picture with a pattern hidden in it.</span>
            </label>
          </div>
          <p>
            <button type="submit" className="button button-primary" disabled={busy}>
              Send the picture to the gate (recipient cannot see it yet)
            </button>
          </p>
        </fieldset>
      </form>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && (
        <p className="alert" role="alert">{error}</p>
      )}

      {detail && detail.deliveries.length > 0 && (
        <section aria-labelledby="gate-deliveries-heading">
          <h2 id="gate-deliveries-heading">Pictures sent in this session</h2>
          <div className="table-wrap">
            <table>
              <caption>Every picture sent so far. Choose one to check it and decide whether the recipient may see it.</caption>
              <thead>
                <tr>
                  <th>Picture (short ID)</th>
                  <th>From → to, and file fingerprint</th>
                  <th>Where it stands now</th>
                  <th>Decision taken</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {detail.deliveries.map((d) => (
                  <tr key={d.delivery_id} className={d.delivery_id === selectedId ? "row-active" : ""}>
                    <td className="num">{d.delivery_id.slice(0, 18)}…</td>
                    <td>
                      {d.sender_id} → {d.recipient_id}
                      <br />
                      <span className="mono-small">{d.content_hash.slice(0, 24)}…</span>
                    </td>
                    <td title={d.state}>{gateStateLabel(d.state)}</td>
                    <td title={d.verdict ?? undefined}>{d.verdict ? verdictLabel(d.verdict) : "none yet"}</td>
                    <td>
                      <button
                        type="button"
                        className="button"
                        onClick={() => {
                          setSelectedId(d.delivery_id);
                          setSuggested(null);
                        }}
                      >
                        Choose this picture
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {selected && (
        <section className="card" aria-labelledby="gate-decide-heading">
          <h2 id="gate-decide-heading">Step 3 — Check this picture and decide</h2>
          <dl className="kv kv-wide">
            <div><dt>Where it stands now</dt><dd title={selected.state}>{gateStateLabel(selected.state)}</dd></div>
            <div><dt>What the recipient is told right now</dt><dd>{selected.recipient_message}</dd></div>
          </dl>
          <TechDetails summary="File fingerprint (for matching this exact file later)">
            <p className="note hash-line">{selected.content_hash}</p>
          </TechDetails>
          {selected.state === "pending" && (
            <>
              <p>
                <button type="button" className="button" onClick={onAnalyze} disabled={busy}>
                  Check this picture (runs all four checks)
                </button>{" "}
                <span className="note">Checking does not decide anything — it only suggests a decision for you below.</span>
              </p>
              {suggested && (
                <p className="note">
                  Suggested from the scores: <strong>{verdictLabel(suggested)}</strong>{" "}
                  (exact value: {suggested}). Treat this as a prompt to look
                  closer, not a final judgement — you choose the decision.
                </p>
              )}
              <div className="form-grid">
                <label>
                  Your decision (called a “verdict”)
                  <select value={verdictChoice} onChange={(e) => setVerdictChoice(e.target.value)} disabled={busy}>
                    {VERDICTS.map((v) => (
                      <option key={v} value={v}>{verdictLabel(v)} ({v})</option>
                    ))}
                  </select>
                  <span className="note">{verdictMeaning(verdictChoice)}</span>
                </label>
              </div>
              <p>
                <button type="button" className="button button-primary" onClick={onVerdict} disabled={busy}>
                  Apply this decision now
                </button>{" "}
                <span className="note">Needs the researcher kind of user (see step 1). The recipient’s view below updates immediately.</span>
              </p>
            </>
          )}
          {selected.state !== "pending" && (
            <p className="note">This picture has already been decided, and decisions here cannot be changed. What to do next: send another picture in step 2 to run the gate again, or open the review page to judge a held-back picture.</p>
          )}
        </section>
      )}

      <div className="card-grid card-grid-2">
        <RecipientPane
          delivery={selected}
          imageUrl={recipientUrl}
          note={recipientNote}
        />

        <ReviewerPane
          delivery={selected}
          imageUrl={reviewerUrl}
          note={reviewerNote}
          role={role}
          busy={busy}
          onOpen={onOpenOriginal}
        />
      </div>

      {detail && (
        <>
          <section aria-labelledby="gate-timeline-heading">
            <h2 id="gate-timeline-heading">What has happened so far, in order</h2>
            <p className="note">Every step in this session, oldest first. New steps appear here automatically.</p>
            {detail.events.length === 0 ? (
              <p className="note">Nothing has happened in this session yet. Send a picture in step 2 to start this list.</p>
            ) : (
              <ol className="tight">
                {detail.events.map((event) => (
                  <li key={event.event_id}>
                    <span title={event.event_type}>{humanizeKey(event.event_type)}</span>
                    {event.verdict ? ` — decision: ${verdictLabel(event.verdict).toLowerCase()}` : ""}
                    {" · "}
                    <span className="mono-small">#{event.seq} · {event.occurred_at}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section aria-labelledby="gate-audit-heading">
            <h2 id="gate-audit-heading">Record of who tried to open what (audit)</h2>
            <p className="note">
              Every attempt to open a picture in this session is counted
              here — including refused attempts, such as the recipient
              asking for a held-back picture (this page makes that request
              for you so you can see it recorded). The number that must
              always be zero is “opened without permission”.
            </p>
            <dl className="kv kv-wide">
              <div><dt>Total attempts to open a picture</dt><dd>{String(report.attempts ?? 0)}</dd></div>
              <div><dt>Given to the recipient (allowed)</dt><dd>{String(report.served ?? 0)}</dd></div>
              <div><dt>Given out without permission (must be 0)</dt><dd>{String(unauthorized)}</dd></div>
              <div><dt>Recipient refused because the picture is held back</dt><dd>{String(report.withheld_denied ?? 0)}</dd></div>
              <div><dt>Opened by a reviewer, allowed (route R-08)</dt><dd>{String(report.reviewer_served ?? 0)}</dd></div>
              <div><dt>Reviewer opening refused (route R-08)</dt><dd>{String(report.reviewer_denied ?? 0)}</dd></div>
            </dl>
            {unauthorized !== 0 && (
              <p className="alert" role="alert">
                Warning: a picture was given out without permission. This
                should never happen — treat this session’s results as
                untrustworthy and tell whoever runs this server.
              </p>
            )}
            {detail.access_attempts.length > 0 && (
              <div className="table-wrap">
                <table>
                  <caption>Every recorded attempt to open a picture, oldest first. “Route” is the path the request took (see step 2); R-08 is the reviewers-only path.</caption>
                  <thead>
                    <tr><th>Picture (short ID)</th><th>Path used</th><th>Allowed or refused</th><th>Picture’s status at the time</th><th>Who asked</th></tr>
                  </thead>
                  <tbody>
                    {detail.access_attempts.map((a, i) => (
                      <tr key={i}>
                        <td className="num">{String(a.delivery_id ?? "").slice(0, 18)}…</td>
                        <td>{String(a.via_route ?? "—")}</td>
                        <td>{String(a.outcome ?? "")}</td>
                        <td>{String(a.delivery_state ?? "—")}</td>
                        <td>{String(a.actor_id ?? "—")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}
