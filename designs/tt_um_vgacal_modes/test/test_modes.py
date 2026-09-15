# SPDX-License-Identifier: Apache-2.0
"""cocotb tests for tt_um_vgacal_modes.

Drives clk at 40 ns (25 MHz), holds rst_n low for 10 cycles with ui_in
already set (the design samples ui_in[3:0] on the reset edge as well as at
each frame boundary, so the selected mode is live from the first frame),
then, for each of the three modes:

- scans two whole frames' worth of samples once and derives, from the
  hsync/vsync transitions alone, the hsync period, the hsync pulse width
  and polarity, the vsync period, the vsync pulse width and polarity, and
  the number of hsync leading edges between two vsync leading edges (the
  lines per frame) -- asserting all of them against the VESA numbers for
  that mode;
- samples one active row around the first two bar boundaries (x =
  bar_width and x = 2*bar_width, plus the pixels either side and the
  clipped last bar) and compares against tools/render.py:modes().

A final test checks that changing ui_in mid-frame does not disturb the
frame in progress and does take effect at the start of the next one.

Sample index k (0-indexed, taken on the falling clock edge k cycles after
rst_n is released -- the same phase tools/dump_uo_out.py samples at)
corresponds to hpos = k % H_TOTAL, vpos = (k // H_TOTAL) % V_TOTAL, with
H_TOTAL/V_TOTAL those of the selected mode. Colour tracks hpos exactly (see
project.v's bar counters), so the colour visible at sample index k is the
picture's pixel at that same index's (hpos, vpos) -- no offset needed.

Some helpers (pixel6, reset) are duplicated from test_bars.py and friends;
not yet factored out into a shared module (see the Task 1 review,
finding 8).
"""
from __future__ import annotations

import pathlib
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from tools import render  # noqa: E402

CLK_PERIOD_NS = 40

HSYNC_BIT = 7
VSYNC_BIT = 3

# ui_in[1:0] -> the mode's VESA numbers. h_pol/v_pol are the *pulse* level:
# 1 = the sync pulse is high (active high), 0 = low.
MODES = {
    0: dict(name="640x480@60", w=640, h=480,
            h_total=800, h_sync=96, v_total=525, v_sync=2, h_pol=0, v_pol=0),
    1: dict(name="800x600@60", w=800, h=600,
            h_total=1056, h_sync=128, v_total=628, v_sync=4, h_pol=1, v_pol=1),
    2: dict(name="720x400@70", w=720, h=400,
            h_total=900, h_sync=108, v_total=449, v_sync=2, h_pol=0, v_pol=1),
}


def pixel6(uo_out: int) -> int:
    """Reassemble the 6-bit rr gg bb colour value from uo_out's Tiny VGA bits."""
    b0 = (uo_out >> 6) & 1
    g0 = (uo_out >> 5) & 1
    r0 = (uo_out >> 4) & 1
    b1 = (uo_out >> 2) & 1
    g1 = (uo_out >> 1) & 1
    r1 = uo_out & 1
    return (r1 << 5) | (r0 << 4) | (g1 << 3) | (g0 << 2) | (b1 << 1) | b0


async def reset(dut, ui_in: int = 0) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = ui_in
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1


