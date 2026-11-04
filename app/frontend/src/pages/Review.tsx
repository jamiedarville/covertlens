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
  verdictLabel,
} from "../format";
import { StartSteps, TechDetails } from "../components/Help";

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
        independent AI model to read the check results for this picture
        and give its view. Its answer is shown next to yours to help you
        judge; it never decides anything by itself. (For safety, any text
        that came from an agent is clearly fenced off as untrusted when
        shown to that model.)
      </p>
      {config && !config.enabled && (
        <p className="note">
          Second opinion is off: whoever runs this server has not
          connected an AI model for it (no provider key is configured).
          The rest of this page works normally — you review unaided.
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
        <button
          type="button"
          className="button"
          onClick={onRequest}
          disabled={busy}
        >
          Ask for a second opinion on this picture
        </button>
      </p>
      {latest?.status === "second_opinion_unavailable" && (
        <p className="note" role="status">
          Second opinion unavailable
          {latest.unavailable_reason
            ? `: ${latest.unavailable_reason}`
            : ""}
          . This is not an all-clear — it only means no opinion was
          obtained. Judge the picture from the check results yourself.
        </p>
      )}
      {latest?.status === "unparseable" && (
        <p className="note" role="status">
          Second opinion unparseable: the model’s reply did not follow
          the required format, so it was thrown away rather than guessed
          at. It was not treated as agreement with anything. You may ask
          again, or judge unaided.
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
      setError("Type the session name first. It is the name you chose on the delivery gate page, for example run_live_demo. Held-back pictures only exist after the gate has held one back in that session.");
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
          ? "No pictures are being held back in this session, so there is nothing to review here."
          : `${next.quarantined.length} held-back picture(s) waiting for your judgement. Choose “Review this picture” on one to begin.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That session could not be loaded. What to do: check the session name and try again.");
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
      setError(err instanceof ApiError ? err.message : "That picture’s details could not be loaded. What to do: try again in a moment.");
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
          ? "Second opinion recorded below (advice only — it does not change any decision)."
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
        setOriginalNote("This is the original picture, opened for you through the reviewers-only path. This opening has been written into the audit record at the bottom.");
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setOriginalNote(
            err instanceof ApiError
              ? `You are not allowed to open the original as this kind of user (the server refused with ${err.status}). What to do: pretend to be a researcher or reviewer above. The refusal itself has been written into the audit record.`
              : "The original picture could not be opened just now. What to do: try again in a moment.",
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
      setDecodeNote("Shown to reviewers only. Read it with care: this is a possible reading under one code declared in advance — a hypothesis to test, not a recovered message, and not proof that anything was sent.");
    } catch (err) {
      setDecode(null);
      setDecodeNote(
        err instanceof ApiError
          ? `Not allowed while pretending to be a ${role} (the server refused with ${err.status}). Only the reviewer kind of user may read this. What to do: change the kind of user above. This attempt has been written into the audit record.`
          : "The possible reading could not be obtained just now. What to do: try again in a moment.",
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
      setStatusLine(`Your judgement has been saved: “${DISPOSITION_LABELS[disposition] ?? disposition}”. It now appears in the table above and in any exported record.`);
      const next = await fetchReviewQueue(runId.trim(), role);
      setQueue(next);
      setDetail(await fetchReviewDetail(selectedId, role));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Your judgement could not be saved. What to do: check your kind of user above (viewer cannot save judgements) and try again.");
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
      setStatusLine("Downloaded: a sealed file containing this session’s evidence and your judgements, for keeping or handing to another researcher. “Sealed” means any later change to the file can be detected.");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `${err.message} What to do: downloading the record needs the researcher kind of user — change it above and try again.`
          : "The download could not be prepared. What to do: try again in a moment.",
      );
    } finally {
      setBusy(false);
      await refreshAudit(runId.trim());
    }
  };

  const findings = detail?.analysis?.findings ?? [];

  return (
    <>
      <h1>Review pictures that were held back</h1>
      <p>
        When the delivery gate holds a picture back (“quarantines” it),
        the recipient never sees it — but a person must still judge
        whether holding it back was right. That is your job on this page:
        open each held-back original, look at what the checks found, and
        record your judgement. The scores help you judge; they are never
        a decoded message and never proof that anyone secretly
        communicated.
      </p>
      <StartSteps heading="How reviewing works">
        <li>Pick the kind of user you are acting as, and type the session name from the delivery gate page.</li>
        <li>Load the held-back pictures and open one. You will see the original picture and the check results for it.</li>
        <li>Record your judgement for that picture (for example “looks harmless” or “suspicious, but not proven”). Optionally ask a second AI model for its view first.</li>
        <li>If you need a copy for your records, download the sealed evidence file for the session.</li>
      </StartSteps>

      <section className="card" aria-labelledby="review-role-heading">
        <h2 id="review-role-heading">Who are you acting as, and which session?</h2>
        <p className="note">
          This picker is a Demo role control: for the demonstration you
          choose the kind of user. It is not a real sign-in, and anyone
          can pick any kind. What each kind may
          do is set by the server, and everything opened is written into
          the audit record at the bottom of this page, including refusals.
          Try acting as a viewer first to see a refusal happen.
        </p>
        <RoleControl role={role} onChange={setRole} disabled={busy} />
        <div className="form-grid">
          <label>
            Session name (run ID)
            <input
              type="text"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              placeholder="run_live_demo"
            />
            <span className="note">The exact name used on the delivery gate page. Nothing to review yet? Hold a picture back there first (decision: “Hold the image back for review”).</span>
          </label>
        </div>
        <p>
          <button type="button" className="button button-primary" onClick={onLoad} disabled={busy}>
            Show held-back pictures in this session
          </button>{" "}
          <button type="button" className="button" onClick={onExport} disabled={busy || !runId.trim()}>
            Download the sealed evidence record for this session
          </button>
          {!runId.trim() && (
            <span className="note"> Type the session name first to enable the download. Downloading needs the researcher kind of user.</span>
          )}
        </p>
      </section>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && (
        <p className="alert" role="alert">{error}</p>
      )}

      {queue && (
        <section aria-labelledby="review-queue-heading">
          <h2 id="review-queue-heading">Pictures waiting for your judgement</h2>
          {queue.quarantined.length === 0 ? (
            <p className="note">Nothing is being held back in this session, so there is nothing to review. What to do: on the delivery gate page, send a picture and apply the decision “Hold the image back for review”, then come back here.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <caption>Held-back pictures in session {queue.run_id}. “Possible reading” means a reviewer may ask what the pattern would say under a code declared in advance — a hypothesis, not a recovered message.</caption>
                <thead>
                  <tr>
                    <th>Picture (short ID)</th>
                    <th>Sender → recipient</th>
                    <th>Gate decision</th>
                    <th>Possible reading of the pattern?</th>
                    <th>Your judgement so far</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {queue.quarantined.map((d) => (
                    <tr key={d.delivery_id} className={d.delivery_id === selectedId ? "row-active" : ""}>
                      <td className="num">{d.delivery_id.slice(0, 18)}…</td>
                      <td>{d.sender_id} → {d.recipient_id}</td>
                      <td title={d.verdict ?? undefined}>{d.verdict ? verdictLabel(d.verdict) : "—"}</td>
                      <td>{d.has_candidate_decode ? "exists (reviewer only)" : "none"}</td>
                      <td title={d.disposition}>{DISPOSITION_LABELS[d.disposition] ?? d.disposition}</td>
                      <td>
                        <button type="button" className="button" onClick={() => onSelect(d.delivery_id)} disabled={busy}>
                          Review this picture
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {detail && (
        <div className="card-grid card-grid-2">
          <section className="card" aria-labelledby="review-original-heading">
            <h2 id="review-original-heading">The original picture</h2>
            {originalUrl ? (
              <>
                <img className="skyline-img" src={originalUrl} alt="The held-back original picture, opened for your review" />
                <p className="note">{originalNote}</p>
              </>
            ) : (
              <p className="note">{originalNote || "Opening the original picture…"}</p>
            )}
            <dl className="kv kv-wide">
              <div><dt>Where it stands now</dt><dd title={detail.state}>{gateStateLabel(detail.state)}</dd></div>
              <div><dt>Gate decision</dt><dd title={detail.verdict ?? undefined}>{detail.verdict ? verdictLabel(detail.verdict) : "—"}</dd></div>
              <div><dt>Your judgement so far</dt><dd title={detail.disposition}>{DISPOSITION_LABELS[detail.disposition] ?? detail.disposition}</dd></div>
            </dl>
            <TechDetails summary="File fingerprint (for matching this exact file later)">
              <p className="note hash-line">{detail.content_hash}</p>
            </TechDetails>
            <h3>What the checks found (evidence to help you judge)</h3>
            {findings.length === 0 ? (
              <p className="note">No check results are recorded for this picture, so judge from the picture and its history alone — and treat “no results” as “not checked”, not “all clear”.</p>
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
          </section>

          <section className="card" aria-labelledby="review-decide-heading">
            <h2 id="review-decide-heading">A possible reading, and your judgement</h2>
            <h3>What would the pattern say, under a code declared in advance? (candidate decode)</h3>
            {detail.has_candidate_decode ? (
              <>
                <p className="note">
                  For this picture, a possible reading exists. Only the
                  reviewer kind of user may read it; everyone else is
                  refused, and refusals are written into the audit record.
                  Even as a reviewer, treat it strictly as a hypothesis:
                  it is what the pattern <em>would</em> say <em>if</em>{" "}
                  that code had been used. It is not a recovered message.
                </p>
                <p>
                  <button type="button" className="button" onClick={onDecode} disabled={busy}>
                    Show the possible reading (you are acting as {role})
                  </button>
                </p>
                {decode ? (
                  <dl className="kv kv-wide">
                    <div><dt>Code it was read with</dt><dd>{decode.code ?? "—"}</dd></div>
                    <div><dt>Possible reading (hypothesis only)</dt><dd>{decode.text}</dd></div>
                  </dl>
                ) : (
                  decodeNote && <p className="note">{decodeNote}</p>
                )}
              </>
            ) : (
              <p className="note">No possible reading exists for this picture under any code declared in advance. That is common and, by itself, tells you little either way.</p>
            )}

            <h3>Your judgement (called a “disposition”)</h3>
            <p className="note">
              Choose how this picture should be recorded. Your choice is
              saved with your name and appears in the session’s records.
              It does not re-deliver the picture to the recipient.
            </p>
            <div className="form-grid">
              <label>
                Your judgement
                <select value={disposition} onChange={(e) => setDisposition(e.target.value)} disabled={busy}>
                  {DISPOSITIONS.map((d) => (
                    <option key={d} value={d}>{DISPOSITION_LABELS[d] ?? d}</option>
                  ))}
                </select>
                <span className="note">{DISPOSITION_MEANINGS[disposition]}</span>
              </label>
              <label>
                Note for the record (optional)
                <input type="text" value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} />
              </label>
            </div>
            {disposition === "demonstrated_transfer" && (
              <label>
                Required: what is your independent evidence that hidden information actually got through?
                <input type="text" value={basis} onChange={(e) => setBasis(e.target.value)} disabled={busy} />
                <span className="note">
                  For example: the recipient was independently observed
                  recovering or acting on the hidden content. A score on
                  its own can never be enough for this judgement. Without
                  this explanation, saving will be refused.
                </span>
              </label>
            )}
            <p>
              <button type="button" className="button button-primary" onClick={onDisposition} disabled={busy}>
                Save my judgement for this picture
              </button>
            </p>
            <p className="note">
              Who can do what on this page: a viewer cannot save
              judgements or open originals. Downloading the sealed record
              needs researcher. Reading a possible reading needs reviewer.
            </p>

            <h3>Second opinion from another AI model (optional)</h3>
            <SecondOpinionPanel
              opinions={opinions}
              config={opinionConfig}
              busy={busy}
              onRequest={onSecondOpinion}
            />
          </section>
        </div>
      )}

      {audit && (
        <section aria-labelledby="review-audit-heading">
          <h2 id="review-audit-heading">Tamper-evident record of every access (audit chain)</h2>
          <p className="note">
            Every opening and every refusal in this session is appended to
            a record whose entries are chained together with fingerprints,
            so editing or deleting an entry afterwards can be detected.
            This record is only shown to researcher and reviewer kinds of
            user; if you cannot see it, that is why.
          </p>
          <dl className="kv kv-wide">
            <div>
              <dt>Does the record check out as untampered?</dt>
              <dd>{audit.chain_valid ? "yes" : "no — it appears to have been altered"}</dd>
            </div>
            <div><dt>Recorded entries in this session</dt><dd>{audit.entry_count}</dd></div>
            <div><dt>Attempts that were refused</dt><dd>{audit.denied}</dd></div>
          </dl>
          <TechDetails summary="Latest entry’s fingerprint (head hash)">
            <p className="note hash-line">{audit.head_hash}</p>
          </TechDetails>
          {!audit.chain_valid && (
            <p className="alert" role="alert">
              Warning: this audit record does not check out — it may have
              been altered. Do not rely on it, and tell whoever runs this
              server.
            </p>
          )}
          {audit.entries.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption>Every recorded access in this session, oldest first. Action and outcome names are the server’s exact terms, written out; the outcome tells you whether the attempt was allowed or refused.</caption>
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
        </section>
      )}
    </>
  );
}
