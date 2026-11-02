import { test } from "node:test";
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";
import { BenchmarkResults, type Reports } from "../src/pages/Benchmarks";

const reports = {
  frozen: {
    held_out: {
      families: {
        frozen_family_marker: {
          recall_at_triage: {
            value: 0.123456,
            wilson95: { low: 0.012345, high: 0.987654 },
          },
          enforcement_precision: {
            value: 0.654321,
            wilson95: { low: 0.111111, high: 0.999999 },
          },
          recall_by_band: {
            high: {
              value: 0.123456,
              wilson95: { low: 0.012345, high: 0.987654 },
            },
          },
        },
      },
    },
    tradeoffs: ["Narrow measured coverage"],
  },
  robustness: {
    experiments: [
      {
        name: "adaptive_probe_marker",
        outcome: "evaded",
        attempts: { n: 6, at_triage: 6, withheld: 0 },
        controls: { n: 1, withheld: 0 },
      },
    ],
    coverage_limitations: ["Small adaptive probes"],
  },
  geometric: {
    subfamilies: {
      height: {
        rows: {
          continuous: {
            classifications: { no_signal: 5 },
            false_structure_claims: {
              rate: 0,
              wilson_95: { low: 0, high: 0.123456 },
            },
          },
          quantized_unstructured: {
            classifications: { quantized_without_structure: 5 },
            false_structure_claims: {
              rate: 0,
              wilson_95: { low: 0, high: 0.123456 },
            },
          },
          quantized_structured: {
            classifications: { structure_claimed: 5 },
            structure_recall: {
              rate: 1,
              wilson_95: { low: 0.876543, high: 1 },
            },
          },
        },
      },
    },
  },
  ablations: {
    arms: {
      image_only: {
        auc: 0.987654,
        recall: 0.654321,
        precision: 0.123456,
        false_positive_rate: 0.012345,
      },
    },
    findings: [],
  },
  latency: {
    classes: [
      {
        class: "large",
        media: "jpeg",
        p95_s: 10.3298,
        meets_proposal: false,
        statuses: { parsed: 5 },
      },
    ],
    tradeoffs: [],
  },
} as Reports;
const provenance = Object.fromEntries(
  ["frozen", "robustness", "geometric", "ablations", "latency"].map((name) => [
    name,
    {
      library_version: "test-library",
      config_version: "test-config",
      computed_at: "2026-11-02T00:00:00Z",
      source: "CLI handler",
    },
  ]),
);
const render = (initialView: string) =>
  renderToStaticMarkup(
    <BenchmarkResults
      reports={reports}
      provenance={provenance}
      initialView={initialView}
    />,
  );

test("frozen values keep exact decimals and exclude robustness experiments", () => {
  const html = render("frozen");
  assert.match(html, /0\.123456/);
  assert.match(html, /0\.012345/);
  assert.match(html, /frozen_family_marker/);
  assert.doesNotMatch(html, /adaptive_probe_marker/);
});
test("robustness chart and rows exclude frozen benchmark values", () => {
  const html = render("robustness");
  assert.match(html, /adaptive_probe_marker/);
  assert.match(html, /<svg/);
  assert.doesNotMatch(html, /frozen_family_marker/);
  assert.doesNotMatch(html, /0\.654321/);
});
for (const view of ["geometric", "ablations", "latency", "robustness"]) {
  test(`${view} shows library, configuration and compute date`, () => {
    const html = render(view);
    assert.match(html, /test-library/);
    assert.match(html, /test-config/);
    assert.match(html, /2026-11-02T00:00:00Z/);
  });
}
test("geometry renders all three scene rows and their Wilson intervals", () => {
  const html = render("geometric");
  for (const label of [
    "continuous",
    "quantized_unstructured",
    "quantized_structured",
    "0.876543",
  ])
    assert.ok(html.includes(label));
});
test("latency displays the measured miss without changing its value", () => {
  const html = render("latency");
  assert.match(html, /10\.3298/);
  assert.match(html, /false/);
});
