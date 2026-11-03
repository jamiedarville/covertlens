// CL-70: leaderboard standings render and submissions send only the
// artifact id and a display name (the server scores the bytes).
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { StandingsTable, short } from "../src/pages/Leaderboard";
import { submitToLeaderboard } from "../src/api";

const board = {
  pin_hash: "sha256:" + "a".repeat(64),
  entries: 2,
  pending: 0,
  standings: {
    triage: [
      {
        rank: 1,
        entry_id: "lb_1",
        display_name: "team one",
        kind: "geometric",
        subfamily: "height_position",
        payload_bits: 36,
        bits_per_pixel: 0.000732,
        verdict: "log",
        family_score: 0.1,
        submitted_at: "2026-11-03T00:00:00Z",
      },
    ],
    quarantine: [],
    fail_run: [],
  },
};

test("standings list rank, name, encoder and payload", () => {
  const html = renderToStaticMarkup(<StandingsTable board={board} point="triage" />);
  assert.match(html, /team one/);
  assert.match(html, /geometric \/ height_position/);
  assert.match(html, /<td>36<\/td>/);
  const empty = renderToStaticMarkup(<StandingsTable board={board} point="quarantine" />);
  assert.match(empty, /No visible submissions/);
  assert.equal(short(board.pin_hash), "aaaaaaaaaaaa…");
});

test("a submission posts only the artifact id and name", async () => {
  const calls: { url: string; init?: RequestInit }[] = [];
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return new Response(
      JSON.stringify({ entry_id: "lb_1", status: "visible", pin_hash: "x", outcome: { verdict: "log", evades: {}, payload: { bits: 64 } } }),
      { status: 201, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;
  const entry = await submitToLeaderboard("ver_1", "team one");
  assert.equal(entry.entry_id, "lb_1");
  assert.equal(calls[0].url, "/api/leaderboard/submissions");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    artifact_version_id: "ver_1",
    display_name: "team one",
  });
});

test("duplicate and sign-in errors are explained", async () => {
  for (const [status, pattern] of [
    [409, /already on the current board/],
    [401, /Sign in/],
  ] as const) {
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ detail: "x" }), { status })) as typeof fetch;
    await assert.rejects(submitToLeaderboard("v", "n"), pattern);
  }
});
