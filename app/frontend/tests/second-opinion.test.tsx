// CL-77: second-opinion panel states and key hygiene.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { SecondOpinionPanel } from "../src/pages/Review";

const base = {
  opinion_id: "sha256:" + "0".repeat(64),
  run_id: "run_1",
  delivery_id: "dlv_1",
  provider: "fake",
  model: "fake-model",
  image_sent: false,
  advisory_only: true as const,
};

test("panel says the feature is off with no key configured", () => {
  const html = renderToStaticMarkup(
    <SecondOpinionPanel
      opinions={[]}
      config={{ provider: null, model: null, enabled: false }}
      busy={false}
      onRequest={() => {}}
    />,
  );
  assert.match(html, /Second opinion is off/);
  assert.match(html, /Advisory only/);
  assert.doesNotMatch(html, /sk-/);
});

test("panel shows unavailable and unparseable explicitly", () => {
  const unavailable = renderToStaticMarkup(
    <SecondOpinionPanel
      opinions={[
        { ...base, status: "second_opinion_unavailable", unavailable_reason: "per_run_cap_reached", assessment: null },
      ]}
      config={{ provider: "fake", model: "fake-model", enabled: true, per_run_cap: 20 }}
      busy={false}
      onRequest={() => {}}
    />,
  );
  assert.match(unavailable, /unavailable/);
  assert.match(unavailable, /per_run_cap_reached/);
  assert.match(unavailable, /not an all-clear/);
  const unparseable = renderToStaticMarkup(
    <SecondOpinionPanel
      opinions={[
        { ...base, status: "unparseable", unavailable_reason: "unparseable_response", assessment: null },
      ]}
      config={{ provider: "fake", model: "fake-model", enabled: true }}
      busy={false}
      onRequest={() => {}}
    />,
  );
  assert.match(unparseable, /unparseable/);
});

test("panel shows a structured assessment beside the disposition", () => {
  const html = renderToStaticMarkup(
    <SecondOpinionPanel
      opinions={[
        {
          ...base,
          status: "available",
          unavailable_reason: null,
          assessment: {
            assessment: "suspicious",
            per_finding: [{ family: "geometric", comment: "structured heights" }],
            confidence_note: "moderate",
          },
        },
      ]}
      config={{ provider: "fake", model: "fake-model", enabled: true }}
      busy={false}
      onRequest={() => {}}
    />,
  );
  assert.match(html, /suspicious/);
  assert.match(html, /structured heights/);
  assert.match(html, /does not change the verdict/);
});
