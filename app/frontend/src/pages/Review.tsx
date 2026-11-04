// Reviewer page (CL-59): quarantined originals under a demo role.
// The role toggle only chooses which CL-11 principal the API acts
// as; it is a demo role, not authentication. Candidate decode text
// arrives only from the reviewer-only decode endpoint; every other
// response carries no decoded text.

import { useCallback, useEffect, useState } from "react";
import type {
  CandidateDecode,
  ReviewAudit,
  ReviewDetail,
  ReviewQueue,
  SecondOpinion,
  SecondOpinionConfig,
} from "../types";
import {
  ApiError,
  downloadReviewPackage,
  fetchCandidateDecode,
  fetchReviewAudit,
  fetchReviewDetail,
  fetchReviewOriginal,
  fetchReviewQueue,
  fetchSecondOpinions,
  postDisposition,
  requestSecondOpinion,
} from "../api";
import { RoleControl } from "../components/RoleControl";
import { useDemoRole } from "../demoRole";
import {
  DISPOSITION_LABELS,
  DISPOSITION_MEANINGS,
  FAMILY_LABELS,
  classificationLabel,
  classificationMeaning,
  gateStateLabel,
  humanizeKey,
} from "../format";
import { TechnicalBreakdown } from "../components/Help";
import { LightDot, VerdictLight } from "../components/TrafficLight";

const DISPOSITIONS = [
  "benign",
  "unresolved",
  "suspected",
  "demonstrated_transfer",
  "policy_supported",
];

