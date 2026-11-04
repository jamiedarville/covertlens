// CL-79: the traffic-light result. A newcomer gets one plain answer
// (green, orange, red, or grey when nothing could be checked), one
// light per test, and the technical evidence only behind a link.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { SimpleResult, VerdictLight, testLights } from "../src/components/TrafficLight";
import { ResultView } from "../src/pages/Analyze";
import Landing from "../src/pages/Landing";
import { lightForVerdict } from "../src/format";
import type { AnalyzePayload, PerFamily } from "../src/types";
import structured from "./fixtures/analyze-structured.json";

function row(family: string, verdict: string, max_score: number, thresholds_status = "frozen"): PerFamily {
  return {
    family,
    max_score,
    findings: 1,
    detectors: ["demo@1"],
    thresholds_status,
    triage_flag_at: 0.381814,
    enforcement_quarantine_at: 0.696774,
    enforcement_fail_run_at: 0.987654,
    verdict,
  };
}

// A parsed PNG: the JPEG test never applies, the other three ran.
function pngPayload(verdict: string, rows: PerFamily[]): AnalyzePayload {
  return {
    status: "parsed",
    analysis: { media_kind: "png", status: "parsed", findings: [] },
    geometric: null,
    decision: {
      verdict,
      delivery: verdict === "quarantine" || verdict === "fail_run" ? "withhold" : "permit",
      halt_execution: verdict === "fail_run",
      enforceable: true,
      equated_with_collusion: false,
      config_version: "frozen-test",
      ladder_version: "1.0.0",
      per_family: rows,
      findings_count: rows.length,
      families_without_findings: ["jpeg_dct"],
    },
  };
}

const quiet = [row("spatial_lsb", "log", 0.000027), row("metadata", "log", 0), row("geometric", "log", 0)];

test("each ladder verdict maps to one colour; anything else is grey", () => {
  assert.equal(lightForVerdict("log"), "green");
  assert.equal(lightForVerdict("flag"), "orange");
  assert.equal(lightForVerdict("quarantine"), "red");
  assert.equal(lightForVerdict("fail_run"), "red");
  assert.equal(lightForVerdict(null), "grey");
  assert.equal(lightForVerdict("something_new"), "grey");
});

test("green says no evidence of collusion and names the skipped test", () => {
  const html = renderToStaticMarkup(<SimpleResult payload={pngPayload("log", quiet)} />);
  assert.match(html, /Is there a chance of collusion\?/);
  assert.match(html, /Green: No evidence of collusion/);
  assert.match(html, /None of our tests found a hidden message/);
  assert.match(html, /One test couldn’t run on this kind of image/);
  assert.match(html, /passed on to the agent it was sent to, as normal/);
  // The JPEG test is grey with a reason, never green.
  assert.match(html, /JPEG compression<\/p><p class="test-result"><strong>Grey — Not tested<\/strong>\. This test only works on JPEG photos, and this image is a PNG\./);
  assert.match(html, /Traffic light showing green/);
});

test("orange names the test and says a person should take a look", () => {
  const html = renderToStaticMarkup(
    <SimpleResult payload={pngPayload("flag", [quiet[0], quiet[1], row("geometric", "flag", 0.5)])} />,
  );
  assert.match(html, /Orange: Potential collusion/);
  assert.match(html, /The shapes and patterns test found something unusual/);
  assert.match(html, /a person should take a look/);
  assert.match(html, /still be passed on, but it’s marked/);
});

test("red says high potential for collusion and that the image is held back", () => {
  const html = renderToStaticMarkup(
    <SimpleResult
      payload={pngPayload("quarantine", [row("spatial_lsb", "quarantine", 0.36), quiet[1], row("geometric", "quarantine", 0.95)])}
    />,
  );
  assert.match(html, /Red: High potential for collusion/);
  assert.match(html, /The tiny colour changes and shapes and patterns tests found strong signs of a hidden message/);
  assert.match(html, /It would be held back/);
  const stopped = renderToStaticMarkup(
    <SimpleResult payload={pngPayload("fail_run", [quiet[0], quiet[1], row("geometric", "fail_run", 1)])} />,
  );
  assert.match(stopped, /Red: High potential for collusion/);
  assert.match(stopped, /AI session it came from would be stopped/);
});

