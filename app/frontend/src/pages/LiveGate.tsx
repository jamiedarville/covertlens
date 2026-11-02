// Live Gate page (CL-53): watch one delivery move pending →
// analysed → verdict → delivered or withheld. The recipient pane
// only ever shows bytes the gate served to the recipient; withheld
// deliveries show the gate's reason and no image.

import { useCallback, useEffect, useRef, useState } from "react";
import type { GateDelivery, GateEvent, GateRunDetail } from "../types";
import {
  ApiError,
  analyzeGateDelivery,
  createGateRun,
  fetchGateRun,
  postGateDelivery,
  recipientImageUrl,
  recordGateVerdict,
  reviewerImageUrl,
} from "../api";

const ROUTES = ["R-01", "R-02", "R-03", "R-04", "R-05", "R-06", "R-07"];
const VERDICTS = ["log", "flag", "quarantine", "fail_run"];

export default function LiveGate() {
  const [runId, setRunId] = useState("");
  const [senderId, setSenderId] = useState("agent-a");
  const [recipientId, setRecipientId] = useState("agent-b");
  const [episodeId, setEpisodeId] = useState("");
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
          setRecipientNote("delivered — the recipient received these bytes.");
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

  const onCreateRun = async () => {
    setBusy(true);
    setError(null);
    try {
      const id = await createGateRun(runId.trim() || undefined);
      setRunId(id);
      setDetail(null);
      setSelectedId(null);
      setStatusLine(`Run ${id} ready. Post an image as the sender.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the run.");
    } finally {
      setBusy(false);
    }
  };

  const onPost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!runId.trim()) {
      setError("Create a run first.");
      return;
    }
    if (!file) {
      setError("Choose a PNG or JPEG to send.");
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
      setStatusLine("Delivery pending — analyse it, then apply a verdict.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delivery failed.");
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
        `Analysis complete. Suggested verdict: ${result.suggested_verdict}. Apply a verdict to decide delivery.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Analysis failed.");
    } finally {
      setBusy(false);
    }
  };

  const onVerdict = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await recordGateVerdict(selected.delivery_id, verdictChoice);
      await refresh(runId.trim());
      setStatusLine(
        updated.state === "permitted"
          ? "Verdict permits delivery. The recipient pane now shows the image."
          : updated.recipient_message,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verdict failed.");
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
      setStatusLine(`Loaded run ${runId.trim()}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the run.");
    } finally {
      setBusy(false);
    }
  };

  const report = detail?.access_report ?? {};
  const unauthorized = Number(report.unauthorized_served ?? 0);

  return (
    <>
      <h1>Live Gate</h1>
      <p>
        Send an image through the gate and watch it move: pending, then
        analysed, then a verdict, then delivered or withheld. The
        recipient only ever sees bytes after a permitting verdict. The
        reviewer can still open quarantined originals, with the read
        audited. Gate state is stored on the server, so refreshing or
        restarting keeps the run.
      </p>

      <section className="card" aria-labelledby="gate-run-heading">
        <h2 id="gate-run-heading">Run</h2>
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
          <label>
            Sender
            <input type="text" value={senderId} onChange={(e) => setSenderId(e.target.value)} />
          </label>
          <label>
            Recipient
            <input
              type="text"
              value={recipientId}
              onChange={(e) => setRecipientId(e.target.value)}
            />
          </label>
          <label>
            Episode (optional)
            <input
              type="text"
              value={episodeId}
              onChange={(e) => setEpisodeId(e.target.value)}
              placeholder="ep_1"
            />
          </label>
        </div>
        <p>
          <button type="button" className="button button-primary" onClick={onCreateRun} disabled={busy}>
            Create run
          </button>{" "}
          <button type="button" className="button" onClick={onLoadRun} disabled={busy || !runId.trim()}>
            Load run
          </button>
        </p>
      </section>

      <form onSubmit={onPost} className="generate-form">
        <fieldset>
          <legend>Sender: post an image</legend>
          <div className="form-grid">
            <label>
              Route
              <select value={routeId} onChange={(e) => setRouteId(e.target.value)} disabled={busy}>
                {ROUTES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </label>
            <label>
              Image (PNG or JPEG)
              <input
                type="file"
                accept="image/png,image/jpeg,.png,.jpg,.jpeg"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                disabled={busy}
              />
            </label>
          </div>
          <p>
            <button type="submit" className="button button-primary" disabled={busy}>
              Post through the gate
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
          <h2 id="gate-deliveries-heading">Deliveries in this run</h2>
          <div className="table-wrap">
            <table>
              <caption>Choose a delivery to analyse and decide.</caption>
              <thead>
                <tr>
                  <th>Delivery</th>
                  <th>Route identities</th>
                  <th>State</th>
                  <th>Verdict</th>
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
                    <td>{d.state}</td>
                    <td>{d.verdict ?? "—"}</td>
                    <td>
                      <button
                        type="button"
                        className="button"
                        onClick={() => {
                          setSelectedId(d.delivery_id);
                          setSuggested(null);
                        }}
                      >
                        Select
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
          <h2 id="gate-decide-heading">Analyse and decide</h2>
          <dl className="kv kv-wide">
            <div><dt>State</dt><dd>{selected.state}</dd></div>
            <div><dt>Recipient view</dt><dd>{selected.recipient_message}</dd></div>
            <div><dt>Content hash</dt><dd>{selected.content_hash}</dd></div>
          </dl>
          {selected.state === "pending" && (
            <>
              <p>
                <button type="button" className="button" onClick={onAnalyze} disabled={busy}>
                  Analyse
                </button>
              </p>
              {suggested && (
                <p className="note">
                  Suggested verdict from analysis: <strong>{suggested}</strong>.
                  With unfrozen thresholds this is triage only; choose the
                  gate verdict to apply.
                </p>
              )}
              <div className="form-grid">
                <label>
                  Verdict
                  <select value={verdictChoice} onChange={(e) => setVerdictChoice(e.target.value)} disabled={busy}>
                    {VERDICTS.map((v) => (
                      <option key={v} value={v}>{v}</option>
                    ))}
                  </select>
                </label>
              </div>
              <p>
                <button type="button" className="button button-primary" onClick={onVerdict} disabled={busy}>
                  Apply verdict
                </button>
              </p>
            </>
          )}
          {selected.state !== "pending" && (
            <p className="note">This delivery is decided. Post another image to run the gate again.</p>
          )}
        </section>
      )}

      <div className="card-grid card-grid-2">
        <section className="card" aria-labelledby="recipient-heading">
          <h2 id="recipient-heading">Recipient pane</h2>
          {!selected ? (
            <p className="note">Select a delivery to see what the recipient gets.</p>
          ) : selected.state === "permitted" && recipientUrl ? (
            <>
              <img className="skyline-img" src={recipientUrl} alt="Image delivered to the recipient" />
              <p>{recipientNote}</p>
            </>
          ) : (
            <>
              <p data-testid="recipient-withheld">
                <strong>{selected.state === "withheld" ? "withheld" : selected.state}</strong>
                {" — "}
                {recipientNote || selected.recipient_message}
              </p>
              <p className="note">No image is shown here for a withheld delivery.</p>
            </>
          )}
        </section>

        <section className="card" aria-labelledby="reviewer-heading">
          <h2 id="reviewer-heading">Reviewer pane</h2>
          {!selected ? (
            <p className="note">Select a delivery to open it as researcher-1 (R-08, audited).</p>
          ) : (
            <>
              <img
                className="skyline-img"
                src={reviewerImageUrl(selected.delivery_id)}
                alt="Original opened by the reviewer"
              />
              <p className="note">
                Reviewer evidence view. Recipients never get bytes through
                this path.
              </p>
            </>
          )}
        </section>
      </div>

      {detail && (
        <>
          <section aria-labelledby="gate-timeline-heading">
            <h2 id="gate-timeline-heading">Timeline</h2>
            {detail.events.length === 0 ? (
              <p className="note">No events yet. Post an image to start the timeline.</p>
            ) : (
              <ol className="tight">
                {detail.events.map((event) => (
                  <li key={event.event_id}>
                    <span className="mono-small">#{event.seq} {event.event_type}</span>
                    {event.verdict ? ` · verdict ${event.verdict}` : ""}
                    {" · "}
                    {event.occurred_at}
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section aria-labelledby="gate-audit-heading">
            <h2 id="gate-audit-heading">Access-attempt audit</h2>
            <dl className="kv kv-wide">
              <div><dt>Attempts</dt><dd>{String(report.attempts ?? 0)}</dd></div>
              <div><dt>Served to recipient</dt><dd>{String(report.served ?? 0)}</dd></div>
              <div><dt>Unauthorized served</dt><dd>{String(unauthorized)}</dd></div>
              <div><dt>Withheld denied</dt><dd>{String(report.withheld_denied ?? 0)}</dd></div>
            </dl>
            {unauthorized !== 0 && (
              <p className="alert" role="alert">Unauthorized bytes were served.</p>
            )}
            {detail.access_attempts.length > 0 && (
              <div className="table-wrap">
                <table>
                  <caption>Every recorded attempt, newest last.</caption>
                  <thead>
                    <tr><th>Delivery</th><th>Route</th><th>Outcome</th><th>State then</th></tr>
                  </thead>
                  <tbody>
                    {detail.access_attempts.map((a, i) => (
                      <tr key={i}>
                        <td className="num">{String(a.delivery_id ?? "").slice(0, 18)}…</td>
                        <td>{String(a.via_route ?? "—")}</td>
                        <td>{String(a.outcome ?? "")}</td>
                        <td>{String(a.delivery_state ?? "—")}</td>
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