// AI second opinion (CL-77): advisory only, beside the disposition.
export function SecondOpinionPanel({
  opinions,
  config,
  busy,
  onRequest,
}: {
  opinions: SecondOpinion[];
  config: SecondOpinionConfig | null;
  busy: boolean;
  onRequest: () => void;
}) {
  const latest = opinions[opinions.length - 1];
  return (
    <>
      <p className="note">
        Advisory only — does not change the verdict. You can ask a second,
        independent AI model to look at the check results and give its
        view. It never decides anything. (Any text that came from an agent
        is fenced off as untrusted before that model sees it.)
      </p>
      {config && !config.enabled && (
        <p className="note">
          Second opinion is off: no AI model has been connected on this
          server. Everything else on this page works normally.
        </p>
      )}
      {config?.enabled && (
        <p className="note">
          Model that will answer: {config.model ?? config.provider ?? "configured"}
          {config.per_run_cap != null
            ? ` · at most ${config.per_run_cap} opinion(s) per session`
            : ""}
        </p>
      )}
      <p>
        <button type="button" className="button" onClick={onRequest} disabled={busy}>
          Ask for a second opinion
        </button>
      </p>
      {latest?.status === "second_opinion_unavailable" && (
        <p className="note" role="status">
          Second opinion unavailable
          {latest.unavailable_reason ? `: ${latest.unavailable_reason}` : ""}.
          This is not an all-clear: no opinion was obtained, so judge from
          the check results yourself.
        </p>
      )}
      {latest?.status === "unparseable" && (
        <p className="note" role="status">
          Second opinion unparseable: the model’s reply wasn’t in the
          required format, so it was thrown away rather than guessed at. It
          wasn’t treated as agreement with anything. You can ask again, or
          judge unaided.
        </p>
      )}
      {latest?.status === "available" && latest.assessment && (
        <dl className="kv kv-wide">
          <div>
            <dt>The second model’s overall view</dt>
            <dd>{latest.assessment.assessment}</dd>
          </div>
          <div>
            <dt>Which model answered</dt>
            <dd>
              {latest.provider ?? "—"} / {latest.model ?? "—"}
            </dd>
          </div>
          <div>
            <dt>How sure it says it is (in its own words)</dt>
            <dd>{latest.assessment.confidence_note}</dd>
          </div>
        </dl>
      )}
      {latest?.assessment?.per_finding?.length ? (
        <>
          <p className="note">What it said about each check:</p>
          <ul className="tight">
            {latest.assessment.per_finding.map((row, i) => (
              <li key={i}>
                {FAMILY_LABELS[row.family] ?? row.family}: {row.comment}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

// Withheld deliveries of one run. Rows say whether a candidate decode
// exists, never what it says.
export function QueueTable({
  queue,
  selectedId,
  busy,
  onSelect,
}: {
  queue: ReviewQueue;
  selectedId: string | null;
  busy: boolean;
  onSelect: (deliveryId: string) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <caption>Images held back in session {queue.run_id}.</caption>
        <thead>
          <tr>
            <th>Image</th>
            <th>From → to</th>
            <th>Gate decision</th>
            <th>Possible hidden reading?</th>
            <th>Your judgement so far</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {queue.quarantined.map((d, i) => (
            <tr key={d.delivery_id} className={d.delivery_id === selectedId ? "row-active" : ""}>
              <td title={d.delivery_id}>Image {i + 1}</td>
              <td>{d.sender_id} → {d.recipient_id}</td>
              <td title={d.verdict ?? undefined}>
                <VerdictLight verdict={d.verdict} label={d.verdict ? undefined : "—"} />
              </td>
              <td>{d.has_candidate_decode ? "exists (reviewer only)" : "none"}</td>
              <td title={d.disposition}>{DISPOSITION_LABELS[d.disposition] ?? d.disposition}</td>
              <td>
                <button type="button" className="button" onClick={() => onSelect(d.delivery_id)} disabled={busy}>
                  Review this image
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Candidate decode: text only after a successful reviewer read.
export function CandidateDecodePanel({
  available,
  decode,
  note,
  role,
  busy,
  onRead,
}: {
  available: boolean;
  decode: CandidateDecode | null;
  note: string;
  role: string;
  busy: boolean;
  onRead: () => void;
}) {
  if (!available) return <p className="note">No possible reading exists for this image under any code declared in advance. That’s common, and on its own tells you little either way.</p>;
  return (
    <>
      <p className="note">
        A possible reading exists for this image. Only reviewers may see
        it, and every refusal is recorded. Treat it as a guess: it’s what
        the pattern <em>would</em> say <em>if</em> a particular code had
        been used, not a recovered message.
      </p>
      <p>
        <button type="button" className="button" onClick={onRead} disabled={busy}>
          Show the possible reading (you are acting as {role})
        </button>
      </p>
      {decode ? (
        <dl className="kv kv-wide">
          <div><dt>Code it was read with</dt><dd>{decode.code ?? "—"}</dd></div>
          <div><dt>Possible reading (hypothesis only)</dt><dd>{decode.text}</dd></div>
        </dl>
      ) : (
        note && <p className="note">{note}</p>
      )}
    </>
  );
}

export default function Review() {
  const [role, setRole] = useDemoRole();
  const [runId, setRunId] = useState("");
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [originalUrl, setOriginalUrl] = useState<string | null>(null);
  const [originalNote, setOriginalNote] = useState("");
  const [decode, setDecode] = useState<CandidateDecode | null>(null);
  const [decodeNote, setDecodeNote] = useState("");
  const [disposition, setDisposition] = useState("suspected");
  const [note, setNote] = useState("");
  const [basis, setBasis] = useState("");
  const [audit, setAudit] = useState<ReviewAudit | null>(null);
  const [opinions, setOpinions] = useState<SecondOpinion[]>([]);
  const [opinionConfig, setOpinionConfig] =
    useState<SecondOpinionConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLine, setStatusLine] = useState("");

  // The audit chain needs trace.read (researcher or reviewer, CL-78);
  // a viewer sees no audit panel.
  const refreshAudit = useCallback(
    async (id: string) => {
      if (!id.trim()) return;
      try {
        setAudit(await fetchReviewAudit(id.trim(), role));
      } catch {
        setAudit(null);
      }
    },
    [role],
  );

  const onLoad = async () => {
    if (!runId.trim()) {
      setError("Type the session name first. It’s the name from the delivery gate page, for example run_live_demo.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await fetchReviewQueue(runId.trim(), role);
      setQueue(next);
      setSelectedId(null);
      setDetail(null);
      setDecode(null);
      await refreshAudit(runId.trim());
      setStatusLine(
        next.quarantined.length === 0
          ? "No images are being held back in this session, so there’s nothing to review."
          : `${next.quarantined.length} held-back image${next.quarantined.length === 1 ? "" : "s"} waiting for your judgement. Press “Review this image” on one to begin.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That session couldn’t be loaded. What to do: check the session name and try again.");
    } finally {
      setBusy(false);
    }
  };

  const onSelect = async (deliveryId: string) => {
    setSelectedId(deliveryId);
    setDecode(null);
    setDecodeNote("");
    setOpinions([]);
    setBusy(true);
    setError(null);
    try {
      setDetail(await fetchReviewDetail(deliveryId, role));
      const stored = await fetchSecondOpinions(deliveryId, role).catch(
        () => null,
      );
      if (stored) {
        setOpinions(stored.opinions);
        setOpinionConfig(stored.config);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That image’s details couldn’t be loaded. What to do: try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  const onSecondOpinion = async () => {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const record = await requestSecondOpinion(selectedId, role);
      setOpinions((prev) => [...prev, record]);
      setStatusLine(
        record.status === "available"
          ? "Second opinion recorded below (advice only: it doesn’t change any decision)."
          : `No usable second opinion was obtained (${humanizeKey(record.status).toLowerCase()}). That is not an all-clear; judge from the check results.`,
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "The second opinion could not be obtained. What to do: judge from the check results, or try again later.",
      );
    } finally {
      setBusy(false);
      await refreshAudit(runId.trim());
    }
  };

  useEffect(() => {
    if (!selectedId) {
      setOriginalUrl(null);
      setOriginalNote("");
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setOriginalUrl(null);
    fetchReviewOriginal(selectedId, role)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setOriginalUrl(objectUrl);
        setOriginalNote("This is the original image, opened through the reviewers-only route. This opening has been recorded.");
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setOriginalNote(
            err instanceof ApiError
              ? `You’re not allowed to open the original as this role (the server refused with ${err.status}). What to do: pick Reviewer or Researcher in step 1. The refusal has been recorded.`
              : "The original couldn’t be opened just now. What to do: try again in a moment.",
          );
        }
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [selectedId, role]);

  const onDecode = async () => {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await fetchCandidateDecode(selectedId, role);
      setDecode(result);
      setDecodeNote("Shown to reviewers only. Read it with care: it’s a possible reading under one code declared in advance, a guess to test, not a recovered message and not proof that anything was sent.");
    } catch (err) {
      setDecode(null);
      setDecodeNote(
        err instanceof ApiError
          ? `Not allowed as a ${role} (the server refused with ${err.status}). Only reviewers may read this. What to do: pick Reviewer in step 1. This attempt has been recorded.`
          : "The possible reading couldn’t be fetched just now. What to do: try again in a moment.",
      );
    } finally {
      setBusy(false);
      await refreshAudit(runId.trim());
    }
  };

  const onDisposition = async () => {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      await postDisposition(selectedId, role, {
        disposition,
        note,
        demonstrated_basis: disposition === "demonstrated_transfer" ? basis : undefined,
      });
      setStatusLine(`Your judgement has been saved: “${DISPOSITION_LABELS[disposition] ?? disposition}”.`);
      const next = await fetchReviewQueue(runId.trim(), role);
      setQueue(next);
      setDetail(await fetchReviewDetail(selectedId, role));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Your judgement couldn’t be saved. What to do: pick Reviewer in step 1 (viewers can’t save judgements) and try again.");
    } finally {
      setBusy(false);
      await refreshAudit(runId.trim());
    }
  };

  const onExport = async () => {
    if (!runId.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await downloadReviewPackage(runId.trim(), role);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
      setStatusLine("Downloaded: a sealed file with this session’s evidence and your judgements. “Sealed” means any later change to the file can be detected.");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `${err.message} What to do: downloading the record needs the Researcher role. Pick it in step 1 and try again.`
          : "The download couldn’t be prepared. What to do: try again in a moment.",
      );
    } finally {
      setBusy(false);
      await refreshAudit(runId.trim());
    }
  };

  const findings = detail?.analysis?.findings ?? [];

  return (
    <>
      <h1>Review held-back images</h1>
      <p className="lede">
        When the gate holds an image back, the other agent never sees it.
        A person then decides what it really was. Load a session, look at
        each held-back image, and record what you think.
      </p>

      <section className="card step" aria-labelledby="review-role-heading">
        <h2 id="review-role-heading">Step 1 — Choose a session</h2>
        <RoleControl
          role={role}
          onChange={setRole}
          disabled={busy}
          hint="Demo role: pick Reviewer to open images and record judgements."
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
            Show held-back images
          </button>
        </p>
      </section>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && (
        <p className="alert" role="alert">{error}</p>
      )}

      {queue && (
        <section aria-labelledby="review-queue-heading">
          <h2 id="review-queue-heading">Step 2 — Pick an image</h2>
          {queue.quarantined.length === 0 ? (
            <p className="note">Nothing is being held back in this session, so there’s nothing to review. What to do: on the delivery gate page, send an image and choose “Hold the image back for review”, then come back.</p>
          ) : (
            <QueueTable queue={queue} selectedId={selectedId} busy={busy} onSelect={onSelect} />
          )}
        </section>
      )}

      {detail && (
        <div className="card-grid card-grid-2 card-grid-top">
          <section className="card" aria-labelledby="review-original-heading">
            <h2 id="review-original-heading">The held-back image</h2>
            {originalUrl ? (
              <>
                <img className="skyline-img" src={originalUrl} alt="The held-back original image, opened for your review" />
                <p className="note">{originalNote}</p>
              </>
            ) : (
              <p className="note">{originalNote || "Opening the original image…"}</p>
            )}
            <p>
              Gate decision:{" "}
              <span title={detail.verdict ?? undefined}>
                <VerdictLight verdict={detail.verdict} label={detail.verdict ? undefined : "none"} />
              </span>
            </p>
            <p>
              Your judgement so far:{" "}
              <strong title={detail.disposition}>{DISPOSITION_LABELS[detail.disposition] ?? detail.disposition}</strong>
            </p>
          </section>

          <section className="card step" aria-labelledby="review-decide-heading">
            <h2 id="review-decide-heading">Step 3 — Record your judgement</h2>
            <fieldset>
              <legend>What do you think this image is?</legend>
              <div className="choice-list choice-list-wide">
                {DISPOSITIONS.map((d) => (
                  <label key={d} className={disposition === d ? "choice choice-active" : "choice"} title={d}>
                    <input
                      type="radio"
                      name="disposition"
                      value={d}
                      checked={disposition === d}
                      onChange={() => setDisposition(d)}
                      disabled={busy}
                    />
                    <span>
                      <strong>{DISPOSITION_LABELS[d] ?? d}</strong>
                      <span className="choice-about">{DISPOSITION_MEANINGS[d]}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
            {disposition === "demonstrated_transfer" && (
              <label className="stacked-label">
                Required: what independent evidence shows the hidden message got through?
                <input type="text" value={basis} onChange={(e) => setBasis(e.target.value)} disabled={busy} />
                <span className="note">
                  For example, the other agent was seen recovering or acting on
                  the hidden content. A score on its own is never enough. Without
                  this, saving will be refused.
                </span>
              </label>
            )}
            <label className="stacked-label">
              Note for the record (optional)
              <input type="text" value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} />
            </label>
            <p>
              <button type="button" className="button button-primary" onClick={onDisposition} disabled={busy}>
                Save my judgement
              </button>{" "}
              <span className="note">Needs the Reviewer role. Saving doesn’t send the image to the other agent.</span>
            </p>

            <h3>Want a second opinion? (optional)</h3>
            <SecondOpinionPanel
              opinions={opinions}
              config={opinionConfig}
              busy={busy}
              onRequest={onSecondOpinion}
            />
          </section>
        </div>
      )}

      {audit && <AuditLine audit={audit} />}

      {queue && (
        <TechnicalBreakdown
          id="review-breakdown"
          note="check scores, the possible hidden reading, file fingerprint and the full access record"
        >
          {detail && (
            <>
              <h2>What the checks found (for the chosen image)</h2>
              {findings.length === 0 ? (
                <p className="note">No check results are recorded for this image, so judge from the image and its history alone. Treat “no results” as “not checked”, not “all clear”.</p>
              ) : (
                <ul className="tight">
                  {findings.map((f, i) => (
                    <li key={i}>
                      {FAMILY_LABELS[f.family] ?? f.family}: score{" "}
                      {f.score.toFixed(3)} out of 1 (checked by{" "}
                      {f.detector_name} version {f.detector_version})
                    </li>
                  ))}
                </ul>
              )}
              {detail.geometric?.classification && (
                <p className="note">
                  Shape-pattern result:{" "}
                  {classificationLabel(detail.geometric.classification)} (
                  {detail.geometric.signal_grade ?? "—"}).{" "}
                  {classificationMeaning(detail.geometric.classification)}
                </p>
              )}
              <dl className="kv kv-wide">
                <div><dt>Delivery ID</dt><dd>{detail.delivery_id}</dd></div>
                <div><dt>Where it stands now</dt><dd title={detail.state}>{gateStateLabel(detail.state)} ({detail.state})</dd></div>
                <div><dt>Gate decision (exact)</dt><dd>{detail.verdict ?? "—"}</dd></div>
                <div><dt>Your judgement (exact)</dt><dd>{detail.disposition}</dd></div>
                <div><dt>File fingerprint</dt><dd className="hash-line">{detail.content_hash}</dd></div>
              </dl>

              <h2>A possible reading of the pattern (reviewers only)</h2>
              <CandidateDecodePanel
                available={detail.has_candidate_decode}
                decode={decode}
                note={decodeNote}
                role={role}
                busy={busy}
                onRead={onDecode}
              />
            </>
          )}

          {audit && (
            <>
              <h2>Tamper-evident record of every access (audit chain)</h2>
              <p className="note">
                Every opening and every refusal in this session is added to a
                record whose entries are chained together with fingerprints,
                so editing or deleting an entry afterwards can be detected.
                Only researchers and reviewers can see it.
              </p>
              <dl className="kv kv-wide">
                <div>
                  <dt>Does the record check out as untampered?</dt>
                  <dd>{audit.chain_valid ? "yes" : "no — it appears to have been altered"}</dd>
                </div>
                <div><dt>Recorded entries in this session</dt><dd>{audit.entry_count}</dd></div>
                <div><dt>Attempts that were refused</dt><dd>{audit.denied}</dd></div>
                <div><dt>Latest entry’s fingerprint (head hash)</dt><dd className="hash-line">{audit.head_hash}</dd></div>
              </dl>
              {audit.entries.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <caption>Every recorded access in this session, oldest first, in the server’s exact terms (written out).</caption>
                    <thead>
                      <tr><th>Order</th><th>Who</th><th>What they tried to do</th><th>Allowed or refused</th></tr>
                    </thead>
                    <tbody>
                      {audit.entries.map((e, i) => (
                        <tr key={i}>
                          <td className="num">{String(e.seq ?? "")}</td>
                          <td>{String(e.actor_id ?? "")}</td>
                          <td title={String(e.action ?? "")}>{humanizeKey(String(e.action ?? ""))}</td>
                          <td title={String(e.outcome ?? "")}>{humanizeKey(String(e.outcome ?? ""))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          <h2>Keep a copy</h2>
          <p>
            <button type="button" className="button" onClick={onExport} disabled={busy || !runId.trim()}>
              Download the sealed evidence record
            </button>{" "}
            <span className="note">
              A file with this session’s evidence and judgements, for your
              records. Needs the Researcher role.
            </span>
          </p>
          <p className="note">
            Who can do what here: viewers can’t open originals or save
            judgements; only reviewers can read a possible hidden reading;
            downloading the record needs Researcher.
          </p>
        </TechnicalBreakdown>
      )}
    </>
  );
}

// The audit chain's verdict, as one plain line.
export function AuditLine({ audit }: { audit: ReviewAudit }) {
  return audit.chain_valid ? (
    <p className="safety-line" data-testid="audit-line" data-light="green">
      <LightDot light="green" />
      <span>
        <strong>Record check passed:</strong> this session’s access record
        hasn’t been tampered with ({audit.entry_count}{" "}
        {audit.entry_count === 1 ? "entry" : "entries"}, {audit.denied} refused).
      </span>
    </p>
  ) : (
    <p className="alert" role="alert" data-testid="audit-line">
      Warning: this session’s access record doesn’t check out. It may have
      been altered. Don’t rely on it, and tell whoever runs this server.
    </p>
  );
}
