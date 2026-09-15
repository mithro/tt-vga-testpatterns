# SPDX-License-Identifier: Apache-2.0
"""Compare a reconstructed frame from a real capture against a calibration
design's reference render, pixel by pixel.

    uv run --no-project --with numpy --with pillow python tools/compare_capture.py \
        tt_um_vgacal_bars frame.ppm

Exits 1 on any mismatching pixel and prints where the first ones are, so a
hardware capture is held to exactly the same standard as the simulation
checks in tools/check.py.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tools import render  # noqa: E402


def read_ppm(path: pathlib.Path) -> np.ndarray:
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        raise SystemExit(f"{path}: not a binary PPM")
    fields: list[int] = []
    pos = 2
    while len(fields) < 3:
        while pos < len(data) and data[pos : pos + 1].isspace():
            pos += 1
        if data[pos : pos + 1] == b"#":
            while data[pos : pos + 1] not in (b"\n", b""):
                pos += 1
            continue
        start = pos
        while pos < len(data) and not data[pos : pos + 1].isspace():
            pos += 1
        fields.append(int(data[start:pos]))
    pos += 1
    w, h, _maxval = fields
    return np.frombuffer(data, dtype=np.uint8, count=w * h * 3, offset=pos).reshape(h, w, 3)


REFERENCE = {
    "tt_um_vgacal_bars": lambda: render.bars(),
    "tt_um_vgacal_grid": lambda: render.grid(),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design", choices=sorted(REFERENCE))
    ap.add_argument("frame", type=pathlib.Path)
    a = ap.parse_args()

    got = read_ppm(a.frame)
    want = render.to_rgb(REFERENCE[a.design]())
    print(f"captured {got.shape[1]}x{got.shape[0]}, reference {want.shape[1]}x{want.shape[0]}")
    if got.shape != want.shape:
        print("FAIL: size mismatch")
        return 1
    bad = np.argwhere(np.any(got != want, axis=-1))
    if len(bad):
        print(f"FAIL: {len(bad)} mismatching pixels of {got.shape[0] * got.shape[1]}")
        for y, x in bad[:10]:
            print(f"  ({x}, {y}): captured {tuple(got[y, x])}, reference {tuple(want[y, x])}")
        return 1
    print(f"PASS: {got.shape[0] * got.shape[1]} pixels identical to the reference render")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