test("the simple answer shows no scores, cut-offs or machine names", () => {
  const html = renderToStaticMarkup(
    <SimpleResult payload={pngPayload("flag", [quiet[0], quiet[1], row("geometric", "flag", 0.512345)])} />,
  );
  for (const raw of ["0.512345", "0.381814", "0.696774", "0.987654", "0.000027", "spatial_lsb", "geometric", "frozen-test", "flag", "out of 1"]) {
    assert.ok(!html.includes(raw), `simple view leaked ${raw}`);
  }
});

test("a test whose warning levels are not settled is grey, never green", () => {
  const lights = testLights(pngPayload("log", [quiet[0], quiet[1], row("geometric", "log", 0.9, "unfrozen_placeholder")]));
  const geometric = lights.find((t) => t.family === "geometric");
  assert.equal(geometric?.light, "grey");
  assert.match(geometric?.reason ?? "", /haven’t been settled/);
});

test("an image that could not be checked is grey with what to do next", () => {
  const html = renderToStaticMarkup(
    <SimpleResult payload={{ status: "oversized", detail: "too big", analysis: null, geometric: null, decision: null }} />,
  );
  assert.match(html, /Grey: Not checked/);
  assert.match(html, /too large to check safely/);
  assert.match(html, /What to do:/);
  assert.match(html, /Not checked doesn’t mean safe/);
  assert.match(html, /Traffic light with no lamp lit/);
  assert.doesNotMatch(html, /What each of the four tests found/);
  const nothingRan = renderToStaticMarkup(
    <SimpleResult
      payload={{ status: "parsed", analysis: { media_kind: "png", status: "parsed", findings: [] }, geometric: null, decision: null }}
    />,
  );
  assert.match(nothingRan, /Grey: Not checked/);
  assert.match(nothingRan, /None of our four tests could run/);
});

test("a real analysis: the shapes test is red and the JPEG test is grey", () => {
  const payload = structured as unknown as AnalyzePayload;
  const html = renderToStaticMarkup(<SimpleResult payload={payload} />);
  assert.match(html, /Red: High potential for collusion/);
  const lights = Object.fromEntries(testLights(payload).map((t) => [t.family, t.light]));
  assert.deepEqual(lights, { spatial_lsb: "green", jpeg_dct: "grey", metadata: "green", geometric: "red" });
});

test("technical evidence stays behind a link until it is opened", () => {
  const payload = structured as unknown as AnalyzePayload;
  const props = { payload, label: "scene.png", previewUrl: null, onToggleTechnical: () => {} };
  const closed = renderToStaticMarkup(<ResultView {...props} showTechnical={false} />);
  assert.match(closed, /Result for scene\.png/);
  assert.match(closed, /aria-expanded="false"[^>]*>See the technical evidence</);
  assert.doesNotMatch(closed, /Would this image be delivered\?/);
  assert.doesNotMatch(closed, /0\.95/);
  const open = renderToStaticMarkup(<ResultView {...props} showTechnical={true} />);
  assert.match(open, /aria-expanded="true"[^>]*>Hide the technical evidence</);
  assert.match(open, /Technical evidence \(for specialists\)/);
  assert.match(open, /Would this image be delivered\?/);
  assert.match(open, /0\.95/);
});

test("decision tables show the colour next to the plain label", () => {
  const html = renderToStaticMarkup(<VerdictLight verdict="quarantine" />);
  assert.match(html, /light-dot-red/);
  assert.match(html, /Red: /);
  assert.match(html, /Hold the image back for review/);
  assert.match(renderToStaticMarkup(<VerdictLight verdict={null} label="none yet" />), /light-dot-grey.*none yet/);
});

test("home page leads to the check, explains the colours and lists every page", () => {
  const html = renderToStaticMarkup(<Landing navigate={() => undefined} />);
  assert.match(html, /Check an image/);
  assert.match(html, /collusion/);
  assert.match(html, /What the colours mean/);
  assert.match(html, /warning signs, not proof/);
  for (const page of ["/generate", "/gate", "/review", "/trace", "/benchmarks", "/leaderboard", "/scorecard", "/docs"]) {
    assert.match(html, new RegExp(`href="${page}"`));
  }
});
