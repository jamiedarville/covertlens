// Geometric overlay (CL-48): canvas bounding boxes in reading
// order, per-channel sequence plot, Rayleigh periodogram with the
// discovered step marked, residual histogram, chart-likeness
// gauge, structure score against the null, classification badge.
// Everything renders from the /api/analyze JSON alone. Symbols
// stay numeric indices; this page never shows decoded text.

import { useEffect, useRef, useState } from "react";
import type { GeoElement, Geometric } from "../types";
import { CHANNEL_LABELS, classificationLabel, fmtExact, fmtNum } from "../format";
import { Gauge, HistogramPlot, PeriodogramPlot, ScoreBar, SequencePlot } from "./Charts";

const CHANNEL_ORDER = ["height", "gap", "lit", "angle", "colour"];

function CanvasOverlay({
  imageUrl,
  imageLabel,
  elements,
  segWidth,
  segHeight,
  showBoxes,
  highlighted,
}: {
  imageUrl: string | null;
  imageLabel: string;
  elements: GeoElement[];
  segWidth: number;
  segHeight: number;
  showBoxes: boolean;
  highlighted: number | null;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    const canvas = canvasRef.current;
    if (!canvas || !imageUrl) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let cancelled = false;
    const img = new Image();
    img.onload = () => {
      if (cancelled) return;
      const naturalW = img.naturalWidth || segWidth;
      const naturalH = img.naturalHeight || segHeight;
      const scale = Math.min(2, 1600 / Math.max(naturalW, 1));
      canvas.width = Math.round(naturalW * scale);
      canvas.height = Math.round(naturalH * scale);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      if (!showBoxes) return;
      const sx = (naturalW / (segWidth || naturalW)) * scale;
      const sy = (naturalH / (segHeight || naturalH)) * scale;
      ctx.font = `${Math.max(11 * scale, 11)}px ui-monospace, monospace`;
      ctx.textBaseline = "top";
      for (const el of elements) {
        const x = el.left * sx;
        const y = el.top * sy;
        const w = Math.max(el.width * sx, 2);
        const h = Math.max(el.height * sy, 2);
        const isHot = highlighted === el.index;
        // Dual stroke (white halo, dark core) stays visible on any
        // scene background; the reading-order number means meaning
        // never rests on colour alone (WCAG AA, CL-48).
        ctx.lineWidth = 4.5 * scale;
        ctx.strokeStyle = "#ffffff";
        ctx.strokeRect(x, y, w, h);
        ctx.lineWidth = 2.2 * scale;
        ctx.strokeStyle = isHot ? "#9b1c1c" : "#111111";
        ctx.strokeRect(x, y, w, h);
        const label = String(el.index);
        const tw = ctx.measureText(label).width;
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(x, y, tw + 6 * scale, 15 * scale);
        ctx.fillStyle = "#111111";
        ctx.fillText(label, x + 3 * scale, y + 2 * scale);
      }
    };
    img.onerror = () => {
      if (!cancelled) setFailed(true);
    };
    img.src = imageUrl;
    return () => {
      cancelled = true;
    };
  }, [imageUrl, elements, segWidth, segHeight, showBoxes, highlighted]);

  if (!imageUrl) {
    return <p className="note">No preview image available; the tables below carry the same measurements.</p>;
  }
  if (failed) {
    return <p className="note">The preview image could not be drawn here; the tables below carry the same measurements.</p>;
  }
  return (
    <canvas
      ref={canvasRef}
      className="overlay-canvas"
      role="img"
      aria-label={`${imageLabel} with ${elements.length} segmented elements outlined and numbered in reading order.`}
    />
  );
}

function fallbackValues(geometric: Geometric, channel: string): number[] {
  // Only used if an older cached payload has no overlay block:
  // the same measured sequences, under the detector's mapping.
  const attr: Record<string, string> = {
    height: "height",
    gap: "gap_to_next",
    lit: "brightness",
    angle: "angle_deg",
    colour: "colour_index",
  };
  const seq = geometric.segmentation?.sequences[attr[channel] ?? ""] ?? [];
  return seq.filter((v): v is number => v !== null);
}

