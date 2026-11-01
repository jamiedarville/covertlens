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

export const FAMILY_LABELS: Record<string, string> = {
  spatial_lsb: "Spatial LSB",
  jpeg_dct: "JPEG DCT",
  metadata: "Metadata",
  geometric: "Geometric",
};

export const FAMILY_BLURBS: Record<string, string> = {
  spatial_lsb: "Patterns hidden in pixel least-significant bits (PNG).",
  jpeg_dct: "Patterns hidden in JPEG frequency coefficients.",
  metadata: "Payloads carried in file metadata fields.",
  geometric: "Patterns hidden in the visible geometry of repeated elements (PNG).",
};

export const CHANNEL_LABELS: Record<string, string> = {
  height: "Height",
  gap: "Gap",
  lit: "Lit / brightness",
  angle: "Angle",
  colour: "Colour",
};

export function classificationLabel(classification: string | null): string {
  switch (classification) {
    case "structure_claimed":
      return "Structure claimed";
    case "quantized_without_structure":
      return "Quantized, no structure";
    case "quantized_declared_channel":
      return "Quantized declared channel";
    case "no_signal":
      return "No signal";
    default:
      return classification ?? "Not classified";
  }
}
