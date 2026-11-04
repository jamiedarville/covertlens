// Traffic-light result (CL-79): the plain answer shown before any
// score. Every colour comes from the verdicts already in the
// /api/analyze response (decision.verdict and decision.per_family,
// decided by the frozen ladder); nothing here computes or compares a
// score. Colour is never the only signal: each light also carries a
// symbol and its colour name in words.

import type { AnalyzePayload } from "../types";
import {
  LIGHT_HEADLINE,
  LIGHT_MEANING,
  LIGHT_NAME,
  TEST_ABOUT,
  TEST_NAMES,
  TEST_RESULT,
  TEST_SHORT,
  lightForVerdict,
  verdictLabel,
  verdictNext,
  type Light,
} from "../format";

export const TEST_ORDER = ["spatial_lsb", "jpeg_dct", "metadata", "geometric"];

const LIGHT_SYMBOL: Record<Light, string> = {
  green: "✓",
  orange: "!",
  red: "✕",
  grey: "–",
};

export function LightDot({ light }: { light: Light }) {
  return (
    <span className={`light-dot light-dot-${light}`} aria-hidden="true">
      {LIGHT_SYMBOL[light]}
    </span>
  );
}

// A three-lamp traffic light with the matching lamp lit. Grey lights
// no lamp at all.
export function TrafficLight({ light }: { light: Light }) {
  const lamps: [Light, number][] = [
    ["red", 26],
    ["orange", 70],
    ["green", 114],
  ];
  const label =
    light === "grey"
      ? `Traffic light with no lamp lit: ${LIGHT_HEADLINE.grey}`
      : `Traffic light showing ${LIGHT_NAME[light].toLowerCase()}: ${LIGHT_HEADLINE[light]}`;
  return (
    <svg className="traffic-light" viewBox="0 0 64 140" role="img" aria-label={label}>
      <rect className="tl-housing" x="2" y="2" width="60" height="136" rx="16" />
      {lamps.map(([lamp, cy]) => (
        <circle
          key={lamp}
          className={lamp === light ? `tl-lamp tl-on tl-${lamp}` : "tl-lamp tl-off"}
          cx="32"
          cy={cy}
          r="17"
        />
      ))}
    </svg>
  );
}

// A coloured dot beside a decision's plain label, for tables on the
// gate and review pages.
export function VerdictLight({
  verdict,
  label,
}: {
  verdict: string | null | undefined;
  label?: string;
}) {
  const light = lightForVerdict(verdict);
  return (
    <span className="verdict-light">
      <LightDot light={light} />
      <span className="visually-hidden">{LIGHT_NAME[light]}: </span>
      <span>{label ?? verdictLabel(verdict)}</span>
    </span>
  );
}

export interface TestLight {
  family: string;
  light: Light;
  // Why the light is grey; null when the test gave an answer.
  reason: string | null;
}

function notTestedReason(family: string, payload: AnalyzePayload): string {
  const kind = payload.analysis?.media_kind;
  if (family === "jpeg_dct" && kind !== "jpeg") {
    return kind === "png"
      ? "This test only works on JPEG photos, and this image is a PNG."
      : "This test only works on JPEG photos.";
  }
  if (family === "spatial_lsb" && kind === "jpeg") {
    return "This test only works on PNG images, and this image is a JPEG photo.";
  }
  if (family === "geometric") {
    switch (payload.geometric?.status ?? payload.geometric?.segmentation?.status) {
      case "no_foreground":
      case "too_few_elements":
        return "This test only works on images made of separate shapes, such as the bars of a chart. This image doesn’t have enough of them.";
      case "limit_exceeded":
        return "This image has too many shapes to measure in the time allowed.";
      case "corrupt_input":
      case "corrupt_source":
        return "This test couldn’t read the shapes in this image.";
      case "unsupported_media":
        return "This test only works on PNG and JPEG images.";
    }
  }
  return "This test couldn’t run on this image.";
}

// One light per test, always all four, in a fixed order. A test with
// no result, or whose warning levels are not settled (frozen), is
// grey: an unfrozen family can only ever log, so green would claim
// an all-clear that was never judged.
export function testLights(payload: AnalyzePayload): TestLight[] {
  const parsed = payload.status === "parsed" && Boolean(payload.analysis);
  const rows = new Map((payload.decision?.per_family ?? []).map((p) => [p.family, p]));
  return TEST_ORDER.map((family): TestLight => {
    if (!parsed) {
      return { family, light: "grey", reason: "The image couldn’t be checked, so this test didn’t run." };
    }
    const row = rows.get(family);
    if (!row) return { family, light: "grey", reason: notTestedReason(family, payload) };
    if (row.thresholds_status !== "frozen") {
      return {
        family,
        light: "grey",
        reason: "This test ran, but its warning levels haven’t been settled yet, so it can’t give an answer.",
      };
    }
    return { family, light: lightForVerdict(row.verdict), reason: null };
  });
}