export function Overlay({
  geometric,
  imageUrl,
  imageLabel,
}: {
  geometric: Geometric | null;
  imageUrl: string | null;
  imageLabel: string;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [highlighted, setHighlighted] = useState<number | null>(null);

  if (!geometric) {
    return (
      <section aria-labelledby="overlay-heading">
        <h2 id="overlay-heading">Geometric overlay</h2>
        <p>
          No geometric report was returned for this input. The geometric
          family measures PNG rasters; other inputs are covered by the
          families above.
        </p>
      </section>
    );
  }

  const seg = geometric.segmentation;
  const elements = seg?.elements ?? [];
  // Failed-segmentation reports omit channels entirely (CL-51 fix).
  const channels = geometric.channels ?? {};
  const channelNames = CHANNEL_ORDER.filter((name) => channels[name]);
  const active =
    selected && channels[selected]
      ? selected
      : geometric.primary_channel && channels[geometric.primary_channel]
        ? geometric.primary_channel
        : (channelNames[0] ?? "height");
  const channel = channels[active];
  const overlayChannel = geometric.overlay?.channels[active];
  const values = overlayChannel?.values ?? fallbackValues(geometric, active);
  const chart = geometric.chart_likeness;
  const structure = geometric.structure;

  return (
    <section aria-labelledby="overlay-heading">
      <div className="card-head">
        <h2 id="overlay-heading">Geometric overlay</h2>
        <span className="badge" title={geometric.classification ?? undefined}>
          {classificationLabel(geometric.classification)}
        </span>
      </div>
      <p>
        Evidence aid — not a decoded message. Boxes follow reading order;
        grid symbols are shown as numbers only. Signal grade:{" "}
        <strong>{fmtExact(geometric.signal_grade)}</strong>; primary channel:{" "}
        <strong>{fmtExact(geometric.primary_channel)}</strong>.
      </p>

      {seg && elements.length > 0 ? (
        <>
          <div className="overlay-controls">
            <label className="check">
              <input
                type="checkbox"
                checked={showBoxes}
                onChange={(e) => setShowBoxes(e.target.checked)}
              />
              Show element boxes ({elements.length} elements)
            </label>
          </div>
          <CanvasOverlay
            imageUrl={imageUrl}
            imageLabel={imageLabel}
            elements={elements}
            segWidth={seg.width}
            segHeight={seg.height}
            showBoxes={showBoxes}
            highlighted={highlighted}
          />
        </>
      ) : (
        <p className="note">
          Segmentation status: {fmtExact(seg?.status ?? geometric.status)}
          {seg?.detail ? ` — ${seg.detail}` : ""}. No element overlay is
          available for this image.
        </p>
      )}

      {channel && (
        <div className="channel-block">
          <div className="tabs" role="tablist" aria-label="Geometric channels">
            {channelNames.map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={name === active}
                className={name === active ? "tab tab-active" : "tab"}
                onClick={() => setSelected(name)}
              >
                {CHANNEL_LABELS[name] ?? name}
                {channels[name]?.quantized ? " · quantized" : ""}
              </button>
            ))}
          </div>

          <h3>{CHANNEL_LABELS[active] ?? active} sequence</h3>
          <SequencePlot
            values={values}
            unit={overlayChannel?.unit ?? ""}
            step={channel.step}
            offset={channel.offset}
            symbols={channel.symbols}
            title={`${CHANNEL_LABELS[active] ?? active} attribute sequence`}
          />
          <p className="note">
            Values in reading order
            {channel.step !== null
              ? `; horizontal lines mark the discovered grid (step ${fmtNum(channel.step)}, offset ${fmtNum(channel.offset)}).`
              : "; no grid was discovered for this channel."}
          </p>
          <p className="symbols">
            <span className="symbols-label">Grid symbols (numeric only):</span>{" "}
            <span className="mono">{channel.symbols.join(" ")}</span>
          </p>

          <h3>Rayleigh periodogram</h3>
          {overlayChannel?.periodogram.available ? (
            <>
              <PeriodogramPlot
                points={overlayChannel.periodogram.points}
                discoveredStep={overlayChannel.periodogram.discovered_step}
                discoveredR={overlayChannel.periodogram.discovered_rayleigh_R}
                title={`Rayleigh periodogram for ${CHANNEL_LABELS[active] ?? active}`}
              />
              <p className="note">
                R is 1 when every value locks onto one step. The marker is
                the discovered step {fmtNum(channel.step)} with R{" "}
                {fmtNum(channel.rayleigh_R)}; null exceedance{" "}
                {fmtExact(channel.null_exceedance)}.
              </p>
            </>
          ) : (
            <p className="note">
              {overlayChannel?.periodogram.reason ??
                "No periodogram was included for this channel in the response."}
            </p>
          )}

          <h3>Residual histogram</h3>
          {overlayChannel ? (
            <HistogramPlot
              edges={overlayChannel.residual_histogram.bin_edges}
              counts={overlayChannel.residual_histogram.counts}
              tolerance={overlayChannel.residual_histogram.tolerance}
              title={`Residual histogram for ${CHANNEL_LABELS[active] ?? active}`}
            />
          ) : (
            <p className="note">No histogram bins were included for this channel.</p>
          )}
          <p className="note">
            Distance of each value from its grid point. Residuals inside the
            dashed tolerance support the grid; RMS residual{" "}
            {fmtNum(channel.rms_residual)}.
          </p>
        </div>
      )}

      {chart && (
        <div className="panel">
          <h3>Chart-likeness: {fmtNum(chart.score)}</h3>
          <Gauge score={chart.score} label={`Chart-likeness ${fmtNum(chart.score)} of 1`} />
          <p className="note">
            Legitimate charts are grid-snapped by design, so this context
            travels with any quantization finding. Baseline present:{" "}
            {chart.baseline_present ? "yes" : "no"}.
          </p>
          <dl className="kv">
            {Object.entries(chart.features).map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{fmtExact(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {structure && (
        <div className="panel">
          <div className="card-head">
            <h3>Structure against the null</h3>
            <span className={structure.claimed ? "badge badge-claimed" : "badge"}>
              {structure.claimed ? "Structure claimed" : "No structure claimed"}
            </span>
          </div>
          <dl className="kv kv-wide">
            <div><dt>Declared code</dt><dd>{fmtExact(structure.code)}</dd></div>
            <div><dt>Trigram score</dt><dd>{fmtExact(structure.trigram_score)}</dd></div>
            <div><dt>Null exceedance</dt><dd>{fmtExact(structure.null_exceedance)}</dd></div>
            <div><dt>Log-likelihood ratio</dt><dd>{fmtExact(structure.log_likelihood_ratio)}</dd></div>
            <div><dt>Printable fraction</dt><dd>{fmtExact(structure.printable_fraction)}</dd></div>
          </dl>
          {structure.null_exceedance !== null && (
            <>
              <ScoreBar score={structure.null_exceedance} />
              <p className="note">
                Null exceedance on a 0–1 scale: lower means shuffled symbols
                rarely score this well, which is stronger evidence of
                structure. {structure.reason ?? ""}
              </p>
            </>
          )}
          {!structure.claimed && structure.reason && (
            <p className="note">{structure.reason}</p>
          )}
        </div>
      )}

      <div className="table-wrap">
        <table>
          <caption>All geometric channels, exactly as returned</caption>
          <thead>
            <tr>
              <th scope="col">Channel</th>
              <th scope="col">Step</th>
              <th scope="col">Rayleigh R</th>
              <th scope="col">Null exceedance</th>
              <th scope="col">Support</th>
              <th scope="col">RMS residual</th>
              <th scope="col">Levels</th>
              <th scope="col">Score</th>
              <th scope="col">Quantized</th>
            </tr>
          </thead>
          <tbody>
            {channelNames.map((name) => {
              const c = channels[name] as NonNullable<typeof channel>;
              return (
                <tr key={name} className={name === active ? "row-active" : undefined}>
                  <th scope="row">{CHANNEL_LABELS[name] ?? name}</th>
                  <td className="num">{fmtExact(c.step)}</td>
                  <td className="num">{fmtExact(c.rayleigh_R)}</td>
                  <td className="num">{fmtExact(c.null_exceedance)}</td>
                  <td className="num">{c.supporting}/{c.elements}</td>
                  <td className="num">{fmtExact(c.rms_residual)}</td>
                  <td className="num">{c.levels_used}</td>
                  <td className="num">{fmtExact(c.score)}</td>
                  <td>{c.applicable ? (c.quantized ? "yes" : "no") : "not applicable"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {elements.length > 0 && (
        <div className="table-wrap">
          <table>
            <caption>
              Segmented elements in reading order — select a row to highlight
              its box
            </caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Left</th>
                <th scope="col">Top</th>
                <th scope="col">Width</th>
                <th scope="col">Height</th>
                <th scope="col">Gap →</th>
                <th scope="col">Angle°</th>
                <th scope="col">Colour idx</th>
                <th scope="col">Brightness</th>
              </tr>
            </thead>
            <tbody>
              {elements.map((el) => (
                <tr
                  key={el.index}
                  className={highlighted === el.index ? "row-active" : undefined}
                  onClick={() =>
                    setHighlighted(highlighted === el.index ? null : el.index)
                  }
                >
                  <th scope="row">{el.index}</th>
                  <td className="num">{el.left}</td>
                  <td className="num">{el.top}</td>
                  <td className="num">{el.width}</td>
                  <td className="num">{el.height}</td>
                  <td className="num">{fmtExact(el.gap_to_next)}</td>
                  <td className="num">{fmtExact(el.angle_deg)}</td>
                  <td className="num">{el.colour_index}</td>
                  <td className="num">{fmtExact(el.brightness)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
