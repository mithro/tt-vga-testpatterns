# SPDX-License-Identifier: Apache-2.0
"""Compare frames reconstructed from a real hardware capture against a
calibration design's reference render, pixel by pixel.

    uv run --no-project --with numpy --with pillow python tools/compare_capture.py \
        tt_um_vgacal_bars /path/to/frames/f-0005.ppm
    uv run ... tools/compare_capture.py tt_um_vgacal_counter /path/to/f-0003.ppm
    uv run ... tools/compare_capture.py tt_um_vgacal_modes /path/to/f-0002.ppm --ui-in 1

This is the hardware counterpart of `tools/check.py`, which does the same
comparison against a simulation. Designs that draw their own frame counter
(counter, prbs) have their reference chosen by the counter decoded from the
picture, exactly as check.py does. Exits 1 on any mismatching pixel and says
where the first ones are.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tools import check, render  # noqa: E402


def read_ppm(path: pathlib.Path) -> np.ndarray:
    """Parse a binary PPM (P6) into an (h, w, 3) uint8 array."""
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


def reference(design: str, got6: np.ndarray, ui_in: int) -> tuple[np.ndarray, str]:
    """The 6-bit reference picture this frame should equal, and how it was chosen."""
    if design in check.REFERENCE_RENDERS:
        return check.REFERENCE_RENDERS[design](), "fixed picture"
    if design in check.FRAME_COUNTER_RENDERS:
        row = check.FRAME_COUNTER_ROW[design]
        counter = check.decode_frame_counter(got6, row)
        return check.FRAME_COUNTER_RENDERS[design](counter), f"frame counter {counter} decoded from the picture"
    if design in check.MODE_CASES:
        return render.modes(ui_in), f"ui_in={ui_in:#x}"
    raise SystemExit(f"{design}: no reference renderer")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("design")
    ap.add_argument("frame", type=pathlib.Path)
    ap.add_argument("--ui-in", type=int, default=0, help="ui_in value for tt_um_vgacal_modes")
    a = ap.parse_args()

    got = read_ppm(a.frame)
    got6 = check.rgb_to_img6(got)
    want6, how = reference(a.design, got6, a.ui_in)
    want = render.to_rgb(want6)
    print(f"{a.design}: captured {got.shape[1]}x{got.shape[0]}, reference {want.shape[1]}x{want.shape[0]} ({how})")
    if got.shape != want.shape:
        print("FAIL: size mismatch")
        return 1
    bad = np.argwhere(np.any(got != want, axis=-1))
    total = got.shape[0] * got.shape[1]
    if len(bad):
        print(f"FAIL: {len(bad)} mismatching pixels of {total}")
        for y, x in bad[:10]:
            print(f"  ({x}, {y}): captured {tuple(int(v) for v in got[y, x])}, reference {tuple(int(v) for v in want[y, x])}")
        return 1
    print(f"PASS: {total} pixels identical to the reference render")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
