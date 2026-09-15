# SPDX-License-Identifier: Apache-2.0
# Top-level Makefile: cocotb simulation, the reference-render check, the
# iCE40UP5K bitstream build, and keeping common/*.v in sync with each
# design's src/.

DESIGNS := $(notdir $(wildcard designs/*))


# sim-<design> and check-<design> are deliberately NOT listed here: naming a
# pattern-rule target in .PHONY creates an empty explicit rule for it, which
# GNU Make then prefers over the "sim-%"/"check-%" pattern rules below, so
# the recipe never runs. Leaving them unlisted still reruns them every time
# (the target name is never a real file), which is what we want anyway.
.PHONY: sim check build check-bitstreams sync-common

sim: $(addprefix sim-,$(DESIGNS))

sim-%:
	uv run make -C designs/$*/test

# Needs a sibling `vgacap` checkout built at ../vgacap/build (VGACAP env var
# overrides the location); see README.md.
check: $(addprefix check-,$(DESIGNS))

check-%:
	uv run python tools/check.py $*

# Needs oss-cad-suite (OSS_CAD_SUITE_BIN, default /home/tim/tools/oss-cad-suite/bin)
# and network access for the pinned tt-support-tools clone; rewrites
# bitstreams/*.bin and bitstreams/README.md. Not run in CI -- see
# check-bitstreams and .github/workflows/ci.yml.
build:
	uv run --no-project python tools/build.py

# The CI-side check on the committed bitstreams: real iCE40 preamble, under
# the board daemon's upload limit. No FPGA toolchain needed.
check-bitstreams:
	uv run --no-project python tools/check_bitstreams.py

sync-common:
	./scripts/sync_common.sh
