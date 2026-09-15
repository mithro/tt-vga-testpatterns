# SPDX-License-Identifier: Apache-2.0
"""cocotb test for tt_um_vgacal_counter.

Drives clk at 40 ns (25 MHz), holds rst_n low for 10 cycles, then checks
that hsync and vsync have the expected periods, that the 8-bit frame
counter blocks (rows 0..59) read the right frame number in frames 0, 1 and
2, and that the 9-bit line-number blocks (rows 60..479) match
tools/render.py:counter().

Sample index k (0-indexed, taken on the falling clock edge k cycles after
rst_n is released -- the same phase tools/dump_uo_out.py samples at)
corresponds to hpos = k % 800, vpos = (k // 800) % 525 *within* a frame,
and frame = k // (800*525) -- i.e. frame N's picture occupies sample
indices [N*800*525, (N+1)*800*525), because the frame counter register
only ever changes during vertical blanking (see project.v), well clear of
either edge of that window. So sample index base = frame*800*525 +
y*800 + x lands exactly on tools/render.py:counter(frame)[y, x].

Some helpers (Sampler, measure_period, pixel6, reset) are duplicated from
test_bars.py/test_grid.py; not yet factored out into a shared module (see
the Task 1 review, finding 8).
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
FRAME_CLOCKS = H_TOTAL * V_TOTAL


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
async def test_frame_counter_blocks(dut):
    """In frames 0, 1 and 2, the block row at y=30 (x = 40 + 80*i for block
    i) encodes the frame number, matching tools/render.py:counter()."""
    await reset(dut)
    sampler = Sampler(dut)

    y = 30
    for frame_idx in (0, 1, 2):
        want = render.counter(frame_idx)
        base = frame_idx * FRAME_CLOCKS + y * H_TOTAL
        for i in range(8):
            x = 40 + 80 * i
            uo = await sampler.at(base + x)
            got = pixel6(uo)
            want_px = int(want[y, x])
            assert got == want_px, (
                f"frame {frame_idx} block {i} (x={x}, y={y}): got {got:#08b} want {want_px:#08b}"
            )


@cocotb.test()
async def test_line_number_strip(dut):
    """The 9-bit line-number blocks, well into frame 2, match
    tools/render.py:counter() -- a label block, the black remainder of that
    band, and the x >= 540 margin."""
    await reset(dut)
    sampler = Sampler(dut)

    frame_idx = 2
    want = render.counter(frame_idx)
    base = frame_idx * FRAME_CLOCKS

    # Band k=1 (y = 100..119 label the value 100, y = 120..139 black).
    label_line = 100
    for x in (0, 30, 59, 60, 300, 539, 540, 600, 639):
        uo = await sampler.at(base + label_line * H_TOTAL + x)
        got = pixel6(uo)
        want_px = int(want[label_line, x])
        assert got == want_px, f"x={x} y={label_line}: got {got:#08b} want {want_px:#08b}"

    black_line = 130  # band offset 30, past the 20 label rows: must be black
    uo = await sampler.at(base + black_line * H_TOTAL + 30)
    got = pixel6(uo)
    assert got == 0, f"y={black_line}: got {got:#08b} want black (0)"

    # A blanking-area sample, later on the same line: colour must be
    # forced to 0 (Sampler only moves forward, so this must come last).
    uo = await sampler.at(base + black_line * H_TOTAL + 700)
    assert pixel6(uo) == 0, "colour must be blanked outside the active area"
