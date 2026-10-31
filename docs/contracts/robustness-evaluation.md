# Adaptive and unseen-configuration evaluation contract (CL-34)

Implements: CL-34. Schema:
[schemas/robustness-evaluation.schema.json](../../schemas/robustness-evaluation.schema.json).
Kept strictly separate from the CL-28 frozen benchmark
(`separate_from_frozen_benchmark: true`,
`merged_into_frozen_claim: false`): these probes bound the frozen
claims, they never improve them.

## Results under `frozen-1.0.0`

| Experiment | Outcome |
|---|---|
| Adaptive reduced-rate LSB (2/4/8 B) | `evaded_below_enforcement` — triage at best, never withheld |
| Adaptive allowed-keyword metadata (Description/Title) | `evaded` — score 0 by CL-23 design; a policy change, not recalibration, closes it |
| Low-signal sequence (6 × 8 B, one sender) | nothing withheld; repetition visible only in the CL-30 weak-signal view |
| Unseen JPEG quality 50 / 75 | `detected` (fail_run) at probed rates |
| Unseen cover pattern `blocks` | `evaded` — texture shift drops the same payload below triage |
| Unseen cover pattern `smooth` | `confounded_unresolved` — clean control fails identically (CL-28), no claim possible |
| Unseen 128×96 images (same 64 B payload) | `evaded` — payload *density* drives the score; 4× pixels falls below triage |

## Documented limitations

- Frozen coverage is bounded to suite-like payload densities and
  the `gradient_noise` cover family; reduced-rate, larger-image,
  blocks-cover and allowed-keyword attempts sit outside it.
- Each unseen configuration is a 1–6 case probe — directional
  evidence, not a rate estimate.
- Confounded smooth-cover results stay unresolved; no detector
  claim is made where clean controls fail the same way.
- Adaptive success here is measured against the *detector*, by an
  experiment-side adversary with scorer-side truth (C-07); it is
  not evidence about any real sender (C-02).

## Verification

`python -m covertlens robustness-demo` prints experiment outcomes;
`tests/test_robustness.py` asserts the separation flags, the
evasions, the confounded case, and the low-signal sequence.
