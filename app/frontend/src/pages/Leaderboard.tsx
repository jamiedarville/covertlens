// Leaderboard of encoder strategies vs detector versions (CL-70).
// One board per CL-26 pin hash: a detector or freeze change starts a
// new board, and older boards stay readable under their own hash.
import { useEffect, useState } from "react";
import type { LeaderboardBoard, LeaderboardView, OperatingPoint } from "../api";
import { ApiError, fetchLeaderboard, fetchLeaderboardBoard } from "../api";
import { verdictLabel } from "../format";
import { TechDetails } from "../components/Help";

const POINT_LABEL: Record<OperatingPoint, string> = {
  triage: "Slipped past without even being flagged for attention",
  quarantine: "Not held back (delivered, even if flagged)",
  fail_run: "Did not stop the session (delivered or merely held back)",
};

export function short(hash: string): string {
  return hash.startsWith("sha256:") ? `${hash.slice(7, 19)}…` : hash;
}

// Pure view, exported for server-side render tests.
export function StandingsTable({ board, point }: { board: LeaderboardBoard; point: OperatingPoint }) {
  const rows = board.standings[point] ?? [];
  if (rows.length === 0) {
    return (
      <p className="note">
        No visible submissions got this far past the checker yet. That
        can mean nobody has entered, entries are waiting for approval,
        or the checker caught everything at this strictness. To enter,
        make a picture on “Make a test image” and choose its leaderboard
        button.
      </p>
    );
  }
  return (
    <table className="data-table">
      <caption>
        {POINT_LABEL[point]} — ranked by how much hidden information each
        picture carried (more is a “better” smuggle). “Bits per pixel”
        says how densely it was packed.
      </caption>
      <thead>
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Name</th>
          <th scope="col">Hiding method used</th>
          <th scope="col">Hidden information carried (bits)</th>
          <th scope="col">Bits per pixel (how densely packed)</th>
          <th scope="col">What the gate decided</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.entry_id}>
            <td>{row.rank}</td>
            <td>{row.display_name ?? "anonymous"}</td>
            <td>{row.subfamily ? `${row.kind} / ${row.subfamily}` : row.kind}</td>
            <td>{row.payload_bits}</td>
            <td>{row.bits_per_pixel ?? "—"}</td>
            <td title={row.verdict}>{verdictLabel(row.verdict)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Leaderboard() {
  const [view, setView] = useState<LeaderboardView | null>(null);
  const [board, setBoard] = useState<LeaderboardBoard | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [point, setPoint] = useState<OperatingPoint>("triage");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchLeaderboard()
      .then((next) => {
        setView(next);
        setBoard(next.board);
        setSelected(next.current.pin_hash);
      })
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "The leaderboard could not be loaded. What to do: reload this page to try again."),
      );
  }, []);

  const choose = (pinHash: string) => {
    setSelected(pinHash);
    if (view && pinHash === view.current.pin_hash) {
      setBoard(view.board);
      return;
    }
    fetchLeaderboardBoard(pinHash)
      .then(setBoard)
      .catch((err: unknown) =>
        setError(err instanceof ApiError ? err.message : "That older leaderboard could not be loaded. What to do: choose the current board, or reload the page."),
      );
  };

  return (
    <>
      <h1>Leaderboard: who smuggled the most past the checker?</h1>
      <p>
        People use “Make a test image” to hide information in a picture,
        then enter it here. The server re-checks the exact saved picture
        (so nobody can swap in a different one) and ranks entries by how
        much hidden information got past each decision cut-off. Doing
        well here is useful, not naughty: every successful smuggle shows
        the project a blind spot to fix.
      </p>
      <p className="note">
        Fair-play rule: entries are only compared against the{" "}
        <em>same version</em> of the checker. When the checker or its
        cut-offs change, a fresh board starts; older boards stay readable
        below, each labelled with that version’s fingerprint (its “pin
        hash”).
      </p>
      {error && <p className="alert" role="alert">{error}</p>}
      {!view && !error && (
        <p role="status">Loading the leaderboard…</p>
      )}
      {view && (
        <section className="card" aria-labelledby="pin-heading">
          <h2 id="pin-heading">Which version of the checker?</h2>
          <p className="note">
            Rankings below were all produced by the checker version named
            here. Use the list to look at boards from older versions.
          </p>
          <TechDetails summary="Exact version fingerprints">
            <dl className="kv kv-wide">
              <div><dt>Version fingerprint (pin hash)</dt><dd>{view.current.pin_hash}</dd></div>
              <div><dt>Cut-off settings version</dt><dd>{view.current.threshold_config_version}</dd></div>
              <div><dt>Checks included (detectors)</dt><dd>{view.current.detectors.join(", ")}</dd></div>
            </dl>
          </TechDetails>
          {view.moderation && (
            <p className="note">New entries appear on the public board only after an operator approves them, so yours may not show immediately.</p>
          )}
          <label>
            Board to view{" "}
            <select value={selected} onChange={(e) => choose(e.target.value)}>
              <option value={view.current.pin_hash}>
                current checker ({short(view.current.pin_hash)})
              </option>
              {view.boards
                .filter((b) => !b.current)
                .map((b) => (
                  <option key={b.pin_hash} value={b.pin_hash}>
                    older checker {short(b.pin_hash)} · settings {b.threshold_config_version} · {b.visible_entries} entries
                  </option>
                ))}
            </select>
          </label>
        </section>
      )}
      {board && (
        <section aria-labelledby="standings-heading">
          <h2 id="standings-heading">Standings</h2>
          <p className="note">
            First choose how strict the gate must be for an entry to
            count as “got past”. The first choice is the hardest to
            achieve.
          </p>
          <fieldset className="point-choice">
            <legend>How strict must the gate be?</legend>
            {(view?.operating_points ?? ["triage", "quarantine", "fail_run"]).map((p) => (
              <label key={p}>
                <input
                  type="radio"
                  name="operating-point"
                  value={p}
                  checked={point === p}
                  onChange={() => setPoint(p)}
                />{" "}
                {POINT_LABEL[p]}
              </label>
            ))}
          </fieldset>
          <StandingsTable board={board} point={point} />
        </section>
      )}
    </>
  );
}
