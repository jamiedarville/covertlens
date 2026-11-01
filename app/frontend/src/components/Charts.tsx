// Hand-drawn SVG charts. Every plotted value comes from the
// /api/analyze response (sequences, overlay periodogram points and
// histogram bins are computed server-side, CL-48); this file only
// scales response numbers into viewBox coordinates.

import { fmtNum } from "../format";

const W = 640;
const H = 220;
const PAD = { left: 52, right: 14, top: 14, bottom: 30 };

function xScale(index: number, count: number): number {
  const inner = W - PAD.left - PAD.right;
  if (count <= 1) return PAD.left + inner / 2;
  return PAD.left + (index / (count - 1)) * inner;
}

export function SequencePlot({
  values,
  unit,
  step,
  offset,
  symbols,
  title,
}: {
  values: number[];
  unit: string;
  step: number | null;
  offset: number | null;
  symbols: number[];
  title: string;
}) {
  if (values.length === 0) return <p className="note">No values in this channel.</p>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const lo = min - span * 0.08;
  const hi = max + span * 0.08;
  const y = (v: number) => PAD.top + (1 - (v - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const line = values.map((v, i) => `${xScale(i, values.length)},${y(v)}`).join(" ");
  const gridLevels: number[] = [];
  if (step !== null && offset !== null && symbols.length > 0) {
    const kMin = Math.min(...symbols);
    const kMax = Math.max(...symbols);
    if (kMax - kMin <= 40) {
      for (let k = kMin; k <= kMax; k++) gridLevels.push(offset + k * step);
    }
  }
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`${title}. ${values.length} values in reading order, from ${fmtNum(min)} to ${fmtNum(max)} ${unit}.`}>
      <title>{title}</title>
      {gridLevels.map((level) => (
        <line key={level} x1={PAD.left} x2={W - PAD.right} y1={y(level)} y2={y(level)}
          className="chart-gridline" />
      ))}
      <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom} className="chart-axis" />
      <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} className="chart-axis" />
      <polyline points={line} className="chart-line-sequence" fill="none" />
      {values.map((v, i) => (
        <circle key={i} cx={xScale(i, values.length)} cy={y(v)} r="3" className="chart-dot-sequence" />
      ))}
      <text x={4} y={y(max) + 4} className="chart-text">{fmtNum(max)}</text>
      <text x={4} y={y(min) + 4} className="chart-text">{fmtNum(min)}</text>
      <text x={PAD.left} y={H - 8} className="chart-text">element 0</text>
      <text x={W - PAD.right} y={H - 8} textAnchor="end" className="chart-text">
        element {values.length - 1} · {unit}
      </text>
    </svg>
  );
}

export function PeriodogramPlot({
  points,
  discoveredStep,
  discoveredR,
  title,
}: {
  points: { step: number; rayleigh_R: number }[];
  discoveredStep: number | null;
  discoveredR: number | null;
  title: string;
}) {
  if (points.length === 0) return <p className="note">No periodogram points in the response.</p>;
  const minStep = Math.min(...points.map((p) => p.step));
  const maxStep = Math.max(...points.map((p) => p.step));
  const x = (s: number) =>
    PAD.left + ((s - minStep) / (maxStep - minStep || 1)) * (W - PAD.left - PAD.right);
  const y = (r: number) => PAD.top + (1 - r) * (H - PAD.top - PAD.bottom);
  const line = points.map((p) => `${x(p.step)},${y(p.rayleigh_R)}`).join(" ");
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`${title}. Rayleigh R against candidate step.${discoveredStep !== null ? ` Discovered step ${fmtNum(discoveredStep)} with R ${fmtNum(discoveredR)}.` : ""}`}>
      <title>{title}</title>
      <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom} className="chart-axis" />
      <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} className="chart-axis" />
      <polyline points={line} className="chart-line-periodogram" fill="none" />
      {discoveredStep !== null && (
        <>
          <line x1={x(discoveredStep)} x2={x(discoveredStep)} y1={PAD.top} y2={H - PAD.bottom}
            className="chart-marker" />
          {discoveredR !== null && (
            <circle cx={x(discoveredStep)} cy={y(discoveredR)} r="4.5" className="chart-dot-marker" />
          )}
          <text x={Math.min(x(discoveredStep) + 6, W - 150)} y={PAD.top + 12} className="chart-text-strong">
            discovered step {fmtNum(discoveredStep)}
          </text>
        </>
      )}
      <text x={4} y={y(1) + 4} className="chart-text">R 1</text>
      <text x={4} y={y(0) + 4} className="chart-text">R 0</text>
      <text x={PAD.left} y={H - 8} className="chart-text">step {fmtNum(minStep)}</text>
      <text x={W - PAD.right} y={H - 8} textAnchor="end" className="chart-text">step {fmtNum(maxStep)}</text>
    </svg>
  );
}

