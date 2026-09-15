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


def _counter_strip(frame: int, w: int, rows: int) -> np.ndarray:
    """The frame-counter strip shared by counter() and prbs(): `rows` tall,
    8 blocks of `w // 8` px wide (w must be a multiple of 8), block i shows
    bit (7-i) of `frame` (MSB first) -- white (0x3F) if set, blue (0x03) if
    clear."""
    assert w % 8 == 0
    blk_w = w // 8
    x = np.arange(w)
    blk = x // blk_w
    bits = (frame >> (7 - blk)) & 1
    row = np.where(bits, 0x3F, 0x03).astype(np.uint8)
    return np.tile(row, (rows, 1))


def counter(frame: int, w: int = 640, h: int = 480) -> np.ndarray:
    """tt_um_vgacal_counter's picture for a given 8-bit frame counter value:

    - Rows 0..59: the 8-bit frame counter as eight 80x60 blocks (see
      _counter_strip).
    - Rows 60..479: in every 40-line band starting at y = 60 + 40*k, the
      first 20 rows show the 9-bit line number of that band's first row
      (60 + 40*k) as nine 60x20 blocks (x in [60*j, 60*j+60), bit 8-j, MSB
      first); the rest of the band, and x >= 540, are black.
    """
    frame &= 0xFF
    img = np.zeros((h, w), dtype=np.uint8)

    img[0:60, :] = _counter_strip(frame, w, 60)

    xj = np.arange(w)
    blk9 = xj // 60  # exceeds 8 for x >= 540: masked out below
    for band_start in range(60, h, 40):
        bits9 = (band_start >> (8 - blk9)) & 1
        row = np.where(blk9 < 9, np.where(bits9, 0x3F, 0x03), 0x00).astype(np.uint8)
        row_end = min(band_start + 20, h)
        img[band_start:row_end, :] = row
    return img


def _lfsr_pixels(seed: int, count: int) -> np.ndarray:
    """`count` samples of the low 6 bits of the 16-bit Fibonacci LFSR
    (x^16+x^14+x^13+x^11+1) starting at `seed` (the first sample is the low
    6 bits of `seed` itself, unadvanced), advancing once per sample:
    bit = s[0]^s[2]^s[3]^s[5]; s <= (s >> 1) | (bit << 15). Matches the
    Verilog in tt_um_vgacal_prbs/src/project.v exactly."""
    out = np.empty(count, dtype=np.uint8)
    s = seed & 0xFFFF
    for i in range(count):
        out[i] = s & 0x3F
        bit = (s ^ (s >> 2) ^ (s >> 3) ^ (s >> 5)) & 1
        s = (s >> 1) | (bit << 15)
    return out


def prbs(frame: int, w: int = 640, h: int = 480) -> np.ndarray:
    """tt_um_vgacal_prbs's picture for a given 8-bit frame counter value:

    - Rows 0..7 (y < 8): the 8-bit frame counter as eight 80x8 blocks (same
      encoding as counter()'s top block row).
    - Rows 8..h: the low 6 bits of a 16-bit Fibonacci LFSR seeded with
      0xACE1 ^ frame at the first active pixel of row 8, advanced once per
      active pixel in raster order (continuously across rows).
    """
    frame &= 0xFF
    img = np.zeros((h, w), dtype=np.uint8)
    img[0:8, :] = _counter_strip(frame, w, 8)
    img[8:h, :] = _lfsr_pixels(0xACE1 ^ frame, w * (h - 8)).reshape(h - 8, w)
    return img


def to_rgb(img6: np.ndarray) -> np.ndarray:
    """Expand a 6-bit (rr gg bb) image to 8-bit RGB, levels 0/85/170/255."""
    levels = np.array([0, 85, 170, 255], dtype=np.uint8)
    r = levels[(img6 >> 4) & 0x3]
    g = levels[(img6 >> 2) & 0x3]
    b = levels[img6 & 0x3]
    return np.stack([r, g, b], axis=-1)


def save_png(img6: np.ndarray, path: str | pathlib.Path) -> None:
    Image.fromarray(to_rgb(img6), mode="RGB").save(path)