class Sampler:
    """Samples uo_out on the falling clock edge, tracking the sample index
    so hpos/vpos can be derived without re-deriving elapsed-cycle counts."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.index = 0

    async def at(self, index: int) -> int:
        assert index >= self.index, "Sampler only moves forward"
        delta = index - self.index
        if delta > 0:
            await ClockCycles(self.dut.clk, delta)
        await FallingEdge(self.dut.clk)
        self.index = index
        return int(self.dut.uo_out.value)


async def scan_transitions(dut, clocks: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Sample uo_out on the falling clock edge for `clocks` cycles and return
    the hsync and vsync transition lists as (sample index, new level) pairs.

    One pass collects everything the timing assertions need, which matters
    here: two frames of 800x600@60 is 1.3 M samples, so re-scanning per
    property would make this test several times slower for no extra
    coverage. Sampling both bits in the same loop is free."""
    h_tr: list[tuple[int, int]] = []
    v_tr: list[tuple[int, int]] = []
    prev_h = prev_v = None
    for i in range(clocks):
        await FallingEdge(dut.clk)
        uo = int(dut.uo_out.value)
        h = (uo >> HSYNC_BIT) & 1
        v = (uo >> VSYNC_BIT) & 1
        if prev_h is not None and h != prev_h:
            h_tr.append((i, h))
        if prev_v is not None and v != prev_v:
            v_tr.append((i, v))
        prev_h, prev_v = h, v
    return h_tr, v_tr


def pulse_level(transitions: list[tuple[int, int]], what: str) -> int:
    """The active (pulse) level of a sync signal, derived from its own
    transitions rather than assumed: of the two alternating runs, the pulse
    is the *shorter* one (a sync pulse is a small fraction of its period in
    every VGA mode), so its level is the value the shorter run holds."""
    assert len(transitions) >= 3, f"{what}: only {len(transitions)} transitions seen"
    (i0, v0), (i1, _), (i2, _) = transitions[0], transitions[1], transitions[2]
    return v0 if (i1 - i0) < (i2 - i1) else 1 - v0


def leading_edges(transitions: list[tuple[int, int]], level: int) -> list[int]:
    """Sample indices of the transitions *into* `level` (the pulse's leading
    edges)."""
    return [i for i, v in transitions if v == level]


def widths(transitions: list[tuple[int, int]], level: int) -> list[int]:
    """Lengths of every complete run at `level`: each leading edge to the
    following (trailing) transition."""
    out = []
    for n, (i, v) in enumerate(transitions[:-1]):
        if v == level:
            out.append(transitions[n + 1][0] - i)
    return out


@cocotb.test()
@cocotb.parametrize(mode=[0, 1, 2])
async def test_mode_timing(dut, mode: int):
    """Each mode's hsync/vsync periods, pulse widths, polarities and lines
    per frame match the VESA numbers in MODES."""
    m = MODES[mode]
    await reset(dut, ui_in=mode)

    # Two whole frames plus two lines of margin, so at least two vsync
    # leading edges (and the pulse after the second) are inside the scan.
    h_tr, v_tr = await scan_transitions(dut, 2 * m["v_total"] * m["h_total"] + 2 * m["h_total"])

    h_level = pulse_level(h_tr, "hsync")
    v_level = pulse_level(v_tr, "vsync")
    assert h_level == m["h_pol"], (
        f"{m['name']}: hsync pulse is {'high' if h_level else 'low'}, expected "
        f"{'high' if m['h_pol'] else 'low'}"
    )
    assert v_level == m["v_pol"], (
        f"{m['name']}: vsync pulse is {'high' if v_level else 'low'}, expected "
        f"{'high' if m['v_pol'] else 'low'}"
    )

    h_edges = leading_edges(h_tr, h_level)
    h_periods = {b - a for a, b in zip(h_edges, h_edges[1:])}
    assert h_periods == {m["h_total"]}, (
        f"{m['name']}: hsync periods {sorted(h_periods)} clocks, expected {m['h_total']}"
    )
    h_widths = set(widths(h_tr, h_level))
    assert h_widths == {m["h_sync"]}, (
        f"{m['name']}: hsync pulse widths {sorted(h_widths)} clocks, expected {m['h_sync']}"
    )

    v_edges = leading_edges(v_tr, v_level)
    assert len(v_edges) >= 2, f"{m['name']}: only {len(v_edges)} vsync leading edges in the scan"
    v_periods = {b - a for a, b in zip(v_edges, v_edges[1:])}
    assert v_periods == {m["v_total"] * m["h_total"]}, (
        f"{m['name']}: vsync periods {sorted(v_periods)} clocks, expected "
        f"{m['v_total'] * m['h_total']}"
    )
    v_widths = set(widths(v_tr, v_level))
    assert v_widths == {m["v_sync"] * m["h_total"]}, (
        f"{m['name']}: vsync pulse widths {sorted(v_widths)} clocks, expected "
        f"{m['v_sync'] * m['h_total']} ({m['v_sync']} lines)"
    )

    # Lines per frame, counted the way a VGA sink counts them: hsync leading
    # edges between two consecutive vsync leading edges.
    lines = sum(1 for i in h_edges if v_edges[0] <= i < v_edges[1])
    assert lines == m["v_total"], (
        f"{m['name']}: {lines} hsync leading edges per frame, expected {m['v_total']}"
    )


