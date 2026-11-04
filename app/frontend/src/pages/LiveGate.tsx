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
import {
  LIGHT_HEADLINE,
  LIGHT_NAME,
  gateStateLabel,
  humanizeKey,
  lightForVerdict,
  verdictLabel,
  verdictMeaning,
} from "../format";
import { AdvancedSettings, TechnicalBreakdown } from "../components/Help";
import { LightDot, VerdictLight } from "../components/TrafficLight";

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
      <h3 id="recipient-heading">What the other agent sees</h3>
      {!delivery ? (
        <p className="note">Nothing yet. Send an image in step 2, then choose it from the list.</p>
      ) : delivery.state === "permitted" && imageUrl ? (
        <>
          <img className="skyline-img" src={imageUrl} alt="The image exactly as the other agent received it" />
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
            There’s no image here to uncover: the server refuses the other
            agent’s request, and the refusal is recorded.
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
      <h3 id="reviewer-heading">What a reviewer can open</h3>
      <p className="note">
        Held-back images aren’t deleted. A reviewer can still open the
        original through a separate, reviewers-only route, and every
        opening is recorded.
      </p>
      {!delivery ? (
        <p className="note">Nothing yet. Choose an image from the list first.</p>
      ) : (
        <>
          {imageUrl ? (
            <img className="skyline-img" src={imageUrl} alt="The original image, opened by a reviewer" />
          ) : (
            <p>
              <button type="button" className="button" onClick={onOpen} disabled={busy}>
                Open the original picture (you are pretending to be a {role})
              </button>{" "}
              <span className="note">Only researchers and reviewers may. Try it as a viewer to see a refusal get recorded.</span>
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
  const [activeRun, setActiveRun] = useState<string | null>(null);
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
          setRecipientNote("Delivered. This is exactly the image the other agent received.");
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
      setReviewerNote(`You opened the original as a ${role}, through the reviewers-only route. This has been recorded.`);
    } catch (err) {
      setReviewerUrl(null);
      setReviewerNote(
        err instanceof ApiError && err.status === 403
          ? `Not allowed as a ${role}: opening the original needs Researcher or Reviewer. What to do: change “Who are you in this demo?” in step 1 and try again. This refused attempt has been recorded.`
          : "The original couldn’t be opened just now. What to do: try again in a moment.",
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
      setActiveRun(id);
      setDetail(null);
      setSelectedId(null);
      setStatusLine(`Your session “${id}” is ready. Next: send an image in step 2.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The session couldn’t be started. What to do: try again, or choose a different session name in the advanced settings.");
    } finally {
      setBusy(false);
    }
  };

  const onPost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!runId.trim()) {
      setError("Start a session first: press “Start a new session” in step 1.");
      return;
    }
    if (!file) {
      setError("Choose an image to send first (PNG or JPEG).");
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
      setStatusLine("The image is waiting at the gate; the other agent can’t see it yet. Next: press “Check this image” in step 3.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The image couldn’t be sent. What to do: check it’s a PNG or JPEG and try again.");
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
        `Check finished. We suggest: “${verdictLabel(result.suggested_verdict)}”. Nothing has been decided yet: choose a decision and apply it.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The check couldn’t be finished. What to do: try again in a moment.");
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
          ? "Decision applied: the image was let through. Step 4 shows exactly what the other agent received."
          : `Decision applied: the image was held back. ${updated.recipient_message}`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? `Not allowed as a ${role}: deciding needs the Researcher role. What to do: change “Who are you in this demo?” in step 1 to Researcher, then apply the decision again.`
          : err instanceof ApiError
            ? err.message
            : "The decision couldn’t be applied. What to do: try again in a moment.",
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
      setActiveRun(runId.trim());
      setStatusLine(`Session “${runId.trim()}” re-opened. Its images are listed below.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That session couldn’t be found. What to do: check you typed its name exactly as when you created it.");
    } finally {
      setBusy(false);
    }
  };

  const report = detail?.access_report ?? {};
  const unauthorized = Number(report.unauthorized_served ?? 0);
  const suggestedLight = suggested ? lightForVerdict(suggested) : null;

  return (
    <>
      <h1>Delivery gate</h1>
      <p className="lede">
        When one AI agent sends an image to another, it stops at a
        checkpoint first: the <strong>delivery gate</strong>. The gate
        checks the image, and the other agent only sees it if it’s let
        through. Try it yourself in four steps.
      </p>

      <section className="card step" aria-labelledby="gate-run-heading">
        <h2 id="gate-run-heading">Step 1 — Start a session</h2>
        <p>
          A session keeps your images together, so you can come back to
          them later on the review and timeline pages.
        </p>
        <RoleControl
          role={role}
          onChange={setRole}
          disabled={busy}
          hint="Pick Researcher to try every step: only researchers can decide what happens to an image."
        />
        <p>
          <button type="button" className="button button-primary" onClick={onCreateRun} disabled={busy}>
            Start a new session
          </button>
        </p>
        {activeRun && (
          <p className="note">
            Your session is called <strong>{activeRun}</strong>. Use this
            name on the review and timeline pages.
          </p>
        )}
        <AdvancedSettings id="gate-session-advanced" note="name the session and the agents, or re-open an old session">
          <div className="form-grid">
            <label>
              Session name (run ID)
              <input
                type="text"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                placeholder="run_live_demo"
              />
              <span className="note">Leave empty and a name is made for you. To re-open an old session, type its name and press “Re-open”.</span>
            </label>
            <label>
              Sender (the agent sending the image)
              <input type="text" value={senderId} onChange={(e) => setSenderId(e.target.value)} />
            </label>
            <label>
              Recipient (the agent it’s for)
              <input type="text" value={recipientId} onChange={(e) => setRecipientId(e.target.value)} />
            </label>
            <label>
              Episode label (optional)
              <input
                type="text"
                value={episodeId}
                onChange={(e) => setEpisodeId(e.target.value)}
                placeholder="ep_1"
              />
              <span className="note">An extra label to group a few images inside the session.</span>
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
            sending the first image: height, gap (spacing), lit (brightness),
            colour, or angle, separated by commas. Regular spacing in a listed
            measurement is recorded without blocking delivery on its own.
            Patterns within it are still checked, using a stricter threshold.
          </p>
          <p>
            <button type="button" className="button" onClick={onLoadRun} disabled={busy || !runId.trim()}>
              Re-open an existing session
            </button>
            {!runId.trim() && <span className="note"> Type the session’s name above first.</span>}
          </p>
        </AdvancedSettings>
      </section>

      <form onSubmit={onPost} className="card step generate-form" aria-labelledby="gate-send-heading">
        <h2 id="gate-send-heading">Step 2 — Send an image</h2>
        <p>The image goes to the gate first. The other agent can’t see it yet.</p>
        <p>
          <label className="file-pick">
            Image to send (PNG or JPEG){" "}
            <input
              type="file"
              accept="image/png,image/jpeg,.png,.jpg,.jpeg"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              disabled={busy}
            />
          </label>
        </p>
        <p className="note">Tip: use “Make a test image” in the menu to create an image with a hidden message in it.</p>
        <AdvancedSettings id="gate-send-advanced" note="choose how the image travels">
          <div className="form-grid">
            <label>
              How does the image travel to the other agent?
              <select value={routeId} onChange={(e) => setRouteId(e.target.value)} disabled={busy}>
                {ROUTES.map((r) => (
                  <option key={r.value} value={r.value}>{r.label}</option>
                ))}
              </select>
              <span className="note">The gate checks the image on every one of these routes, so there’s no unchecked way around it.</span>
            </label>
          </div>
        </AdvancedSettings>
        <p>
          <button type="submit" className="button button-primary" disabled={busy}>
            Send it to the gate
          </button>
        </p>
      </form>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && (
        <p className="alert" role="alert">{error}</p>
      )}

      {detail && detail.deliveries.length > 0 && (
        <section aria-labelledby="gate-deliveries-heading">
          <h2 id="gate-deliveries-heading">Images you’ve sent</h2>
          <ul className="item-list">
            {detail.deliveries.map((d, i) => (
              <li key={d.delivery_id} className={d.delivery_id === selectedId ? "item item-active" : "item"}>
                <span className="item-name" title={d.delivery_id}>Image {i + 1}</span>
                <span>{d.sender_id} → {d.recipient_id}</span>
                <span title={d.state}>{gateStateLabel(d.state)}</span>
                <span title={d.verdict ?? undefined}>
                  <VerdictLight verdict={d.verdict} label={d.verdict ? undefined : "No decision yet"} />
                </span>
                <button
                  type="button"
                  className="button"
                  onClick={() => {
                    setSelectedId(d.delivery_id);
                    setSuggested(null);
                  }}
                  disabled={d.delivery_id === selectedId}
                >
                  {d.delivery_id === selectedId ? "Chosen" : "Choose"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {selected && (
        <section className="card step" aria-labelledby="gate-decide-heading">
          <h2 id="gate-decide-heading">Step 3 — Check it and decide</h2>
          {selected.state === "pending" ? (
            <>
              <p>
                <button type="button" className="button" onClick={onAnalyze} disabled={busy}>
                  Check this image
                </button>{" "}
                <span className="note">Checking doesn’t decide anything. It only suggests a decision.</span>
              </p>
              {suggested && suggestedLight && (
                <p className={`result-pill result-${suggestedLight}`} data-light={suggestedLight}>
                  <LightDot light={suggestedLight} />
                  <span>
                    <strong>
                      {LIGHT_NAME[suggestedLight]}: {LIGHT_HEADLINE[suggestedLight]}.
                    </strong>{" "}
                    We suggest: {verdictLabel(suggested).toLowerCase()}.
                  </span>
                </p>
              )}
              <fieldset className="decision-choices">
                <legend>Your decision</legend>
                <div className="choice-list choice-list-wide">
                  {VERDICTS.map((v) => (
                    <label key={v} className={verdictChoice === v ? "choice choice-active" : "choice"}>
                      <input
                        type="radio"
                        name="gate-verdict"
                        value={v}
                        checked={verdictChoice === v}
                        onChange={() => setVerdictChoice(v)}
                        disabled={busy}
                      />
                      <LightDot light={lightForVerdict(v)} />
                      <span>
                        <strong>{verdictLabel(v)}</strong>
                        <span className="choice-about">{verdictMeaning(v)}</span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <p>
                <button type="button" className="button button-primary" onClick={onVerdict} disabled={busy}>
                  Apply this decision
                </button>{" "}
                <span className="note">Needs the Researcher role (step 1).</span>
              </p>
            </>
          ) : (
            <p>
              Decision taken: <VerdictLight verdict={selected.verdict} />.{" "}
              {verdictMeaning(selected.verdict)}{" "}
              <span className="note">Decisions can’t be changed. To try again, send another image.</span>
            </p>
          )}
        </section>
      )}

      <section aria-labelledby="gate-result-heading">
        <h2 id="gate-result-heading">Step 4 — See what happened</h2>
        <div className="card-grid card-grid-2">
          <RecipientPane delivery={selected} imageUrl={recipientUrl} note={recipientNote} />
          <ReviewerPane
            delivery={selected}
            imageUrl={reviewerUrl}
            note={reviewerNote}
            role={role}
            busy={busy}
            onOpen={onOpenOriginal}
          />
        </div>
      </section>

      {detail && <GateSafetyLine unauthorized={unauthorized} />}

      {detail && (
        <TechnicalBreakdown id="gate-breakdown" note="exact IDs, every recorded step and the full access record">
          <h2>Images in this session (exact values)</h2>
          <div className="table-wrap">
            <table>
              <caption>Every image sent so far, with the exact values the server recorded.</caption>
              <thead>
                <tr>
                  <th>Image</th>
                  <th>Delivery ID</th>
                  <th>From → to</th>
                  <th>File fingerprint</th>
                  <th>State (exact)</th>
                  <th>Decision (exact)</th>
                  <th>What the other agent is told</th>
                </tr>
              </thead>
              <tbody>
                {detail.deliveries.map((d, i) => (
                  <tr key={d.delivery_id}>
                    <td>Image {i + 1}</td>
                    <td className="num">{d.delivery_id}</td>
                    <td>{d.sender_id} → {d.recipient_id}</td>
                    <td className="mono-small">{d.content_hash}</td>
                    <td>{d.state}</td>
                    <td>{d.verdict ?? "—"}</td>
                    <td>{d.recipient_message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h2>What has happened so far, in order</h2>
          <p className="note">Every step in this session, oldest first. New steps appear here automatically.</p>
          {detail.events.length === 0 ? (
            <p className="note">Nothing has happened in this session yet.</p>
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

          <h2>Record of who tried to open what (audit)</h2>
          <p className="note">
            Every attempt to open an image on this server. This record
            covers all sessions, not only this one. It includes refused
            attempts, such as the other agent asking for a held-back image
            (this page makes that request for you so you can see it
            recorded). The number that must always be zero is “given out
            without permission”.
          </p>
          <dl className="kv kv-wide">
            <div><dt>Total attempts to open an image</dt><dd>{String(report.attempts ?? 0)}</dd></div>
            <div><dt>Given to the other agent (allowed)</dt><dd>{String(report.served ?? 0)}</dd></div>
            <div><dt>Given out without permission (must be 0)</dt><dd>{String(unauthorized)}</dd></div>
            <div><dt>Other agent refused, because the image is held back</dt><dd>{String(report.withheld_denied ?? 0)}</dd></div>
            <div><dt>Opened by a reviewer, allowed (route R-08)</dt><dd>{String(report.reviewer_served ?? 0)}</dd></div>
            <div><dt>Reviewer opening refused (route R-08)</dt><dd>{String(report.reviewer_denied ?? 0)}</dd></div>
          </dl>
          {detail.access_attempts.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption>Every recorded attempt to open an image, oldest first. “Route” is the path the request took; R-08 is the reviewers-only route.</caption>
                <thead>
                  <tr><th>Delivery (short ID)</th><th>Route</th><th>Allowed or refused</th><th>Image’s status at the time</th><th>Who asked</th></tr>
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
        </TechnicalBreakdown>
      )}
    </>
  );
}

// The audit's one number that must stay zero, as a plain line. The
// gate's access report covers the whole server, not one session.
export function GateSafetyLine({ unauthorized }: { unauthorized: number }) {
  return unauthorized === 0 ? (
    <p className="safety-line" data-testid="gate-safety" data-light="green">
      <LightDot light="green" />
      <span>
        <strong>Safety check passed:</strong> no image on this server has
        been given out without permission.
      </span>
    </p>
  ) : (
    <p className="alert" role="alert" data-testid="gate-safety">
      Warning: an image on this server was given out without permission.
      This should never happen. Treat these results as untrustworthy and
      tell whoever runs this server.
    </p>
  );
}