export function HistogramPlot({
  edges,
  counts,
  tolerance,
  title,
}: {
  edges: number[];
  counts: number[];
  tolerance: number;
  title: string;
}) {
  if (edges.length < 2 || counts.length === 0) {
    return <p className="note">No residuals in the response for this channel.</p>;
  }
  const lo = edges[0] as number;
  const hi = edges[edges.length - 1] as number;
  const maxCount = Math.max(...counts, 1);
  const x = (v: number) =>
    PAD.left + ((v - lo) / (hi - lo || 1)) * (W - PAD.left - PAD.right);
  const barH = (c: number) => (c / maxCount) * (H - PAD.top - PAD.bottom);
  const total = counts.reduce((a, b) => a + b, 0);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`${title}. ${total} residuals in ${counts.length} bins from ${fmtNum(lo)} to ${fmtNum(hi)}; tallest bin holds ${maxCount}.`}>
      <title>{title}</title>
      <line x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={H - PAD.bottom} className="chart-axis" />
      <line x1={PAD.left} x2={W - PAD.right} y1={H - PAD.bottom} y2={H - PAD.bottom} className="chart-axis" />
      {counts.map((count, i) => {
        const x0 = x(edges[i] as number);
        const x1 = x(edges[i + 1] as number);
        const h = barH(count);
        return (
          <g key={i}>
            <rect x={x0 + 1} y={H - PAD.bottom - h} width={Math.max(x1 - x0 - 2, 1)} height={h}
              className="chart-bar" />
            {count > 0 && (
              <text x={(x0 + x1) / 2} y={H - PAD.bottom - h - 4} textAnchor="middle" className="chart-text">
                {count}
              </text>
            )}
          </g>
        );
      })}
      {[-tolerance, tolerance].map((mark) => (
        <line key={mark} x1={x(mark)} x2={x(mark)} y1={PAD.top} y2={H - PAD.bottom}
          className="chart-tolerance" />
      ))}
      <text x={4} y={PAD.top + 4} className="chart-text">count</text>
      <text x={PAD.left} y={H - 8} className="chart-text">{fmtNum(lo)}</text>
      <text x={W - PAD.right} y={H - 8} textAnchor="end" className="chart-text">
        residual {fmtNum(hi)} · dashed lines at ±{fmtNum(tolerance)} tolerance
      </text>
    </svg>
  );
}

export function Gauge({ score, label }: { score: number; label: string }) {
  const clamped = Math.min(1, Math.max(0, score));
  return (
    <div className="gauge">
      <div className="gauge-track" role="meter" aria-label={label}
        aria-valuemin={0} aria-valuemax={1} aria-valuenow={score} aria-valuetext={fmtNum(score)}>
        <div className="gauge-fill" style={{ width: `${clamped * 100}%` }} />
      </div>
      <div className="gauge-scale" aria-hidden="true">
        <span>0 — scene-like</span>
        <span>1 — chart-like</span>
      </div>
    </div>
  );
}

export function ScoreBar({ score }: { score: number }) {
  const clamped = Math.min(1, Math.max(0, score));
  return (
    <div className="scorebar" aria-hidden="true">
      <div className="scorebar-fill" style={{ width: `${clamped * 100}%` }} />
    </div>
  );
}
