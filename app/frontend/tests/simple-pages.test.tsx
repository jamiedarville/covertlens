// CL-79: every page leads with a plain summary or a few plain steps,
// and keeps the exact values one click away behind "See the technical
// breakdown" (or "Show advanced settings" for form options).
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { AdvancedSettings, TechnicalBreakdown } from "../src/components/Help";
import { DemoRoleView } from "../src/components/DemoRoleSelect";
import LiveGate, { GateSafetyLine } from "../src/pages/LiveGate";
import Review, { AuditLine } from "../src/pages/Review";
import Trace, { TimelineSummary, whatHappened } from "../src/pages/Trace";
import AgentDemo from "../src/pages/AgentDemo";
import Generate from "../src/pages/Generate";
import { AccuracySummary, type Reports } from "../src/pages/Benchmarks";
import { StandingsTable } from "../src/pages/Leaderboard";
import { ReleaseSummary, type Card } from "../src/pages/Scorecard";
import { NAV } from "../src/App";
import type { TraceDelivery, TraceView } from "../src/types";

const hiddenBlock = (html: string, id: string) => new RegExp(`id="${id}" hidden=""`).test(html);

test("the technical breakdown is a link that starts closed", () => {
  const closed = renderToStaticMarkup(
    <TechnicalBreakdown id="tb">
      <p>exact-value-0.123456</p>
    </TechnicalBreakdown>,
  );
  assert.match(closed, /aria-expanded="false"[^>]*>See the technical breakdown</);
  assert.ok(hiddenBlock(closed, "tb"), "breakdown should start hidden");
  const open = renderToStaticMarkup(
    <TechnicalBreakdown id="tb" initiallyOpen>
      <p>exact-value-0.123456</p>
    </TechnicalBreakdown>,
  );
  assert.match(open, /aria-expanded="true"[^>]*>Hide the technical breakdown</);
  assert.ok(!hiddenBlock(open, "tb"));
  const settings = renderToStaticMarkup(
    <AdvancedSettings id="adv">
      <p>seed</p>
    </AdvancedSettings>,
  );
  assert.match(settings, />Show advanced settings</);
  assert.ok(hiddenBlock(settings, "adv"));
});

test("the menu uses short names and every page has a title", () => {
  assert.deepEqual(
    NAV.map((n) => n.label),
    ["Two-agent demo", "Check an image", "Make a test image", "Delivery gate", "Review images", "Timeline", "Accuracy", "Leaderboard", "Release decision"],
  );
  for (const item of NAV) assert.ok(item.title.length > 0);
});

test("role picker names each role by what it can do", () => {
  const html = renderToStaticMarkup(
    <DemoRoleView
      roles={[
        { role: "viewer", actorId: "demo-viewer" },
        { role: "researcher", actorId: "demo-researcher" },
      ]}
      role="researcher"
      onChange={() => {}}
      enabled
      permissions={["verdict.override"]}
    />,
  );
  assert.match(html, /Who are you in this demo\?/);
  assert.match(html, /Researcher — can run the gate and make decisions/);
  assert.match(html, /Viewer — can only look/);
  assert.match(html, /verdict\.override/);
  assert.match(html, /<details/);
});

test("delivery gate shows four plain steps and hides the specialist settings", () => {
  const html = renderToStaticMarkup(<LiveGate />);
  for (const step of [
    "Step 1 — Start a session",
    "Step 2 — Send an image",
    "Step 4 — See what happened",
  ]) {
    assert.ok(html.includes(step), `missing ${step}`);
  }
  assert.match(html, /Start a new session/);
  assert.match(html, /Send it to the gate/);
  assert.ok(hiddenBlock(html, "gate-session-advanced"));
  assert.ok(hiddenBlock(html, "gate-send-advanced"));
});

