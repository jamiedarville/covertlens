# Latency, resource limits and gate reliability contract (CL-29)

Implements: CL-29. Measures the frozen pipeline
(`analyze_and_decide`, the shipped freeze — `frozen-1.2.0` since
CL-78) on a documented pilot workload. Schema:
[schemas/latency-reliability.schema.json](../../schemas/latency-reliability.schema.json).

## Pilot workload and proposal

Agreed concurrency: 4 workers. Size classes (PNG/JPEG):
small 256×192, medium 512×384, large 1024×768, envelope
5000×4000 (20 MP, PNG only). Proposed target: P95 overhead ≤ 2 s
for ≤ 10 MB / 20 MP images.

## Current measurement (CL-78)

The published numbers are the `latency_reliability` section of
`config/release-scorecard.json`, re-measured whenever the scorecard is
rebuilt (`make refreeze`), on the default pure-Python path. The
scorecard's published-vs-built test compares every section except
this one, because timings are machine-dependent; so a slower
pipeline can go unnoticed until the next republish. That is what
happened twice:

- **Large PNG, met → missed.** The CL-35 scorecard (0.07 s) was
  measured before the geometric family existed. CL-44 added
  segmentation to every PNG/JPEG analysis (about 2.7 s of the 2.9 s
  for 1024×768), and the latency section was not re-measured until
  CL-55–CL-57, which first showed the miss. The miss is correct for
  the current pipeline.
- **20 MP envelope PNG, met → missed.** CL-61 added the sample-pair
  LSB detector to every analysis; its pair count is about 7.4 s of
  pure Python on 20 MP. The envelope's segmentation stops at the
  2 MP segmenter cap, so the geometric family is not the cost here.

With `COVERTLENS_FAST_PATH=numpy` (`covertlens[fast]`, exact; CL-78
adds the sample-pair counts to it) large PNG measures about 1.5 s and
the envelope about 0.6 s on the CL-78 machine. The default stays the
dependency-free reference path, and the scorecard reports it.

## Measured results at CL-29 (historical, 5 repetitions/class)

| Class | Media | P95 | Outcome |
|---|---|---|---|
| small | PNG / JPEG | 0.005 s / 0.18 s | meets proposal |
| medium | PNG / JPEG | 0.017 s / 0.75 s | meets proposal |
| large | PNG | 0.30 s | meets proposal |
| large | JPEG | 2.01 s, all `timeout` | **misses**: explicit timeout at the CL-13 2 s deadline |
| envelope 20 MP | PNG | 1.77 s | meets proposal |
| medium JPEG × 4 workers | JPEG | 2.63 s, 10/12 `timeout` | **misses under concurrency** (GIL contention inflates wall-clock per item past the deadline) |

## Explicit tradeoffs (no universal claim)

- The ≤2 s P95 proposal holds for PNG at every measured class
  including 20 MP, and for JPEG up to medium sequential. It does
  **not** hold for JPEG ≥ ~1 MP or for medium JPEG at concurrency 4.
- A 20 MP JPEG is **not measured**: the pure-Python encoder cannot
  generate one in reasonable time. Recorded as narrowed coverage,
  not a pass.
- Timeouts are safe but not free: they withhold delivery as
  infrastructure outcomes (`analysis_timeout`), consuming
  availability. A faster JPEG path (or a higher, explicitly
  re-frozen runtime limit) is required before claiming the JPEG
  envelope.

## Reliability properties (all hold)

- Timeout → status `timeout` / error class `analysis_timeout`;
  oversize → `oversized` / `oversized_input`. In enforcement mode
  both withhold delivery, record `failed_infrastructure`, produce
  no clean verdict, and serve zero bytes.
- Under concurrent route + cached-link attempts (8 threads),
  only verdict-permitted deliveries are served (12/36 route
  attempts = exactly the permitted set); `unauthorized_served: 0`.

## Verification

`python -m covertlens latency-demo` prints the assessment summary;
`tests/test_latency.py` re-measures the small classes and asserts
the limit and concurrency properties.
