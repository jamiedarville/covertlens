# Shared helpers consolidation (CL-63)

Behaviour-preserving consolidation; no detector, threshold, or
verdict changes.

- `covertlens/_stats.py` — Wilson, ROC-AUC, average precision,
  percentile, bootstrap interval, score summary (formerly private
  helpers in `lsb`, imported across modules by private name).
- `covertlens/_png.py` — PNG save/load/render bytes (formerly
  private helpers in `fixtures`). Fixture bytes are unchanged.
- `covertlens/_validation.py` — the `need()` error collector
  (`make_need`), the single UTC `now_iso()` (formerly three `_now`
  copies), and the canonical JSON/hash shared by pinning and the
  audit log.
- No module imports a private name from another module (enforced
  by `tests/test_shared_helpers.py` over the AST of `covertlens/`,
  `app/` and `scripts/`, relative and absolute imports; CL-78), and
  `now_iso` and `need` are each defined once, in `_validation`.
- Magic numbers moved into versioned configs: sequence context
  weights (`SequenceConfig`), replay seed stride
  (`ReplayConfig.seed_stride`), pinning agreement bound
  (`AGREEMENT_MIN_DEFAULT`), metadata payload-size constants
  (`MetadataConfig.payload_size_*`); geometric weak floor/support
  fraction already lived in `GeometricConfig`. `latency.percentile`
  uses `math.ceil` instead of `+0.999999`, after rounding away float
  noise (`0.07 * 100` is `7.000000000000001`; CL-78).
- `events.Event` is a frozen dataclass; the pilot adjudications
  dict is defined once (`pilot.DEFAULT_ADJUDICATIONS`);
  `report.build_run_report` joins the trace once; `handoff`
  loads the frozen thresholds and builds the dataset once.