test("the gate's audit is summed up as one safety line", () => {
  assert.match(renderToStaticMarkup(<GateSafetyLine unauthorized={0} />), /Safety check passed/);
  const bad = renderToStaticMarkup(<GateSafetyLine unauthorized={2} />);
  assert.match(bad, /role="alert"/);
  assert.match(bad, /given out without permission/);
});

test("review page is three plain steps; the audit chain is one line", () => {
  const html = renderToStaticMarkup(<Review />);
  assert.match(html, /Step 1 — Choose a session/);
  assert.match(html, /Show held-back images/);
  const ok = renderToStaticMarkup(
    <AuditLine audit={{ chain_valid: true, entry_count: 7, denied: 2, head_hash: "sha256:x", entries: [] }} />,
  );
  assert.match(ok, /Record check passed/);
  assert.match(ok, /7 entries, 2 refused/);
  const broken = renderToStaticMarkup(
    <AuditLine audit={{ chain_valid: false, entry_count: 7, denied: 2, head_hash: "sha256:x", entries: [] }} />,
  );
  assert.match(broken, /doesn’t check out/);
});

function traceDelivery(overrides: Partial<TraceDelivery>): TraceDelivery {
  return {
    delivery_id: "dlv_1",
    artifact_id: null,
    artifact_version_id: null,
    content_hash: "sha256:" + "0".repeat(64),
    episode_id: null,
    sender_id: "agent-a",
    recipient_id: "agent-b",
    verdict_reference_status: "linked",
    verdict: { verdict_id: "v1", verdict: "log" },
    delivered: true,
    parse: { linkage: "linked", parse_status: "parsed" },
    next_action: { linkage: "missing" },
    next_actions: [],
    findings_status: "linked",
    findings: [],
    missing: [],
    missing_reasons: [],
    ...overrides,
  };
}

test("the timeline says in one sentence what happened to each image", () => {
  assert.equal(
    whatHappened(traceDelivery({ delivered: false, verdict: { verdict_id: "v", verdict: "quarantine" } })),
    "Held back. The other agent never saw it.",
  );
  assert.match(
    whatHappened(traceDelivery({ delivered: false, verdict: { verdict_id: "v", verdict: "fail_run" } })),
    /session was stopped/,
  );
  const acted = whatHappened(
    traceDelivery({ next_actions: [{ linkage: "candidate", causation_claimed: false }] }),
  );
  assert.match(acted, /Delivered, and the other agent opened it\./);
  assert.match(acted, /only a possible link, not proof/);
  const view = {
    run_id: "run_1",
    deliveries: [
      traceDelivery({}),
      traceDelivery({ delivery_id: "dlv_2", delivered: false, verdict: { verdict_id: "v", verdict: "quarantine" } }),
    ],
    weak_signals: { band: { min_exclusive: 0, max_exclusive: 0.2 }, per_sender: [], repeated_senders: ["agent-a"], label: "x" },
  } as unknown as TraceView;
  const html = renderToStaticMarkup(<TimelineSummary view={view} />);
  assert.match(html, /<strong>2<\/strong> images sent/);
  assert.match(html, /<strong>1<\/strong> delivered/);
  assert.match(html, /Worth a look:<\/strong> agent-a/);
  assert.match(html, /light-dot-red/);
  assert.match(renderToStaticMarkup(<Trace />), /Show the timeline/);
});

test("make a test image offers four plain hiding places", () => {
  const html = renderToStaticMarkup(<Generate navigate={() => {}} />);
  for (const name of ["Shapes and patterns", "Tiny colour changes", "JPEG compression", "File details"]) {
    assert.ok(html.includes(name), `missing ${name}`);
  }
  assert.match(html, /Make the test image/);
  assert.ok(hiddenBlock(html, "generate-advanced"));
});

