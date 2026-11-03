// Leaderboard of encoder strategies vs detector versions (CL-70).
// One board per CL-26 pin hash: a detector or freeze change starts a
// new board, and older boards stay readable under their own hash.
import { useEffect, useState } from "react";
import type { LeaderboardBoard, LeaderboardView, OperatingPoint } from "../api";
import { ApiError, fetchLeaderboard, fetchLeaderboardBoard } from "../api";

const POINT_LABEL: Record<OperatingPoint, string> = {
  triage: "Below triage (never flagged)",
  quarantine: "Below quarantine (delivered)",
  fail_run: "Below fail-run (run kept going)",
};

export function short(hash: string): string {
  return hash.startsWith("sha256:") ? `${hash.slice(7, 19)}…` : hash;
}

// Pure view, exported for server-side render tests.
export function StandingsTable({ board, point }: { board: LeaderboardBoard; point: OperatingPoint }) {
  const rows = board.standings[point] ?? [];
  if (rows.length === 0) {
    return <p className="note">No visible submissions stayed below this point yet.</p>;
  }
  return (
    <table className="data-table">
      <caption>{POINT_LABEL[point]}: ranked by payload carried</caption>
      <thead>
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Name</th>
          <th scope="col">Encoder</th>
          <th scope="col">Payload bits</th>
          <th scope="col">Bits per pixel</th>
          <th scope="col">Verdict</th>
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
            <td>{row.verdict}</td>
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
        setError(err instanceof ApiError ? err.message : "Could not load the leaderboard."),
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
        setError(err instanceof ApiError ? err.message : "That board could not be loaded."),
      );
  };

  return (
    <>
      <h1>Leaderboard</h1>
      <p>
        Encoders made on the Generate page, scored by this server under one
        pinned detector configuration. Each board is keyed by the release pin
        hash, so results are only compared against the same detectors and
        thresholds. A new detector version starts a new board; older boards
        stay here under their own hash.
      </p>
      {error && <p className="alert" role="alert">{error}</p>}
      {view && (
        <section className="card" aria-labelledby="pin-heading">
          <h2 id="pin-heading">Current configuration</h2>
          <dl className="kv kv-wide">
            <div><dt>Pin hash</dt><dd>{view.current.pin_hash}</dd></div>
            <div><dt>Thresholds</dt><dd>{view.current.threshold_config_version}</dd></div>
            <div><dt>Detectors</dt><dd>{view.current.detectors.join(", ")}</dd></div>
          </dl>
          {view.moderation && (
            <p className="note">New submissions appear after an operator approves them.</p>
          )}
          <label>
            Board{" "}
            <select value={selected} onChange={(e) => choose(e.target.value)}>
              <option value={view.current.pin_hash}>
                current ({short(view.current.pin_hash)})
              </option>
              {view.boards
                .filter((b) => !b.current)
                .map((b) => (
                  <option key={b.pin_hash} value={b.pin_hash}>
                    {short(b.pin_hash)} · {b.threshold_config_version} · {b.visible_entries} entries
                  </option>
                ))}
            </select>
          </label>
        </section>
      )}
      {board && (
        <section aria-labelledby="standings-heading">
          <h2 id="standings-heading">Standings</h2>
          <fieldset className="point-choice">
            <legend>Operating point</legend>
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
