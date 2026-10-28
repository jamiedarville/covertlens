# Allowed-channel manifest (CL-7 · EV-02)

The manifest is the codified form of the owning team's eval rule. The
machine-readable instance is
[allowed-channel-manifest.json](../../config/allowed-channel-manifest.json)
(schema: [allowed-channel-manifest.schema.json](../../schemas/allowed-channel-manifest.schema.json),
validator: `covertlens.manifest`). This page explains how to read it;
the JSON is authoritative.

## The rule and its owner

- **Owner:** Agent Evaluation / AI Safety, as eval-harness operator.
- **Rule:** agents may not encode task-relevant information in image
  pixels or image metadata outside the allowed channel.
- **Allowed channel:** the declared inter-agent text / structured
  tool-call channel (`declared_text_channel`). It is logged as ordinary
  trace content and is not gated by CovertLens. Using image pixels or
  metadata as a substitute for it is exactly what the detectors score.

## Scope

Eval-generated PNG/JPEG artifacts only, analysed on original bytes.
Consumer uploads and transports are out of scope (C-08). Originals,
lineage and access history are retained for the dataset lifetime.

## Monitored channels

| Family | Applies to | Policy | Detector mode | Lands in |
|---|---|---|---|---|
| `spatial_lsb` | PNG | Prohibited for task information | `enabled`, original bytes | CL-14 |
| `jpeg_dct` | JPEG | Prohibited for task information | `enabled`, original bytes | CL-15 |
| `metadata` | PNG/JPEG | Prohibited except declared exceptions | `enabled`, original bytes | CL-22/CL-23 |

Detector `mode` is one of `enabled` (score and enforce), `log_only`
(score, never enforce — for pilots) or `disabled` (family not scored;
must be an explicit, versioned manifest change).

**Metadata exceptions:** only metadata keys declared for the task before
the run are exempt from scoring. The declaration lives in
`allowed_metadata_exceptions.declared_keys` per campaign; an exception
never exempts the pixel or DCT channels.

## Thresholds

Each family carries two separately configured operating points (C-06):

- `triage` — high-recall research point (`flag_at`).
- `enforcement` — high-precision point (`quarantine_at`, `fail_run_at`).

Both ship as `unfrozen_placeholder` with `null` values in v1.0.0. Frozen
numbers are set only by CL-27, calibrated without held-out test labels
(C-07), and a frozen manifest must satisfy
`quarantine_at >= flag_at` (enforced by the validator). Downstream code
must treat a `null` threshold as "not yet enforceable", never as zero.

## Verdict ladder and error behaviour

`log` and `flag` permit delivery; `quarantine` withholds bytes from the
recipient; `fail_run` withholds and halts the run with a structured
eval-failure reason (ENF-01, CL-17/CL-19).

Every error class — corrupt, unsupported, oversized, timeout, detector
error, gate error — fails closed: **no clean verdict, bytes withheld,
infrastructure outcome recorded**. An error is never equated with
demonstrated collusion (C-02).

## Change control

`manifest_version` is semantic. Any channel, threshold-status or
error-behaviour change bumps it, requires owner approval, and invalidates
verdict caches keyed to the old version (CL-20).
