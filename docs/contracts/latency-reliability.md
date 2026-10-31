# Latency, resource limits and gate reliability contract (CL-29)

Implements: CL-29. Measures the frozen pipeline
(`analyze_and_decide`, `frozen-1.0.0`) on a documented pilot
workload. Schema:
[schemas/latency-reliability.schema.json](../../schemas/latency-reliability.schema.json).

## Pilot workload and proposal

Agreed concurrency: 4 workers. Size classes (PNG/JPEG):
small 256×192, medium 512×384, large 1024×768, envelope
5000×4000 (20 MP, PNG only). Proposed target: P95 overhead ≤ 2 s
for ≤ 10 MB / 20 MP images.

## Measured results (this harness, 5 repetitions/class)

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
