# Benchmarks and Scorecard (CL-55)

`/benchmarks` shows cached library reports; `/scorecard` shows the published
release assessment. The existing CLI handlers are the only report producers.
`scripts/precompute.py` serializes their complete payloads with the CLI JSON
serializer; the benchmark HTTP endpoints serve those bytes directly. Display
values retain the source decimal precision. SVG coordinates scale those values
for presentation; tables and downloadable JSON preserve the numbers.

The report views separate the frozen held-out evaluation, development ROC
sweeps, geometric subfamilies, ablations, measured latency and robustness probes.
Robustness never enters a frozen chart or row. ROC views select payload bands
and show Wilson intervals at each threshold. The geometric view has continuous,
quantized unstructured and quantized structured rows for every subfamily.

`GET /api/benchmarks/{lsb,dct,metadata,frozen,geometric,ablations,latency,robustness}`
returns report JSON, or 202 while computing. Unknown names return 404.
`metadata` retains the CLI's `{rows, benchmark}` payload. `scorecard` and
`provenance` are also available by name. `/api/scorecard` remains the published
artifact, available before background computations finish.

`provenance.json` records library version, frozen configuration version,
parser version, backend, git SHA, source command and compute/cache date per
report. The scorecard source is explicitly labelled a published artifact;
its timestamp is when it was loaded into the cache. Every chart shows the
library, configuration and date. Writes use temporary files plus atomic rename;
the cache key is committed last. A key mismatch yields 202, so old-version
reports cannot appear under the running version. Cache generation runs once
in the background and can take several minutes, especially the latency report.

Verification: Python tests compare cached serialization with real CLI handler
payloads and exercise HTTP cache invalidation; `npm test` renders the result
views and checks precise decimals, provenance and frozen/robustness isolation.
