// Small shared help patterns (CL-79): numbered starting steps, a
// collapsed "technical details" area, and the links that reveal a
// page's technical breakdown or advanced settings. Essential guidance
// stays visible in the page itself; these only group optional depth
// so a first-time reader is not faced with raw field names first.

import { useState, type ReactNode } from "react";

export function StartSteps({
  heading = "Start here",
  children,
}: {
  heading?: string;
  children: ReactNode;
}) {
  return (
    <div className="start-steps">
      <h2 className="start-steps-heading">{heading}</h2>
      <ol>{children}</ol>
    </div>
  );
}

export function TechDetails({
  summary = "Technical details (exact values, for specialists)",
  children,
}: {
  summary?: string;
  children: ReactNode;
}) {
  return (
    <details className="tech-details">
      <summary>{summary}</summary>
      {children}
    </details>
  );
}

// A link-style button that shows or hides a block. The block is always
// rendered (hidden until opened) so form values and chart choices
// inside it survive closing and reopening it.
export function Reveal({
  id,
  showLabel,
  hideLabel,
  note,
  initiallyOpen = false,
  children,
}: {
  id: string;
  showLabel: string;
  hideLabel: string;
  note?: string;
  initiallyOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <div className="reveal">
      <p className="technical-toggle">
        <button
          type="button"
          className="link-button"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? hideLabel : showLabel}
        </button>
        {note && <span className="note"> — {note}</span>}
      </p>
      <div id={id} hidden={!open}>
        {children}
      </div>
    </div>
  );
}

// The page-level "technical breakdown": exact values, IDs, records and
// charts for specialists, under one link at the end of the page.
export function TechnicalBreakdown({
  id = "technical-breakdown",
  note = "exact values, IDs and records, for specialists",
  initiallyOpen,
  children,
}: {
  id?: string;
  note?: string;
  initiallyOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <Reveal
      id={id}
      showLabel="See the technical breakdown"
      hideLabel="Hide the technical breakdown"
      note={note}
      initiallyOpen={initiallyOpen}
    >
      <section className="technical-evidence" aria-label="Technical breakdown">
        {children}
      </section>
    </Reveal>
  );
}

// Optional form settings that most people never need to change.
export function AdvancedSettings({
  id,
  note = "for specialists; the defaults are fine",
  children,
}: {
  id: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <Reveal id={id} showLabel="Show advanced settings" hideLabel="Hide advanced settings" note={note}>
      <div className="advanced-settings">{children}</div>
    </Reveal>
  );
}
