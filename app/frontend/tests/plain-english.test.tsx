// CL-79: the UI must explain itself in plain English to a
// first-time reader. These tests pin the key newcomer-facing
// sentences so a later edit cannot silently restore bare jargon.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { DecisionPanel, FamilyCards } from "../src/components/Results";
import Landing from "../src/pages/Landing";
import { exampleLabel } from "../src/pages/Analyze";
import {
  classificationLabel,
  humanizeKey,
  verdictLabel,
  verdictMeaning,
} from "../src/format";
import type { AnalyzePayload, Decision } from "../src/types";

const perFamily = (verdict: string) => [
  {
    family: "spatial_lsb",
    max_score: 0.9,
    findings: 1,
    detectors: ["demo"],
    thresholds_status: "frozen",
    triage_flag_at: 0.2,
    enforcement_quarantine_at: 0.8,
    enforcement_fail_run_at: null,
    verdict,
  },
];

test("verdict words say what happens to the image", () => {
  assert.match(verdictLabel("log"), /Let it through/);
  assert.match(verdictLabel("flag"), /flag it for attention/);
  assert.match(verdictLabel("quarantine"), /Hold the image back for review/);
  assert.match(verdictLabel("fail_run"), /stop the session/);
  assert.match(verdictMeaning("quarantine"), /NOT delivered/);
  assert.match(verdictMeaning("log"), /is delivered/);
});

test("held-back decision panel leads with the plain outcome", () => {
  const decision: Decision = {
    verdict: "quarantine",
    delivery: "withhold",
    halt_execution: false,
    enforceable: true,
    equated_with_collusion: false,
    config_version: "frozen-test",
    ladder_version: "1",
    per_family: perFamily("quarantine"),
    findings_count: 1,
    families_without_findings: ["geometric"],
  };
  const html = renderToStaticMarkup(<DecisionPanel decision={decision} />);
  assert.match(html, /Would this image be delivered\?/);
  assert.match(html, /held back and the recipient would not see it/);
  assert.match(html, /Does this prove the sender was secretly communicating\?/);
  assert.match(html, /never proof on its own/);
  assert.match(html, /What to do next/);
  // Exact technical values remain available for specialists.
  assert.match(html, /frozen-test/);
  assert.match(html, /quarantine/);
});

test("family cards explain scores and the not-checked state", () => {
  const payload = {
    status: "parsed",
    analysis: {
      media_kind: "png",
      status: "parsed",
      findings: [
        {
          family: "spatial_lsb",
          detector_name: "demo-detector",
          detector_version: "1",
          score: 0,
          coverage: { pixels_checked: 100 },
          evidence: {},
          limitations: ["Only some PNG kinds are covered."],
        },
      ],
    },
    decision: null,
    geometric: null,
  } as unknown as AnalyzePayload;
  const html = renderToStaticMarkup(<FamilyCards payload={payload} />);
  assert.match(html, /Tiny pixel changes/);
  assert.match(html, /does not prove nothing is hidden/);
  assert.match(html, /What this check cannot tell you/);
  assert.match(html, /Not checked for this file/);
  assert.match(html, /different from “checked and all clear”/);
});

test("landing page explains the product and where to start", () => {
  const html = renderToStaticMarkup(<Landing navigate={() => undefined} />);
  assert.match(html, /AI agents sometimes send each other images/);
  assert.match(html, /How it works/);
  assert.match(html, /Check an image/);
  assert.match(html, /not proof/);
  assert.doesNotMatch(html, /verdict ladder decides/i);
});

test("ready-made examples are described, not named by machine id", () => {
  const label = exampleLabel({
    fixture_id: "geometric-height_position-encoded-98ae9c1bd36e",
    kind: "encoded",
    subfamily: "height_position",
    content_hash: "sha256:x",
    media_type: "image/png",
  });
  assert.match(label, /bar heights/);
  assert.match(label, /with hidden information/);
  assert.doesNotMatch(label, /^geometric-/);
});

test("raw field names and classifications are written out", () => {
  assert.match(humanizeKey("null_exceedance"), /shuffled/);
  assert.equal(humanizeKey("some_new_field"), "Some new field");
  assert.match(classificationLabel("no_signal"), /No pattern found/);
  assert.match(
    classificationLabel("quantized_without_structure"),
    /Regular spacing, but no deliberate pattern/,
  );
});
