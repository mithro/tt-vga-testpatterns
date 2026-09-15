# SPDX-License-Identifier: Apache-2.0
"""cocotb test for tt_um_vgacal_prbs.

Drives clk at 40 ns (25 MHz), holds rst_n low for 10 cycles, then checks
that hsync and vsync have the expected periods, that the frame-counter
strip (rows 0..7) reads the right frame number in frames 0, 1 and 2, and
that the first 64 pixels of row 8 in frame 0 exactly match the Python LFSR
model in tools/render.py -- proving the Verilog and Python LFSRs agree bit
for bit, not just "look similar".

Sample index k (0-indexed, taken on the falling clock edge k cycles after
rst_n is released -- the same phase tools/dump_uo_out.py samples at)
corresponds to hpos = k % 800, vpos = (k // 800) % 525 *within* a frame,
and frame = k // (800*525) -- i.e. frame N's picture occupies sample
indices [N*800*525, (N+1)*800*525), because the frame counter register
only ever changes during vertical blanking (see project.v), well clear of
either edge of that window. So sample index base = frame*800*525 +
y*800 + x lands exactly on tools/render.py:prbs(frame)[y, x].

Some helpers (Sampler, measure_period, pixel6, reset) are duplicated from
test_bars.py/test_grid.py/test_counter.py; not yet factored out into a
shared module (see the Task 1 review, finding 8).
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
async def test_frame_counter_strip(dut):
    """In frames 0, 1 and 2, the block row at y=4 (x = 40 + 80*i for block
    i) encodes the frame number, matching tools/render.py:prbs()."""
    await reset(dut)
    sampler = Sampler(dut)

    y = 4
    for frame_idx in (0, 1, 2):
        want = render.prbs(frame_idx)
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
async def test_lfsr_matches_model(dut):
    """The first 64 pixels of row 8 in frame 0 equal tools/render.py's LFSR
    model exactly -- the Verilog and Python LFSRs must agree bit for bit,
    not just produce similarly-noisy pictures."""
    await reset(dut)
    sampler = Sampler(dut)

    y = 8
    want = render.prbs(0)
    for x in range(64):
        uo = await sampler.at(y * H_TOTAL + x)
        got = pixel6(uo)
        want_px = int(want[y, x])
        assert got == want_px, f"x={x} y={y}: got {got:#08b} want {want_px:#08b}"


@cocotb.test()
async def test_lfsr_reseeds_per_frame(dut):
    """The LFSR is reseeded from 0xACE1 ^ frame each frame, not just left
    running: row 8 pixel 0 in frames 1 and 2 must match
    tools/render.py:prbs() for those frame numbers (and, since the seed
    depends on frame, must differ from frame 0's)."""
    await reset(dut)
    sampler = Sampler(dut)

    y = 8
    x = 0
    seen = set()
    for frame_idx in (0, 1, 2):
        want = render.prbs(frame_idx)
        uo = await sampler.at(frame_idx * FRAME_CLOCKS + y * H_TOTAL + x)
        got = pixel6(uo)
        want_px = int(want[y, x])
        assert got == want_px, f"frame {frame_idx} x={x} y={y}: got {got:#08b} want {want_px:#08b}"
        seen.add(got)
    assert len(seen) > 1, "LFSR seed does not appear to depend on the frame counter"
