// Leaderboard of encoder strategies vs detector versions (CL-70).
// One board per CL-26 pin hash: a detector or freeze change starts a
// new board, and older boards stay readable under their own hash.
import { useEffect, useState } from "react";
import type { LeaderboardBoard, LeaderboardView, OperatingPoint } from "../api";
import { ApiError, fetchLeaderboard, fetchLeaderboardBoard } from "../api";
import { hidingPlace } from "../format";
import { TechnicalBreakdown } from "../components/Help";
import { VerdictLight } from "../components/TrafficLight";

const POINT_LABEL: Record<OperatingPoint, string> = {
  triage: "Got past without even being flagged",
  quarantine: "Got past without being held back",
  fail_run: "Got past without stopping the session",
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
        No visible submissions got this far past the checker yet. Nobody
        may have entered, entries may be waiting for approval, or the
        checker caught everything at this level. To enter, make an image
        on “Make a test image” and use its leaderboard button.
      </p>
    );
  }
  return (
    <table className="data-table">
      <caption>{POINT_LABEL[point]}: ranked by how much hidden information got past.</caption>
      <thead>
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Name</th>
          <th scope="col">Where it was hidden</th>
          <th scope="col">Hidden information that got past (bits)</th>
          <th scope="col">What the gate decided</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.entry_id}>
            <td>{row.rank}</td>
            <td>{row.display_name ?? "anonymous"}</td>
            <td title={row.subfamily ? `${row.kind} / ${row.subfamily}` : row.kind}>
              {hidingPlace(row.kind, row.subfamily)}
            </td>
            <td>{row.payload_bits}</td>
            <td title={row.verdict}>
              <VerdictLight verdict={row.verdict} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Exact values for specialists: encoder names and packing density.
function StandingsDetail({ board, point }: { board: LeaderboardBoard; point: OperatingPoint }) {
  const rows = board.standings[point] ?? [];
  if (rows.length === 0) return <p className="note">No entries at this level.</p>;
  return (
    <table className="data-table">
      <caption>Exact values for “{POINT_LABEL[point].toLowerCase()}”.</caption>
      <thead>
        <tr>
          <th scope="col">Rank</th>
          <th scope="col">Entry ID</th>
          <th scope="col">Hiding method (exact)</th>
          <th scope="col">Bits</th>
          <th scope="col">Bits per pixel (how densely packed)</th>
          <th scope="col">Decision (exact)</th>
          <th scope="col">Submitted</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.entry_id}>
            <td>{row.rank}</td>
            <td className="num">{row.entry_id}</td>
            <td>{row.subfamily ? `${row.kind} / ${row.subfamily}` : row.kind}</td>
            <td>{row.payload_bits}</td>
            <td>{row.bits_per_pixel ?? "—"}</td>
            <td>{row.verdict}</td>
            <td>{row.submitted_at}</td>
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
      <h1>Leaderboard</h1>
      <p className="lede">
        People hide messages in test images and enter them here. CovertLens
        checks each entry again and ranks them by how much hidden
        information got past it. Every success shows the project a blind
        spot to fix.
      </p>
      {error && <p className="alert" role="alert">{error}</p>}
      {!view && !error && <p role="status">Loading the leaderboard…</p>}
      {board && (
        <section aria-labelledby="standings-heading">
          <h2 id="standings-heading">Standings</h2>
          <fieldset className="point-choice">
            <legend>Count an entry when it…</legend>
            {(view?.operating_points ?? ["triage", "quarantine", "fail_run"]).map((p) => (
              <label key={p}>
                <input
                  type="radio"
                  name="operating-point"
                  value={p}
                  checked={point === p}
                  onChange={() => setPoint(p)}
                />{" "}
                {POINT_LABEL[p].replace(/^Got/, "got")}
              </label>
            ))}
          </fieldset>
          <StandingsTable board={board} point={point} />
          {(board.standings[point] ?? []).length > 0 && (
            <p className="note">
              A “bit” is the smallest piece of information: about 8 bits
              make one letter. Want to take part? Make an image on “Make a
              test image” and enter it from there.
            </p>
          )}
        </section>
      )}
      {view && (
        <TechnicalBreakdown
          id="leaderboard-breakdown"
          note="checker versions, older boards and exact entry values"
        >
          <h2>Which version of the checker?</h2>
          <p className="note">
            Fair-play rule: entries are only compared against the same
            version of the checker. When the checker or its cut-offs
            change, a fresh board starts; older boards stay readable here,
            each labelled with that version’s fingerprint (its “pin hash”).
          </p>
          <dl className="kv kv-wide">
            <div><dt>Version fingerprint (pin hash)</dt><dd>{view.current.pin_hash}</dd></div>
            <div><dt>Cut-off settings version</dt><dd>{view.current.threshold_config_version}</dd></div>
            <div><dt>Checks included (detectors)</dt><dd>{view.current.detectors.join(", ")}</dd></div>
          </dl>
          {view.moderation && (
            <p className="note">New entries appear on the public board only after an operator approves them.</p>
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
          {board && (
            <>
              <h2>Exact entry values</h2>
              <StandingsDetail board={board} point={point} />
            </>
          )}
        </TechnicalBreakdown>
      )}
    </>
  );
}
