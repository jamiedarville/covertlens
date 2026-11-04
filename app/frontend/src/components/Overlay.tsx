// Geometric overlay (CL-48): canvas bounding boxes in reading
// order, per-channel sequence plot, Rayleigh periodogram with the
// discovered step marked, residual histogram, chart-likeness
// gauge, structure score against the null, classification badge.
// Everything renders from the /api/analyze JSON alone. Symbols
// stay numeric indices; this page never shows decoded text.

import { useEffect, useRef, useState } from "react";
import type { GeoElement, Geometric } from "../types";
import { CHANNEL_LABELS, classificationLabel, classificationMeaning, fmtExact, fmtNum, humanizeKey } from "../format";
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
    return <p className="note">No preview of the picture is available here. You lose nothing: the tables below contain exactly the same measurements in words and numbers.</p>;
  }
  if (failed) {
    return <p className="note">The preview picture could not be drawn in your browser. You lose nothing: the tables below contain exactly the same measurements in words and numbers.</p>;
  }
  return (
    <canvas
      ref={canvasRef}
      className="overlay-canvas"
      role="img"
      aria-label={`${imageLabel} with ${elements.length} measured shapes outlined and numbered in reading order (left to right, top to bottom).`}
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
        <h2 id="overlay-heading">Measurements drawn on the picture (shape patterns)</h2>
        <p>
          This check was not run on this file: it only measures PNG
          pictures. “Not run” is not the same as “all clear” — the other
          checks above still apply.
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
        <h2 id="overlay-heading">Measurements drawn on the picture (shape patterns)</h2>
        <span className="badge" title={geometric.classification ?? undefined}>
          {classificationLabel(geometric.classification)}
        </span>
      </div>
      <p>{classificationMeaning(geometric.classification)}</p>
      <p>
        This section shows <em>where</em> the shape-pattern check looked
        and <em>what it measured</em>. It is evidence to help a person
        judge — it is not a decoded hidden message, and no hidden text is
        shown. Each shape found in the picture is outlined and numbered in
        reading order (left to right, top to bottom). The check then asks:
        do the shapes’ heights, gaps, brightness, angles or colours fall
        on a regular spacing (like steps of exactly 10 pixels), the way a
        code could use them to spell something out? Our measurements of
        pattern strength: <strong>{fmtExact(geometric.signal_grade)}</strong>;
        most informative measurement:{" "}
        <strong>{CHANNEL_LABELS[geometric.primary_channel ?? ""] ?? fmtExact(geometric.primary_channel)}</strong>.
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
              Show outlines around the {elements.length} measured shapes
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
          No separate shapes could be picked out in this picture, so there
          is nothing to outline (the checker reported:{" "}
          {fmtExact(seg?.status ?? geometric.status)}
          {seg?.detail ? ` — ${seg.detail}` : ""}). This can happen with
          photographs and other pictures without clear repeated shapes.
        </p>
      )}

      {channel && (
        <div className="channel-block">
          <p className="note">
            Choose which measurement of the shapes to look at. “Fits a
            regular spacing” means the values land on evenly spaced steps —
            ordinary charts do this too, so read the explanation under each
            chart.
          </p>
          <div className="tabs" role="tablist" aria-label="Which measurement of the shapes to view">
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
                {channels[name]?.quantized ? " · fits a regular spacing" : ""}
              </button>
            ))}
          </div>

          <h3>{CHANNEL_LABELS[active] ?? active} of each shape, in reading order</h3>
          <SequencePlot
            values={values}
            unit={overlayChannel?.unit ?? ""}
            step={channel.step}
            offset={channel.offset}
            symbols={channel.symbols}
            title={`${CHANNEL_LABELS[active] ?? active} attribute sequence`}
          />
          <p className="note">
            Each dot is one shape, in reading order.
            {channel.step !== null
              ? ` The horizontal lines are the regular spacing that was found: steps of ${fmtNum(channel.step)} starting from ${fmtNum(channel.offset)}. Dots sitting on the lines fit that spacing.`
              : " No regular spacing was found for this measurement."}
          </p>
          <p className="symbols">
            <span className="symbols-label">
              Which step of the spacing each shape falls on (numbers only — never shown as letters or decoded text):
            </span>{" "}
            <span className="mono">{channel.symbols.join(" ")}</span>
          </p>

          <h3>How well does one regular spacing explain these values?</h3>
          <p className="note">
            This chart (specialists call it a Rayleigh periodogram) tries
            many possible step sizes. A tall peak means that step size fits
            the values well.
          </p>
          {overlayChannel?.periodogram.available ? (
            <>
              <PeriodogramPlot
                points={overlayChannel.periodogram.points}
                discoveredStep={overlayChannel.periodogram.discovered_step}
                discoveredR={overlayChannel.periodogram.discovered_rayleigh_R}
                title={`Rayleigh periodogram for ${CHANNEL_LABELS[active] ?? active}`}
              />
              <p className="note">
                The quality-of-fit score “R” reaches 1 when every value
                falls exactly on one spacing. Here the best step is{" "}
                {fmtNum(channel.step)} with R = {fmtNum(channel.rayleigh_R)}.
                For comparison, shuffled copies of these values scored this
                well {fmtExact(channel.null_exceedance)} of the time — the
                smaller that share, the less likely the fit is a coincidence.
              </p>
            </>
          ) : (
            <p className="note">
              {overlayChannel?.periodogram.reason ??
                "This chart was not produced for this measurement."}
            </p>
          )}

          <h3>How far is each value from its nearest step?</h3>
          {overlayChannel ? (
            <HistogramPlot
              edges={overlayChannel.residual_histogram.bin_edges}
              counts={overlayChannel.residual_histogram.counts}
              tolerance={overlayChannel.residual_histogram.tolerance}
              title={`Residual histogram for ${CHANNEL_LABELS[active] ?? active}`}
            />
          ) : (
            <p className="note">This chart was not produced for this measurement.</p>
          )}
          <p className="note">
            Bars near 0 mean values sit almost exactly on the spacing;
            bars far from 0 argue against it. The dashed lines mark the
            small “close enough” range. The typical distance from the
            spacing is {fmtNum(channel.rms_residual)}.
          </p>
        </div>
      )}

      {chart && (
        <div className="panel">
          <h3>Could this just be an ordinary chart? Score: {fmtNum(chart.score)} out of 1</h3>
          <Gauge score={chart.score} label={`How chart-like this picture looks: ${fmtNum(chart.score)} out of 1`} />
          <p className="note">
            Ordinary charts place their bars on regular spacings on
            purpose, so a regular spacing means much less when the picture
            looks like a chart. This score (0 = looks like a scene,
            1 = looks like a chart) is shown alongside the pattern result
            for that reason. A baseline (the line bars stand on) was{" "}
            {chart.baseline_present ? "found" : "not found"}.
          </p>
          <dl className="kv">
            {Object.entries(chart.features).map(([k, v]) => (
              <div key={k}>
                <dt title={k}>{humanizeKey(k)}</dt>
                <dd>{fmtExact(v)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {structure && (
        <div className="panel">
          <div className="card-head">
            <h3>Could this pattern be a coincidence?</h3>
            <span className={structure.claimed ? "badge badge-claimed" : "badge"}>
              {structure.claimed ? "Looks deliberately arranged" : "No deliberate pattern claimed"}
            </span>
          </div>
          <p className="note">
            The step numbers are read using a code that was declared in
            advance, then compared with many shuffled copies of the same
            numbers. If the real order looks far more organised than the
            shuffles, a deliberate pattern is reported — as evidence, never
            as decoded text.
          </p>
          <dl className="kv kv-wide">
            <div><dt>Code declared in advance</dt><dd>{fmtExact(structure.code)}</dd></div>
            <div><dt>How language-like the step numbers look (trigram score)</dt><dd>{fmtExact(structure.trigram_score)}</dd></div>
            <div><dt>Share of shuffles scoring this well (lower is stronger evidence)</dt><dd>{fmtExact(structure.null_exceedance)}</dd></div>
            <div><dt>Evidence balance for vs against a pattern (log-likelihood ratio)</dt><dd>{fmtExact(structure.log_likelihood_ratio)}</dd></div>
            <div><dt>Share of symbols that are printable characters</dt><dd>{fmtExact(structure.printable_fraction)}</dd></div>
          </dl>
          {structure.null_exceedance !== null && (
            <>
              <ScoreBar score={structure.null_exceedance} />
              <p className="note">
                The bar shows that “share of shuffles” on a 0-to-1 scale:
                shorter (lower) means shuffles rarely match the real
                order, which is stronger evidence of a deliberate pattern.{" "}
                {structure.reason ?? ""}
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
          <caption>
            Every measurement of the shapes, side by side, exactly as
            returned. “Fits spacing” = values fall on evenly spaced steps.
          </caption>
          <thead>
            <tr>
              <th scope="col">Measurement</th>
              <th scope="col">Step size found</th>
              <th scope="col">Quality of fit, R (1 is perfect)</th>
              <th scope="col">Share of shuffles fitting this well</th>
              <th scope="col">Shapes fitting / shapes measured</th>
              <th scope="col">Typical distance from the steps</th>
              <th scope="col">Different steps used</th>
              <th scope="col">Score (0 to 1)</th>
              <th scope="col">Fits a regular spacing?</th>
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
                  <td>{c.applicable ? (c.quantized ? "yes" : "no") : "does not apply to this file"}</td>
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
              Every shape that was measured, in reading order. Select a row
              to highlight that shape’s outline on the picture above. All
              positions and sizes are in pixels.
            </caption>
            <thead>
              <tr>
                <th scope="col">Shape number</th>
                <th scope="col">Distance from left edge</th>
                <th scope="col">Distance from top edge</th>
                <th scope="col">Width</th>
                <th scope="col">Height</th>
                <th scope="col">Gap to next shape</th>
                <th scope="col">Tilt angle (degrees)</th>
                <th scope="col">Colour number</th>
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
