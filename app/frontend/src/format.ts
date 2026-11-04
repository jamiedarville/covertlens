// Display formatting only. Evidence tables print exact response
// values; badges and bars use these shorter renderings of the
// same numbers (full value kept in a title attribute).

export function fmtScore(value: number): string {
  if (value === 0) return "0";
  if (Math.abs(value) < 0.0001) return value.toExponential(2);
  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

export function fmtNum(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    if (Math.abs(value) < 0.0001 && value !== 0) return value.toExponential(3);
    return String(Math.round(value * 1e6) / 1e6);
  }
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

export function fmtExact(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// Plain-English names first (CL-79); the technical name stays in
// brackets so specialists can still match the API and the docs.
export const FAMILY_LABELS: Record<string, string> = {
  spatial_lsb: "Tiny pixel changes (spatial LSB)",
  jpeg_dct: "JPEG compression data (DCT)",
  metadata: "Information stored in the file (metadata)",
  geometric: "Shapes and patterns in the picture (geometric)",
};

export const FAMILY_BLURBS: Record<string, string> = {
  spatial_lsb:
    "Checks for hidden information in tiny changes to pixel values. Each pixel's smallest bit can be flipped to carry data without visibly changing a PNG image.",
  jpeg_dct:
    "Checks for hidden information in the numbers JPEG compression produces when it shrinks an image. Those numbers can be nudged to carry data.",
  metadata:
    "Checks the text fields stored inside the file alongside the picture (such as author or description fields) for extra hidden data.",
  geometric:
    "Checks the visible pattern itself: for example, whether the heights, gaps or colours of repeated shapes follow a regular spacing that could spell something out (PNG images).",
};

// Delivery decisions ("verdicts"). Meanings verified against the
// ladder in covertlens/verdicts.py: log and flag let the image
// through; quarantine holds it back; fail_run holds it back and
// stops the run.
export function verdictLabel(verdict: string | null | undefined): string {
  switch (verdict) {
    case "log":
      return "Let it through and record it";
    case "flag":
      return "Let it through, but flag it for attention";
    case "quarantine":
      return "Hold the image back for review";
    case "fail_run":
      return "Hold the image back and stop the session";
    default:
      return verdict ?? "No decision yet";
  }
}

export function verdictMeaning(verdict: string | null | undefined): string {
  switch (verdict) {
    case "log":
      return "The image is delivered to the other agent. A record is kept so it can be looked at later.";
    case "flag":
      return "The image is delivered to the other agent, but it’s marked so a person can take a closer look later.";
    case "quarantine":
      return "The image is NOT delivered. The other agent can’t open it; a reviewer can open the original on the review page.";
    case "fail_run":
      return "The image is NOT delivered, and the whole session is stopped.";
    default:
      return "No delivery decision has been taken for this image yet.";
  }
}

export function gateStateLabel(state: string | null | undefined): string {
  switch (state) {
    case "pending":
      return "Waiting for a decision";
    case "permitted":
      return "Allowed through to the other agent";
    case "withheld":
      return "Held back — the other agent can’t open it";
    default:
      return state ?? "Unknown";
  }
}

// Review outcomes recorded by a person (covertlens/report.py).
// Plain labels; the exact value (benign, unresolved, …) stays in
// title attributes and the technical breakdown.
export const DISPOSITION_LABELS: Record<string, string> = {
  benign: "Looks harmless",
  unresolved: "Not decided yet",
  suspected: "Suspicious, but not proven",
  demonstrated_transfer: "A hidden message was shown to get through",
  policy_supported: "Project policy says treat it as a hidden message",
};

export const DISPOSITION_MEANINGS: Record<string, string> = {
  benign: "You judge this image harmless.",
  unresolved: "You are not ready to judge it either way.",
  suspected:
    "The evidence makes you suspicious, but no hidden message has been shown to get through.",
  demonstrated_transfer:
    "Independent evidence (not a score alone) shows the hidden message was actually recovered or acted on. You must say what that evidence is.",
  policy_supported:
    "Project policy says this should be treated as a hidden message.",
};

export function scoreMeaning(score: number): string {
  if (score === 0) {
    return "This check measured no signal in this image. That does not prove nothing is hidden — only that this check found nothing.";
  }
  return "This check measured a signal. Higher (closer to 1) means stronger evidence of the pattern this check looks for. A score is evidence, not proof, and it is not a percentage chance. Compare it with the cut-offs in the decision section.";
}

// Turn an API field name such as `null_exceedance` into readable
// words. Known terms get a short explanation; anything else is
// spaced out, and the exact field name stays available in titles.
const KEY_LABELS: Record<string, string> = {
  config_version: "Settings version",
  detector_config_version: "Check settings version",
  null_exceedance:
    "How often shuffled (randomised) data scores this well — lower is stronger evidence",
  rayleigh_R: "How neatly the values fit one regular spacing (0 to 1)",
  rms_residual: "Typical distance from the regular spacing",
  content_hash: "File fingerprint (identical files share it)",
  media_kind: "File type",
  elements: "Shapes measured",
  supporting: "Shapes fitting the spacing",
  levels_used: "Different spacing steps used",
  quantized: "Values fall on a regular spacing",
  applicable: "This check applies to this file",
  coverage: "What was checked",
  score: "Score (0 to 1)",
};

export function humanizeKey(key: string): string {
  if (KEY_LABELS[key]) return KEY_LABELS[key] as string;
  const spaced = key.replaceAll("_", " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export const CHANNEL_LABELS: Record<string, string> = {
  height: "Height",
  gap: "Gap to the next shape",
  lit: "Brightness (lit or dark)",
  angle: "Tilt angle",
  colour: "Colour",
};

export function classificationLabel(classification: string | null): string {
  switch (classification) {
    case "structure_claimed":
      return "Pattern looks deliberately arranged";
    case "quantized_without_structure":
      return "Regular spacing, but no deliberate pattern found";
    case "quantized_declared_channel":
      return "Regular spacing in an openly declared channel";
    case "no_signal":
      return "No pattern found";
    default:
      return classification ?? "Not classified";
  }
}

export function classificationMeaning(classification: string | null): string {
  switch (classification) {
    case "structure_claimed":
      return "The values fall on a regular spacing AND, read under a code declared in advance, they look more organised than shuffled versions of the same values. This is evidence, not a decoded message.";
    case "quantized_without_structure":
      return "The values fall on a regular spacing, which ordinary charts also do, but no declared code explains them better than chance. Regular spacing alone is not treated as a hidden message.";
    case "quantized_declared_channel":
      return "The values fall on a regular spacing in a channel the project has openly declared allowed, so this is expected rather than suspicious.";
    case "no_signal":
      return "No regular spacing or organised pattern was measured. That does not prove nothing is hidden — only that this check found nothing.";
    default:
      return "This image was not given a shape-pattern classification.";
  }
}

// Traffic-light answer (CL-79). The colour comes from the same frozen
// verdict ladder the delivery gate uses, so no new cut-offs exist:
// log → green, flag → orange, quarantine and fail_run → red. Grey
// means a test did not run or could not give an answer; grey is never
// shown as green, because "not checked" is not "all clear".
export type Light = "green" | "orange" | "red" | "grey";

export function lightForVerdict(verdict: string | null | undefined): Light {
  switch (verdict) {
    case "log":
      return "green";
    case "flag":
      return "orange";
    case "quarantine":
    case "fail_run":
      return "red";
    default:
      return "grey";
  }
}

export const LIGHT_SEVERITY: Record<Light, number> = { grey: -1, green: 0, orange: 1, red: 2 };

export const LIGHT_NAME: Record<Light, string> = {
  green: "Green",
  orange: "Orange",
  red: "Red",
  grey: "Grey",
};

// The answer to "is there a chance of collusion?" for the whole image.
export const LIGHT_HEADLINE: Record<Light, string> = {
  green: "No evidence of collusion",
  orange: "Potential collusion",
  red: "High potential for collusion",
  grey: "Not checked",
};

// One line per colour for the colour key.
export const LIGHT_MEANING: Record<Light, string> = {
  green: "Our tests found nothing hidden.",
  orange:
    "Something unusual was found. Ordinary images can look like this too, so a person should take a look.",
  red: "Strong signs of a hidden message. The image would be held back until a person checks it.",
  grey: "The test didn’t run on this image, so it gives no answer either way.",
};

// What one test found, in a few words.
export const TEST_RESULT: Record<Light, string> = {
  green: "Nothing suspicious found",
  orange: "Something unusual found",
  red: "Strong signs of a hidden message",
  grey: "Not tested",
};

export const TEST_NAMES: Record<string, string> = {
  spatial_lsb: "Tiny colour changes",
  jpeg_dct: "JPEG compression",
  metadata: "File details",
  geometric: "Shapes and patterns",
};

// Used inside sentences: "The shapes and patterns test found…".
export const TEST_SHORT: Record<string, string> = {
  spatial_lsb: "tiny colour changes",
  jpeg_dct: "JPEG compression",
  metadata: "file details",
  geometric: "shapes and patterns",
};

export const TEST_ABOUT: Record<string, string> = {
  spatial_lsb: "Looks for a message hidden in colour changes too small for the eye to see.",
  jpeg_dct: "Looks for a message hidden in the way a JPEG photo is compressed.",
  metadata:
    "Looks for a message tucked into the details stored inside the file, such as its title or description.",
  geometric:
    "Looks for a message spelled out by the sizes, gaps or colours of shapes, such as the bars of a chart.",
};

// What would happen to the image, in plain words (same ladder as
// verdictMeaning, phrased for the traffic-light answer).
export function verdictNext(verdict: string | null | undefined): string {
  switch (verdict) {
    case "log":
      return "It would be passed on to the agent it was sent to, as normal.";
    case "flag":
      return "It would still be passed on, but it’s marked so a person can check it.";
    case "quarantine":
      return "It would be held back. The agent it was sent to can’t see it until a person has checked it.";
    case "fail_run":
      return "It would be held back, and the AI session it came from would be stopped until a person has checked it.";
    default:
      return "Nothing was decided. Not checked doesn’t mean safe.";
  }
}

// Demo roles, in plain words (what each one can do).
export const ROLE_PLAIN: Record<string, string> = {
  viewer: "Viewer — can only look",
  researcher: "Researcher — can run the gate and make decisions",
  reviewer: "Reviewer — can open held-back images and judge them",
};

// "0.95082" → 95, for "95 out of 100".
export function outOf100(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? Math.round(value * 100) : null;
}

// Where a test image hid its message (generator kind and subfamily).
const SUBFAMILY_PLAIN: Record<string, string> = {
  height_position: "bar heights",
  gap_timing: "gaps between bars",
  lit_dark: "lit or dark bars",
  colour_code: "bar colours",
  angle_tilt: "bar tilt",
};

export function hidingPlace(kind: string, subfamily?: string | null): string {
  const base = TEST_NAMES[kind] ?? humanizeKey(kind);
  if (!subfamily) return base;
  return `${base}: ${SUBFAMILY_PLAIN[subfamily] ?? subfamily.replaceAll("_", " ")}`;
}

// Release targets (covertlens/scorecard.py `_targets`), in plain words.
export const TARGET_LABELS: Record<string, string> = {
  recall: "Spots at least 95 out of 100 hidden messages in testing",
  precision: "When it holds an image back, it’s right at least 99 times out of 100",
  clean_stability: "Wrongly stops no more than 1 in 100 ordinary test sessions",
  latency: "Checks 95 out of 100 images of every tested size within 2 seconds",
  gate_trace: "Explains every delivery, and never gives out an image without permission",
  route_coverage: "Checks images on every route they can travel",
  exports: "Saves sealed evidence records, and refuses anyone not allowed to see them",
  prevention: "Never counts a held-back image as a message that got through",
  geometric: "The shapes test passes all of its own checks",
  sequence_value: "Looking at a sender’s earlier images makes it better at spotting messages",
  pilot: "In a small trial, no planted message got through and no ordinary image was held back",
  robustness: "Catches every deliberate attempt to beat it",
  infrastructure: "Holds an image back, rather than letting it through, when a check can’t finish",
};

export function targetLabel(name: string): string {
  return TARGET_LABELS[name] ?? humanizeKey(name);
}

// The release decision, as a colour and a plain headline.
export function releaseLight(value: string): Light {
  switch (value) {
    case "release":
      return "green";
    case "release_with_limitations":
      return "orange";
    case "do_not_release":
      return "red";
    default:
      return "grey";
  }
}

export function releaseHeadline(value: string): string {
  switch (value) {
    case "release":
      return "Ready to release";
    case "release_with_limitations":
      return "Released, with known limitations";
    case "do_not_release":
      return "Not ready to release yet";
    default:
      return humanizeKey(value);
  }
}
