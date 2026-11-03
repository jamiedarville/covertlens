# CovertLens operator targets (CL-65).
PYTHON ?= python3

.PHONY: refreeze
refreeze: ## Recalibrate, bump the frozen config version, regenerate the scorecard
	COVERTLENS_BUILD_WORKERS=auto $(PYTHON) scripts/refreeze.py $(REFREEZE_ARGS)
