#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sanity-check the committed bitstreams in bitstreams/.

    uv run --no-project python tools/check_bitstreams.py

Building a bitstream needs oss-cad-suite (a multi-gigabyte download), so
tools/build.py does not run in CI; the .bin files are committed instead and
CI checks them here. This verifies, for every design in designs/:

- a bitstreams/<design>.bin exists;
- it starts with the iCE40 bitstream preamble 7E AA 99 7E (within the first
  64 bytes, after the 0xFF padding an icepack output begins with), so a
  truncated, empty, text or otherwise wrong file cannot be committed
  unnoticed;
- it is smaller than 256 KiB, the limit the Welland board daemon accepts
  for an upload.

It deliberately does not try to validate the bitstream's contents: only a
real build can do that, and a real build is what produced these files.
This script is stdlib-only so it runs under `uv run --no-project`.
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DESIGNS_DIR = REPO_ROOT / "designs"
BITSTREAMS_DIR = REPO_ROOT / "bitstreams"

# The iCE40 configuration preamble, as emitted by icepack. It follows a
# short run of 0xFF padding, hence the search window rather than a prefix
# comparison.
PREAMBLE = bytes([0x7E, 0xAA, 0x99, 0x7E])
PREAMBLE_WINDOW = 64
MAX_SIZE = 256 * 1024


def designs() -> list[str]:
    return sorted(p.name for p in DESIGNS_DIR.iterdir() if (p / "info.yaml").is_file())


def check(design: str) -> list[str]:
    """Problems with this design's bitstream; empty means it is fine."""
    path = BITSTREAMS_DIR / f"{design}.bin"
    if not path.is_file():
        return [f"{path.relative_to(REPO_ROOT)}: missing (run tools/build.py)"]

    problems = []
    size = path.stat().st_size
    head = path.read_bytes()[:PREAMBLE_WINDOW]
    offset = head.find(PREAMBLE)
    if offset < 0:
        problems.append(
            f"{path.relative_to(REPO_ROOT)}: no iCE40 preamble "
            f"{PREAMBLE.hex(' ').upper()} in the first {PREAMBLE_WINDOW} bytes "
            f"(starts with {head[:8].hex(' ').upper()})"
        )
    if size >= MAX_SIZE:
        problems.append(
            f"{path.relative_to(REPO_ROOT)}: {size} bytes, over the "
            f"{MAX_SIZE} byte ({MAX_SIZE // 1024} KiB) upload limit"
        )
    if not problems:
        print(f"OK   {path.relative_to(REPO_ROOT)}: {size} bytes, preamble at offset {offset}")
    return problems


def main() -> int:
    if not BITSTREAMS_DIR.is_dir():
        print(f"no {BITSTREAMS_DIR.relative_to(REPO_ROOT)}/ directory", file=sys.stderr)
        return 1
    names = designs()
    if not names:
        print(f"no designs found in {DESIGNS_DIR.relative_to(REPO_ROOT)}/", file=sys.stderr)
        return 1

    problems = [p for design in names for p in check(design)]
    for problem in problems:
        print(f"FAIL {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"PASS ({len(names)} bitstreams)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
