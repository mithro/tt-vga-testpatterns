# SPDX-License-Identifier: Apache-2.0
"""cocotb test for tt_um_vgacal_grid.

Drives clk at 40 ns (25 MHz), holds rst_n low for 10 cycles, then checks
that hsync and vsync have the expected periods and that a handful of
sampled pixels match tools/render.py:grid().

Sample index k (0-indexed, taken on the falling clock edge k cycles after
rst_n is released -- the same phase tools/dump_uo_out.py samples at)
corresponds to hpos = k % 800, vpos = (k // 800) % 525: this is the
"hvsync_generator holds hpos/vpos at 0 through the last reset cycle, then
increments once per clock" convention documented in common/hvsync_generator.v.

project.v registers colour one clock behind hpos/vpos (to stay in step with
the registered hsync/vsync -- see the comment there), so the colour visible
at sample index k is the picture's pixel at (hpos, vpos) of sample index
k - 1, not sample index k.

project.v also computes the grid/border pattern from vpos_for_color =
vpos - 1 (wrapping), one line behind vpos itself: this corrects an
empirically-observed one-line difference between hvsync_generator's vpos
and the row vgacap's frame reconstruction crops it into (see the comment in
project.v). So GRID[row, col] appears at design vpos = row + 1, hpos =
col + 1 (the vpos_for_color line shift stacks with the one-clock colour
latency above).
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
H_TOTAL = 800
V_TOTAL = 525
H_ACTIVE = 640
V_ACTIVE = 480

GRID = render.grid()


def hsync_bit(uo_out: int) -> int:
    return (uo_out >> 7) & 1


def vsync_bit(uo_out: int) -> int:
    return (uo_out >> 3) & 1


def pixel6(uo_out: int) -> int:
    """Reassemble the 6-bit rr gg bb colour value from uo_out's Tiny VGA bits."""
    b0 = (uo_out >> 6) & 1
    g0 = (uo_out >> 5) & 1
    r0 = (uo_out >> 4) & 1
    b1 = (uo_out >> 2) & 1
    g1 = (uo_out >> 1) & 1
    r1 = uo_out & 1
    return (r1 << 5) | (r0 << 4) | (g1 << 3) | (g0 << 2) | (b1 << 1) | b0


async def reset(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1


async def measure_period(dut, bit_index: int, max_cycles: int) -> int:
    """Clock count between the first two falling edges of uo_out[bit_index],
    sampled on the falling clock edge (Icarus VPI cannot register a value
    change callback directly on a bit-select of a concatenation-assigned
    wire like uo_out, so we poll it once per clock instead of using
    FallingEdge(dut.uo_out[bit_index]))."""
    prev = None
    edges = []
    for i in range(max_cycles):
        await FallingEdge(dut.clk)
        val = (int(dut.uo_out.value) >> bit_index) & 1
        if prev == 1 and val == 0:
            edges.append(i)
            if len(edges) == 2:
                break
        prev = val
    assert len(edges) == 2, f"did not observe two falling edges of bit {bit_index} within {max_cycles} clocks"
    return edges[1] - edges[0]


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

    def hpos(self) -> int:
        return self.index % H_TOTAL

    def vpos(self) -> int:
        return (self.index // H_TOTAL) % V_TOTAL


@cocotb.test()
async def test_hsync_period(dut):
    """hsync toggles low once per line: period is 800 clocks."""
    await reset(dut)
    period_clocks = await measure_period(dut, 7, 2 * H_TOTAL)
    assert period_clocks == H_TOTAL, f"hsync period {period_clocks} clocks, expected {H_TOTAL}"


@cocotb.test()
async def test_vsync_period(dut):
    """vsync toggles low once per frame: period is 525*800 clocks."""
    await reset(dut)
    period_clocks = await measure_period(dut, 3, 2 * V_TOTAL * H_TOTAL)
    assert period_clocks == V_TOTAL * H_TOTAL, (
        f"vsync period {period_clocks} clocks, expected {V_TOTAL * H_TOTAL}"
    )


@cocotb.test()
async def test_sampled_pixels(dut):
    """A handful of pixels, well into frame 2, match tools/render.py:grid()."""
    await reset(dut)
    sampler = Sampler(dut)

    # Line 0 (top border row) of frame 2 (index offset by one full frame so
    # we are clear of the reset transient): every pixel should be white.
    # Row 0 of the picture appears at design vpos=1 (vpos_for_color's
    # one-line shift), and colour lags hpos by one clock (see docstring).
    base0 = V_TOTAL * H_TOTAL + 1 * H_TOTAL
    for x in (1, 5, 100):
        uo = await sampler.at(base0 + x + 1)
        got = pixel6(uo)
        want = int(GRID[0, x])
        assert got == want == 0x3F, f"x={x} y=0: got {got:#08b} want {want:#08b}"

    # A few active-area samples on line 64 of the same frame: grid lines at
    # x%8==0, the border at x==0/639, and off-grid pixels in between.
    # Picture row `line` appears at design vpos = line + 1.
    line = 64
    base = V_TOTAL * H_TOTAL + (line + 1) * H_TOTAL
    for x in (0, 1, 4, 7, 8, 16, 320, 638, 639):
        uo = await sampler.at(base + x + 1)
        assert sampler.hpos() == x + 1 and sampler.vpos() == line + 1
        got = pixel6(uo)
        want = int(GRID[line, x])
        assert got == want, f"x={x} y={line}: got {got:#08b} want {want:#08b}"

    # A blanking-area sample: colour must be forced to 0.
    uo = await sampler.at(base + 700 + 1)
    assert pixel6(uo) == 0, "colour must be blanked outside the active area"
