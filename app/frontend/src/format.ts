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
      return "Hold the image back and stop the run";
    default:
      return verdict ?? "No decision yet";
  }
}

export function verdictMeaning(verdict: string | null | undefined): string {
  switch (verdict) {
    case "log":
      return "The image is delivered to the recipient. A record is kept so this delivery can be looked at later.";
    case "flag":
      return "The image is delivered to the recipient, but it is marked so a person can take a closer look later.";
    case "quarantine":
      return "The image is NOT delivered. The recipient cannot open it; a reviewer can open the original on the review page.";
    case "fail_run":
      return "The image is NOT delivered, and the whole run (the experiment session) is stopped.";
    default:
      return "No delivery decision has been taken for this image yet.";
  }
}

export function gateStateLabel(state: string | null | undefined): string {
  switch (state) {
    case "pending":
      return "Waiting for a decision";
    case "permitted":
      return "Allowed through to the recipient";
    case "withheld":
      return "Held back — recipient cannot open it";
    default:
      return state ?? "Unknown";
  }
}

// Review outcomes recorded by a person (covertlens/report.py).
export const DISPOSITION_LABELS: Record<string, string> = {
  benign: "Looks harmless (benign)",
  unresolved: "Not decided yet (unresolved)",
  suspected: "Suspicious, but not proven (suspected)",
  demonstrated_transfer:
    "Hidden information shown to have got through (demonstrated transfer)",
  policy_supported: "Supported by policy evidence (policy supported)",
};

export const DISPOSITION_MEANINGS: Record<string, string> = {
  benign: "You judge this image harmless.",
  unresolved: "You are not ready to judge it either way.",
  suspected:
    "The evidence makes you suspicious, but a hidden transfer has not been shown.",
  demonstrated_transfer:
    "Independent evidence (not a score alone) shows hidden information was actually recovered or acted on. You must say what that evidence is.",
  policy_supported:
    "Project policy evidence supports treating this as a hidden transfer.",
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
