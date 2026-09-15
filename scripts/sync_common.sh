#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Copy common/hvsync_generator.v into every design's src/, since the Tiny
# Tapeout hardening flow only reads a design's own src/ directory (it does
# not know about common/). common/hvsync_generator.v remains the single
# source of truth; run this script (or `make sync-common`) after editing it.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$repo_root/common/hvsync_generator.v"

for design_src in "$repo_root"/designs/*/src; do
    [ -d "$design_src" ] || continue
    cp "$src" "$design_src/hvsync_generator.v"
    echo "synced -> ${design_src#"$repo_root"/}/hvsync_generator.v"
done
