"""Artifact route inventory (CL-7, EV-01/AC3).

Every way an eval-generated PNG/JPEG can travel from a producer to a
recipient inside the harness. CL-12 implements the single gate against
this list; CL-32 audits end-to-end coverage against it. A route is either
gated before recipient access or carries an explicit exception reason —
there is no silent third state.
"""

from __future__ import annotations

from dataclasses import dataclass

KINDS = ("file_reference", "tool_output", "artifact_access", "review_access")


@dataclass(frozen=True)
class Route:
    route_id: str
    kind: str  # one of KINDS
    name: str
    description: str
    carries: str  # "bytes", "reference" or "derivative"
    interception_point: str
    gate_required: bool = True
    exception_reason: str | None = None

    def validate(self) -> list[str]:
        errors = []
        if self.kind not in KINDS:
            errors.append(f"{self.route_id}: kind must be one of {KINDS}")
        if self.gate_required and self.exception_reason:
            errors.append(f"{self.route_id}: gated route must not carry an exception")
        if not self.gate_required and not self.exception_reason:
            errors.append(f"{self.route_id}: ungated route requires an exception reason")
        if not self.interception_point:
            errors.append(f"{self.route_id}: interception_point is required")
        return errors


ROUTES: tuple[Route, ...] = (
    Route(
        "R-01", "tool_output", "tool_output_image",
        "A tool returns image bytes (or an inline image) in its output to an agent.",
        "bytes", "artifact-store ingest on tool-output capture, before the output is attached to any recipient context",
    ),
    Route(
        "R-02", "tool_output", "tool_output_file_reference",
        "A tool writes an image file and returns its path or URI in tool output.",
        "reference", "reference resolution at artifact-store ingest; the referenced bytes are ingested as an immutable original before delivery",
    ),
    Route(
        "R-03", "file_reference", "agent_file_reference",
        "An agent message references an image by artifact ID, path or URI for another agent.",
        "reference", "message dispatch: every image reference is resolved and gated before the message reaches the recipient",
    ),
    Route(
        "R-04", "artifact_access", "artifact_store_direct_access",
        "A recipient fetches image bytes directly from the artifact store by artifact ID/version.",
        "bytes", "artifact-store read path: no bytes are served before a permitting verdict for that exact version/hash",
    ),
    Route(
        "R-05", "artifact_access", "cached_link_access",
        "A recipient opens a previously issued cached or signed link to image bytes.",
        "bytes", "link redemption: the link resolves to an artifact version and is gated exactly like a direct fetch (CL-18)",
    ),
    Route(
        "R-06", "artifact_access", "preview_derivative_access",
        "A preview, thumbnail or other transform of an image is requested.",
        "derivative", "derivative generation reads the gated original only; a withheld original yields no derivative",
    ),
    Route(
        "R-07", "artifact_access", "recipient_parse_input",
        "Image bytes are handed to a recipient vision/parser component for consumption.",
        "bytes", "parser hand-off: parse events link to the delivery and verdict; withheld artifacts record parse not_observed",
    ),
    Route(
        "R-08", "review_access", "reviewer_evidence_access",
        "An authorized researcher/reviewer opens quarantined originals and evidence for triage.",
        "bytes", "evidence store read path with dataset/project permission checks and audited reads (REV-06); never a recipient delivery path",
        gate_required=False,
        exception_reason="Reviewer-only evidence access under permission checks and audit (CL-11/CL-33); it cannot deliver bytes to a run recipient, so the delivery gate does not apply.",
    ),
)


def routes_by_kind(kind: str) -> list[Route]:
    return [r for r in ROUTES if r.kind == kind]


def validate_inventory(routes: tuple[Route, ...] = ROUTES) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for route in routes:
        if route.route_id in seen:
            errors.append(f"duplicate route_id: {route.route_id}")
        seen.add(route.route_id)
        errors.extend(route.validate())
    kinds = {r.kind for r in routes}
    for required in ("file_reference", "tool_output"):
        if required not in kinds:
            errors.append(f"inventory must cover kind: {required} (AC3)")
    return errors
