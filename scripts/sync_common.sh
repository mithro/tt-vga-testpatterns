#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Refresh each design's copy of the shared modules in common/, since the
# Tiny Tapeout hardening flow only reads a design's own src/ directory (it
# does not know about common/). common/ remains the single source of truth;
# run this script (or `make sync-common`) after editing anything in it.
#
# A common module is copied into a design's src/ only if that design
# *already* has a copy of it, i.e. this refreshes existing copies rather
# than handing every design every shared module: designs pick different
# timing generators (hvsync_generator.v vs hvsync_generator_mux.v), and an
# unused extra .v in src/ would be compiled by tools/check.py (which globs
# src/*.v) and listed in the hardening flow for no reason. Seed a new
# design's first copy by hand: cp common/<module>.v designs/<d>/src/.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for src in "$repo_root"/common/*.v; do
    [ -f "$src" ] || continue
    name="$(basename "$src")"
    for design_src in "$repo_root"/designs/*/src; do
        [ -f "$design_src/$name" ] || continue
        cp "$src" "$design_src/$name"
        echo "synced -> ${design_src#"$repo_root"/}/$name"
    done
done