@cocotb.test()
@cocotb.parametrize(mode=[0, 1, 2])
async def test_bar_boundaries(dut, mode: int):
    """The bars start where they should for each mode's bar width: the
    pixels around x = bar_width and x = 2*bar_width step the colour index by
    exactly one, and the clipped last bar reads 63 to the right-hand edge."""
    m = MODES[mode]
    bar_w = m["w"] // 64
    want = render.modes(mode)
    assert want.shape == (m["h"], m["w"])

    await reset(dut, ui_in=mode)

    # Row 100 of the second frame (clear of the reset transient).
    row = 100
    base = m["v_total"] * m["h_total"] + row * m["h_total"]
    xs = [0, bar_w - 1, bar_w, 2 * bar_w - 1, 2 * bar_w, m["w"] - 1]

    sampler = Sampler(dut)
    for x in xs:
        got = pixel6(await sampler.at(base + x))
        assert got == int(want[row, x]), (
            f"{m['name']}: x={x} y={row}: got {got}, want {int(want[row, x])}"
        )

    # The two boundaries are real steps, not a flat picture that happens to
    # match: bar index must increase by one across each of them.
    assert int(want[row, bar_w]) == int(want[row, bar_w - 1]) + 1
    assert int(want[row, 2 * bar_w]) == int(want[row, 2 * bar_w - 1]) + 1


@cocotb.test()
async def test_mode_change_takes_effect_at_frame_start(dut):
    """ui_in is sampled only at a frame boundary: switching from mode 0 to
    mode 1 in the middle of a frame leaves that frame's line length alone
    and changes it from the next frame on."""
    m0, m1 = MODES[0], MODES[1]
    await reset(dut, ui_in=0)

    # Let the first frame get going, then switch mid-frame (line ~100).
    await ClockCycles(dut.clk, 100 * m0["h_total"] + 17)
    dut.ui_in.value = 1

    # The rest of this frame must still be mode 0: scan to just before the
    # frame boundary and check every hsync period is still 800 clocks.
    remaining = (m0["v_total"] - 102) * m0["h_total"]
    h_tr, _ = await scan_transitions(dut, remaining)
    edges = leading_edges(h_tr, m0["h_pol"])
    periods = {b - a for a, b in zip(edges, edges[1:])}
    assert periods == {m0["h_total"]}, (
        f"mode change disturbed the frame in progress: hsync periods "
        f"{sorted(periods)} clocks, expected {m0['h_total']}"
    )

    # Now cross the frame boundary and check the new mode is in effect: skip
    # the boundary line itself, then every hsync period must be 1056 clocks.
    await ClockCycles(dut.clk, 3 * m0["h_total"])
    h_tr, _ = await scan_transitions(dut, 4 * m1["h_total"])
    edges = leading_edges(h_tr, m1["h_pol"])
    periods = {b - a for a, b in zip(edges, edges[1:])}
    assert periods == {m1["h_total"]}, (
        f"mode change did not take effect at the frame boundary: hsync periods "
        f"{sorted(periods)} clocks, expected {m1['h_total']}"
    )
