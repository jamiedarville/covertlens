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
