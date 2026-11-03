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
} from "../types";
import {
  ApiError,
  downloadReviewPackage,
  fetchCandidateDecode,
  fetchReviewAudit,
  fetchReviewDetail,
  fetchReviewOriginal,
  fetchReviewQueue,
  postDisposition,
} from "../api";
import { DemoRoleSelect } from "../components/DemoRoleSelect";
import { useDemoRole } from "../demoRole";

const DISPOSITIONS = [
  "benign",
  "unresolved",
  "suspected",
  "demonstrated_transfer",
  "policy_supported",
];

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
      setError("Enter a run ID from the Live Gate.");
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
          ? "No quarantined originals in this run."
          : `${next.quarantined.length} quarantined original(s) awaiting review.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the run.");
    } finally {
      setBusy(false);
    }
  };

  const onSelect = async (deliveryId: string) => {
    setSelectedId(deliveryId);
    setDecode(null);
    setDecodeNote("");
    setBusy(true);
    setError(null);
    try {
      setDetail(await fetchReviewDetail(deliveryId, role));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the delivery.");
    } finally {
      setBusy(false);
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
        setOriginalNote("Original served through the evidence gateway for this demo role.");
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setOriginalNote(
            err instanceof ApiError
              ? `Original withheld from this demo role (${err.status}). The denial is in the audit chain.`
              : "Original unavailable for this demo role.",
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
      setDecodeNote("Candidate decode shown to the reviewer only. It is a hypothesis under a declared code, not a recovered message.");
    } catch (err) {
      setDecode(null);
      setDecodeNote(
        err instanceof ApiError
          ? `Denied for the ${role} demo role (${err.status}). This attempt is recorded in the audit chain.`
          : "Decode unavailable.",
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
      setStatusLine(`Disposition recorded: ${disposition}.`);
      const next = await fetchReviewQueue(runId.trim(), role);
      setQueue(next);
      setDetail(await fetchReviewDetail(selectedId, role));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Disposition failed.");
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
      setStatusLine("Sealed review package downloaded.");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `${err.message} Export needs the researcher demo role.`
          : "Export failed.",
      );
    } finally {
      setBusy(false);
      await refreshAudit(runId.trim());
    }
  };

  const findings = detail?.analysis?.findings ?? [];

  return (
    <>
      <h1>Reviewer</h1>
      <p>
        Review quarantined originals from a Live Gate run, record a
        disposition for each, and download a sealed review package.
        Scores are evidence aids, never decoded messages and never
        proof of collusion.
      </p>

      <section className="card" aria-labelledby="review-role-heading">
        <h2 id="review-role-heading">Demo role</h2>
        <p className="note">
          Demo role — not authentication. The toggle chooses the
          evidence principal the API acts as; permissions come from
          the runtime policy and every read is audited.
        </p>
        <DemoRoleSelect role={role} onChange={setRole} disabled={busy} />
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
        <p>
          <button type="button" className="button button-primary" onClick={onLoad} disabled={busy}>
            Load quarantined originals
          </button>{" "}
          <button type="button" className="button" onClick={onExport} disabled={busy || !runId.trim()}>
            Download sealed review package
          </button>
        </p>
      </section>

      <p role="status" aria-live="polite" className="status-line">{statusLine}</p>
      {error && (
        <p className="alert" role="alert">{error}</p>
      )}

      {queue && (
        <section aria-labelledby="review-queue-heading">
          <h2 id="review-queue-heading">Quarantined originals</h2>
          {queue.quarantined.length === 0 ? (
            <p className="note">Nothing is withheld in this run. Quarantine a delivery on the Live Gate page first.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <caption>Withheld deliveries in run {queue.run_id}. Choose one to review.</caption>
                <thead>
                  <tr>
                    <th>Delivery</th>
                    <th>Sender → recipient</th>
                    <th>Verdict</th>
                    <th>Candidate decode</th>
                    <th>Disposition</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {queue.quarantined.map((d) => (
                    <tr key={d.delivery_id} className={d.delivery_id === selectedId ? "row-active" : ""}>
                      <td className="num">{d.delivery_id.slice(0, 18)}…</td>
                      <td>{d.sender_id} → {d.recipient_id}</td>
                      <td>{d.verdict ?? "—"}</td>
                      <td>{d.has_candidate_decode ? "available (reviewer only)" : "none"}</td>
                      <td>{d.disposition}</td>
                      <td>
                        <button type="button" className="button" onClick={() => onSelect(d.delivery_id)} disabled={busy}>
                          Review
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
            <h2 id="review-original-heading">Original</h2>
            {originalUrl ? (
              <>
                <img className="skyline-img" src={originalUrl} alt="Quarantined original opened for review" />
                <p className="note">{originalNote}</p>
              </>
            ) : (
              <p className="note">{originalNote || "Loading the original…"}</p>
            )}
            <dl className="kv kv-wide">
              <div><dt>State</dt><dd>{detail.state}</dd></div>
              <div><dt>Verdict</dt><dd>{detail.verdict ?? "—"}</dd></div>
              <div><dt>Content hash</dt><dd>{detail.content_hash}</dd></div>
              <div><dt>Disposition</dt><dd>{detail.disposition}</dd></div>
            </dl>
            <h3>Findings (evidence aids)</h3>
            {findings.length === 0 ? (
              <p className="note">No findings recorded for this original.</p>
            ) : (
              <ul className="tight">
                {findings.map((f, i) => (
                  <li key={i}>
                    {f.family} · {f.detector_name}@{f.detector_version} · score{" "}
                    {f.score.toFixed(3)}
                  </li>
                ))}
              </ul>
            )}
            {detail.geometric?.classification && (
              <p className="note">
                Geometric classification: {detail.geometric.classification} (
                {detail.geometric.signal_grade ?? "—"}). A classification
                is evidence, not a decoded message.
              </p>
            )}
          </section>

          <section className="card" aria-labelledby="review-decide-heading">
            <h2 id="review-decide-heading">Decode and disposition</h2>
            <h3>Candidate decode</h3>
            {detail.has_candidate_decode ? (
              <>
                <p className="note">
                  A candidate exists under a declared code. Only the
                  reviewer demo role may read its text; other roles
                  are denied and the denial is audited.
                </p>
                <p>
                  <button type="button" className="button" onClick={onDecode} disabled={busy}>
                    Read candidate decode as {role}
                  </button>
                </p>
                {decode ? (
                  <dl className="kv kv-wide">
                    <div><dt>Code</dt><dd>{decode.code ?? "—"}</dd></div>
                    <div><dt>Candidate text</dt><dd>{decode.text}</dd></div>
                  </dl>
                ) : (
                  decodeNote && <p className="note">{decodeNote}</p>
                )}
              </>
            ) : (
              <p className="note">No candidate decode for this original.</p>
            )}

            <h3>Disposition</h3>
            <div className="form-grid">
              <label>
                Disposition
                <select value={disposition} onChange={(e) => setDisposition(e.target.value)} disabled={busy}>
                  {DISPOSITIONS.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </label>
              <label>
                Note
                <input type="text" value={note} onChange={(e) => setNote(e.target.value)} disabled={busy} />
              </label>
            </div>
            {disposition === "demonstrated_transfer" && (
              <label>
                Demonstrated basis (independent recovery/action evidence)
                <input type="text" value={basis} onChange={(e) => setBasis(e.target.value)} disabled={busy} />
              </label>
            )}
            <p>
              <button type="button" className="button button-primary" onClick={onDisposition} disabled={busy}>
                Record disposition
              </button>
            </p>
            <p className="note">
              Viewer cannot record dispositions or read originals.
              Export needs the researcher role; candidate decodes need
              the reviewer role.
            </p>
          </section>
        </div>
      )}

      {audit && (
        <section aria-labelledby="review-audit-heading">
          <h2 id="review-audit-heading">Audit chain</h2>
          <dl className="kv kv-wide">
            <div>
              <dt>Chain verifies</dt>
              <dd>{audit.chain_valid ? "yes" : "no — tampered"}</dd>
            </div>
            <div><dt>Entries for this run</dt><dd>{audit.entry_count}</dd></div>
            <div><dt>Denied attempts</dt><dd>{audit.denied}</dd></div>
            <div><dt>Head hash</dt><dd>{audit.head_hash.slice(0, 24)}…</dd></div>
          </dl>
          {!audit.chain_valid && (
            <p className="alert" role="alert">Audit chain verification failed.</p>
          )}
          {audit.entries.length > 0 && (
            <div className="table-wrap">
              <table>
                <caption>Hash-chained evidence audit for this run, newest last.</caption>
                <thead>
                  <tr><th>Seq</th><th>Actor</th><th>Action</th><th>Outcome</th></tr>
                </thead>
                <tbody>
                  {audit.entries.map((e, i) => (
                    <tr key={i}>
                      <td className="num">{String(e.seq ?? "")}</td>
                      <td>{String(e.actor_id ?? "")}</td>
                      <td>{String(e.action ?? "")}</td>
                      <td>{String(e.outcome ?? "")}</td>
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
