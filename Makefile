# SPDX-License-Identifier: Apache-2.0
# Top-level Makefile: cocotb simulation, the reference-render check, and
# keeping common/hvsync_generator.v in sync with each design's src/.

DESIGNS := $(notdir $(wildcard designs/*))


# sim-<design> and check-<design> are deliberately NOT listed here: naming a
# pattern-rule target in .PHONY creates an empty explicit rule for it, which
# GNU Make then prefers over the "sim-%"/"check-%" pattern rules below, so
# the recipe never runs. Leaving them unlisted still reruns them every time
# (the target name is never a real file), which is what we want anyway.
.PHONY: sim check sync-common

sim: $(addprefix sim-,$(DESIGNS))

sim-%:
	uv run make -C designs/$*/test

check: $(addprefix check-,$(DESIGNS))

check-%:
	uv run python tools/check.py $*

sync-common:
	./scripts/sync_common.sh