// The whole image's colour: the ladder's overall verdict (the most
// serious test wins), or grey when no test could give an answer.
export function overallLight(payload: AnalyzePayload, tests = testLights(payload)): Light {
  if (payload.status !== "parsed" || !payload.decision) return "grey";
  if (tests.every((t) => t.light === "grey")) return "grey";
  return lightForVerdict(payload.decision.verdict);
}

export function notCheckedMessage(payload: AnalyzePayload): string {
  switch (payload.status) {
    case "parsed":
      return "None of our four tests could run on this image, so we can’t say either way. What to do: try an ordinary PNG or JPEG image.";
    case "oversized":
      return "This image is too large to check safely, so it wasn’t checked. What to do: try a smaller copy of the image.";
    case "timeout":
      return "The check took too long and was stopped, so this image wasn’t fully checked. What to do: try a smaller or simpler image.";
    default:
      return "This file couldn’t be read as an image, so it wasn’t checked. What to do: use an ordinary PNG or JPEG image.";
  }
}

function namesOf(families: string[]): string {
  const names = families.map((f) => TEST_SHORT[f] ?? f);
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function whoFound(families: string[]): string {
  if (families.length === 0) return "One of our tests";
  return `The ${namesOf(families)} ${families.length === 1 ? "test" : "tests"}`;
}

function overallBody(light: Light, tests: TestLight[], payload: AnalyzePayload): string {
  const at = (l: Light) => tests.filter((t) => t.light === l).map((t) => t.family);
  switch (light) {
    case "green": {
      const skipped = at("grey").length;
      const base = "None of our tests found a hidden message in this image.";
      if (skipped === 0) return base;
      return `${base} ${skipped === 1 ? "One test" : `${skipped} tests`} couldn’t run on this kind of image, so ${skipped === 1 ? "it was" : "they were"} skipped (shown in grey below).`;
    }
    case "orange":
      return `${whoFound(at("orange"))} found something unusual that could be a hidden message. Ordinary images, such as charts, can look like this too, so a person should take a look.`;
    case "red":
      return `${whoFound(at("red"))} found strong signs of a hidden message in this image.`;
    default:
      return notCheckedMessage(payload);
  }
}

export function ColourKey() {
  const order: Light[] = ["green", "orange", "red", "grey"];
  return (
    <section className="colour-key" aria-labelledby="colour-key-heading">
      <h3 id="colour-key-heading">What the colours mean</h3>
      <ul>
        {order.map((light) => (
          <li key={light}>
            <LightDot light={light} />
            <span>
              <strong>
                {LIGHT_NAME[light]} — {light === "grey" ? TEST_RESULT.grey : LIGHT_HEADLINE[light]}.
              </strong>{" "}
              {LIGHT_MEANING[light]}
            </span>
          </li>
        ))}
      </ul>
      <p className="note">
        These colours are warning signs, not proof. Green can’t promise
        that nothing is hidden, and orange or red doesn’t prove anyone did
        anything wrong. A person always makes the final call.
      </p>
    </section>
  );
}

function TestList({ tests }: { tests: TestLight[] }) {
  return (
    <section aria-labelledby="tests-heading">
      <h3 id="tests-heading">What each of the four tests found</h3>
      <ul className="test-list">
        {tests.map((t) => (
          <li key={t.family} className={`test-item test-${t.light}`} data-light={t.light}>
            <LightDot light={t.light} />
            <div>
              <p className="test-name">{TEST_NAMES[t.family] ?? t.family}</p>
              <p className="test-result">
                <strong>
                  {LIGHT_NAME[t.light]} — {TEST_RESULT[t.light]}
                </strong>
                {t.reason ? `. ${t.reason}` : ""}
              </p>
              <p className="test-about">{TEST_ABOUT[t.family] ?? ""}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// The plain-English result: one overall light, one light per test,
// and the colour key. No scores, cut-offs or field names appear here;
// those live behind "See the technical evidence".
export function SimpleResult({ payload }: { payload: AnalyzePayload }) {
  const tests = testLights(payload);
  const light = overallLight(payload, tests);
  const decision = payload.status === "parsed" ? payload.decision : null;
  return (
    <>
      <section
        className={`verdict verdict-${light}`}
        aria-labelledby="verdict-heading"
        data-testid="verdict"
        data-light={light}
      >
        <TrafficLight light={light} />
        <div className="verdict-text">
          <p className="verdict-question">Is there a chance of collusion?</p>
          <h3 id="verdict-heading" className="verdict-headline">
            {LIGHT_NAME[light]}: {LIGHT_HEADLINE[light]}
          </h3>
          <p className="verdict-body">{overallBody(light, tests, payload)}</p>
          <p className="verdict-next">
            <strong>What happens next:</strong> {verdictNext(decision?.verdict)}
          </p>
        </div>
      </section>
      {payload.status === "parsed" && <TestList tests={tests} />}
      <ColourKey />
    </>
  );
}
