// Small shared help patterns (CL-79): numbered starting steps and a
// collapsed "technical details" area. Essential guidance stays
// visible in the page itself; these only group optional depth so a
// first-time reader is not faced with raw field names first.

import type { ReactNode } from "react";

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
