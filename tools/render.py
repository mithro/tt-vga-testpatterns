# SPDX-License-Identifier: Apache-2.0
"""Reference renderers for the vgacal_* calibration designs.

Each function returns a numpy uint8 array of shape (h, w) holding the 6-bit
Tiny VGA colour value (bits 5..0 = rr gg bb) that the design should draw at
that pixel -- this is compared pixel-exactly against a simulated-and-
reconstructed capture by tools/check.py.
"""
from __future__ import annotations

import pathlib

import numpy as np
from PIL import Image


def bars(w: int = 640, h: int = 480) -> np.ndarray:
    """64 vertical bars, 10 px wide each: colour index = (x // 10) & 0x3F."""
    x = np.arange(w, dtype=np.uint16)
    row = ((x // 10) & 0x3F).astype(np.uint8)
    return np.tile(row, (h, 1))


def grid(w: int = 640, h: int = 480) -> np.ndarray:
    """White (0x3F) 8-pixel grid and a 1-px border, dark red (0x10) elsewhere."""
    x = np.arange(w, dtype=np.int32).reshape(1, w)
    y = np.arange(h, dtype=np.int32).reshape(h, 1)
    white = (
        (x % 8 == 0)
        | (y % 8 == 0)
        | (x == 0)
        | (x == w - 1)
        | (y == 0)
        | (y == h - 1)
    )
    # `white` is already (h, w) -- x (1, w) and y (h, 1) broadcast against
    # each other in the OR expression above -- so np.where needs no further
    # broadcasting.
    return np.where(white, 0x3F, 0x10).astype(np.uint8)


def to_rgb(img6: np.ndarray) -> np.ndarray:
    """Expand a 6-bit (rr gg bb) image to 8-bit RGB, levels 0/85/170/255."""
    levels = np.array([0, 85, 170, 255], dtype=np.uint8)
    r = levels[(img6 >> 4) & 0x3]
    g = levels[(img6 >> 2) & 0x3]
    b = levels[img6 & 0x3]
    return np.stack([r, g, b], axis=-1)


def save_png(img6: np.ndarray, path: str | pathlib.Path) -> None:
    Image.fromarray(to_rgb(img6), mode="RGB").save(path)
