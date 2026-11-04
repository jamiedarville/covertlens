# Campaign log (CL-65)

One append-only entry per campaign-affecting change: a freeze, a
rollback, a pin change, or a scorecard regeneration. Newest last.
Never edit a past entry — record a correction as a new entry.

## Template — copy this for each entry

```markdown
### YYYY-MM-DD — <short title>

- **Change:** freeze | rollback | pin | scorecard | other
- **Frozen config:** <version before> -> <version after> (`COVERTLENS_FROZEN_CONFIG=<path>` if not the default)
- **Pin hash:** `sha256:...` (from `config/release-scorecard.json`)
- **Reason:** <why, in one or two lines>
- **Tests:** <command run and result>
- **Announced to:** <campaign channel / who was told>
```

## Entries

### 2026-11-03 — Campaign log created (CL-65)

- **Change:** other
- **Frozen config:** frozen-1.1.0 (unchanged, default `config/frozen-thresholds.json`)
- **Pin hash:** recorded in `config/release-scorecard.json` (`pin_hash`)
- **Reason:** CL-65 closes the runbook gap: rollbacks and re-freezes are now announced here, by convention.
- **Tests:** see the CL-62–CL-65 pull request.
- **Announced to:** campaign operators via the operations runbook.

### 2026-11-03 — Banded recalibration to frozen-1.3.0 (CL-68)

- **Change:** freeze
- **Frozen config:** frozen-1.1.0 -> frozen-1.3.0 (default `config/frozen-thresholds.json`; `frozen-1.2.0` skipped, the unmerged CL-78 branch uses that label)
- **Pin hash:** `sha256:584ffeccde76b1f51daa8758bcc795dbbbb81f27ea7b0cc0ceab4c0aac7b3cef` (from `config/release-scorecard.json`)
- **Reason:** CL-68 banded suite (dozens of development pairs per band) and refined triage/fail-run selection rules for LSB/DCT/metadata; geometric points unchanged. Stability now measured on all three cover textures; smooth PNG and blocks JPEG are named exclusions.
- **Tests:** `COVERTLENS_BUILD_WORKERS=auto pytest -q -m "not slow"`; see the CL-66–CL-70 pull request.
- **Announced to:** pending — announce to campaign operators when the CL-66–CL-70 pull request merges.

### 2026-11-03 — Geometric re-freeze to frozen-1.4.0 (CL-78)

- **Change:** freeze
- **Frozen config:** frozen-1.3.0 -> frozen-1.4.0 (default `config/frozen-thresholds.json`; `frozen-1.2.0` stays skipped)
- **Pin hash:** `sha256:3a660ad6a21121feafc8b5fd8eb425ee30569407b9c4a7b6c6fecc6b3149551f` (from `config/release-scorecard.json`)
- **Reason:** geometric detector 3.0.0 (CL-78 sections 2–6): decode-margin quantization, structure tested on every decodable channel, varied structured fixtures from disjoint payload pools. Geometric points move to triage 0.381814 / quarantine 0.696774 / fail-run 1.0; the quarantine point is calibrated above the non-structure score ceiling (0.5). LSB, DCT and metadata points are unchanged from frozen-1.3.0, and no scorecard target changed.
- **Tests:** `make refreeze REFREEZE_ARGS="--version frozen-1.4.0"`, then `pytest -m "not slow"`; see the CL-78 sections 2–6 pull request.
- **Announced to:** pending — announce to campaign operators when the CL-78 pull request merges.
