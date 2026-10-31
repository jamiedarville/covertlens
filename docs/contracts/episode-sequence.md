# Episode context and sequence detection (CL-24 · REV-03/REV-04)

`covertlens.sequence` builds the within-run context that single-
artifact detectors cannot see, from the CL-16 trace join.

## Within-run persistence, never across runs

`build_episode_context(events, results)` returns one context per
run: every delivery (with per-family findings scores), every
recipient action, `participants` keyed by agent identity with their
sent/received/action history across *all* episodes of the run, and
`episodes` grouping deliveries and actions per episode. Multi-run
input raises through the CL-16 join — contexts never merge unrelated
runs (REV-02), and separate runs stay separate contexts.

## Gating uses only available evidence

`sequence_features(context, sender_id, recipient_id, through_seq)`
counts only deliveries attempted and actions taken at or before the
caller's `through_seq`. The cutoff is recorded on every assessment,
so a pre-delivery gate can consume sequence context without ever
touching a future recipient action (C-03, REV-04). Ordering is by
trace `seq`, never wall-clock.

## Three scorers, benchmarked separately

- **image-only:** the current artifact's max family score;
- **context-only:** repetition and follow-up pressure
  (delivered priors + prior actions), using no image scores at all;
- **combined:** noisy-OR of image-only, the strongest prior image
  score, and context-only.

`benchmark_sequences` reports ROC-AUC for each over labelled
sequence cases, so the marginal value of context over images (and
vice versa) is measured, not asserted. A combined assessment is an
aid for the CL-17 ladder and researcher review; it is not itself a
verdict, and `causation_claimed` stays false throughout (REV-01).

## Out of scope here

Researcher reports (CL-25), ablation comparisons (CL-31) and
threshold freezing for sequence scores (CL-27) are separate tasks.