const reports = {
  frozen: {
    held_out: {
      families: {
        spatial_lsb: {
          recall_at_triage: { value: 0.95082, wilson95: { low: 0.86, high: 0.98 } },
          enforcement_precision: { value: 0.973684, wilson95: { low: 0.86, high: 0.99 } },
          recall_by_band: {},
        },
      },
    },
    tradeoffs: [],
  },
  geometric: {
    subfamilies: {
      height_position: {
        rows: {
          quantized_unstructured: { classifications: {}, false_structure_claims: { rate: 0, wilson_95: { low: 0, high: 0.1 } } },
          quantized_structured: { classifications: {}, structure_recall: { rate: 0.6, wilson_95: { low: 0.3, high: 0.8 } } },
        },
      },
      gap_timing: {
        rows: {
          quantized_structured: { classifications: {}, structure_recall: { rate: 0.8, wilson_95: { low: 0.5, high: 0.9 } } },
        },
      },
    },
  },
  latency: {
    classes: [
      { class: "small", media: "png", p95_s: 0.23, meets_proposal: true, statuses: {} },
      { class: "envelope", media: "png", p95_s: 10.3056, meets_proposal: false, statuses: {} },
    ],
    tradeoffs: [],
  },
} as unknown as Reports;

test("accuracy page answers in plain numbers out of 100", () => {
  const html = renderToStaticMarkup(<AccuracySummary reports={reports} />);
  assert.match(html, /Tiny colour changes/);
  assert.match(html, /Spotted <strong>95 out of 100<\/strong>/);
  assert.match(html, /right <strong>97 out of 100<\/strong> times/);
  assert.match(html, /<strong>60 to 80 out of 100<\/strong>/);
  assert.match(html, /Ordinary charts were never mistaken/);
  assert.match(html, /Small PNG images are checked within 2 seconds/);
  assert.match(html, /Very large PNG images take longer, up to 10\.3 seconds/);
  assert.doesNotMatch(html, /0\.95082|wilson|recall/i);
});

test("leaderboard names the hiding place in plain words", () => {
  const board = {
    pin_hash: "sha256:" + "a".repeat(64),
    entries: 1,
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
          verdict: "flag",
          family_score: 0.5,
          submitted_at: "2026-11-03T00:00:00Z",
        },
      ],
      quarantine: [],
      fail_run: [],
    },
  };
  const html = renderToStaticMarkup(<StandingsTable board={board} point="triage" />);
  assert.match(html, /Shapes and patterns: bar heights/);
  assert.match(html, /light-dot-orange/);
  assert.doesNotMatch(html, /0\.000732/);
});

test("release decision leads with a colour and a plain checklist", () => {
  const card: Card = {
    release: "CovertLens MVP",
    frozen_config_version: "frozen-1.4.0",
    targets: { recall: true, latency: false, exports: true },
    decision: {
      value: "release_with_limitations",
      rationale: ["recall: met"],
      limitations: ["one", "two"],
      target_revisions: [],
    },
    sections: {},
  };
  const html = renderToStaticMarkup(<ReleaseSummary card={card} />);
  assert.match(html, /data-light="orange"/);
  assert.match(html, /Released, with known limitations/);
  assert.match(html, /2 of 3 targets met/);
  assert.match(html, /Spots at least 95 out of 100 hidden messages in testing/);
  assert.match(html, /What it doesn’t do yet/);
  assert.match(html, /Checks 95 out of 100 images of every tested size within 2 seconds/);
  assert.match(html, /2 known limitations/);
});


test("two-agent demo offers a scene, a hidden message and three plain stages", () => {
  const html = renderToStaticMarkup(<AgentDemo />);
  assert.match(html, /1\. Sender agent/);
  assert.match(html, /2\. Check and decide/);
  assert.match(html, /3\. Receiver agent/);
  for (const scene of ["A house", "A garden", "A night sky", "A skyline"]) assert.ok(html.includes(scene));
  assert.match(html, /type="password"/);
  assert.match(html, /Show.*message/);
  assert.match(html, /Make the picture/);
  assert.match(html, /Make a picture first/);
  assert.match(html, /Waiting for you to send a picture/);
});
