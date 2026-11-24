# SPDX-License-Identifier: Apache-2.0
"""cocotb test for tt_um_vgacal_framer.

Runs the design for a little over one frame, collects uo_out on the clocks
where uio_out[0] is high, parses those bytes as vgacap chunks, and checks
the RAW samples are the bars picture's samples on every other clock (the
framer's sample_valid cadence), in order, with no overrun reported.
"""
from __future__ import annotations

import pathlib
import struct
import sys

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
from tools import render  # noqa: E402

H_TOTAL, V_TOTAL = 800, 525


def bars_frame() -> list[int]:
    """uo_out of tt_um_vgacal_bars for one frame, sample k at (k%800, k//800)."""
    img = render.bars()
    out = []
    for v in range(V_TOTAL):
        for h in range(H_TOTAL):
            hs = 0 if 656 <= h < 752 else 1
            vline = v if h < 656 else (v + 1) % V_TOTAL
            vs = 0 if 490 <= vline < 492 else 1
            c = int(img[v][h]) if (h < 640 and v < 480) else 0
            out.append((hs << 7) | ((c & 1) << 6) | (((c >> 2) & 1) << 5) | (((c >> 4) & 1) << 4)
                       | (vs << 3) | (((c >> 1) & 1) << 2) | (((c >> 3) & 1) << 1) | ((c >> 5) & 1))
    return out


def chunks(data: bytes):
    pos = 0
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4]
        length = struct.unpack_from("<I", data, pos + 4)[0]
        if pos + 8 + length > len(data):
            return
        yield tag, data[pos + 8:pos + 8 + length]
        pos += 8 + length


@cocotb.test()
async def test_framed_samples_are_the_bars_picture(dut):
    cocotb.start_soon(Clock(dut.clk, 40, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    assert int(dut.uio_oe.value) == 0x01

    out = bytearray()
    for _ in range(H_TOTAL * V_TOTAL + 4000):
        await FallingEdge(dut.clk)
        if int(dut.uio_out.value) & 1:
            out.append(int(dut.uo_out.value))

    samples, drops = [], []
    for tag, payload in chunks(bytes(out)):
        if tag == b"RAW ":
            assert struct.unpack_from("<I", payload, 0)[0] == 256
            for i in range(4, len(payload), 4):
                w = struct.unpack_from("<I", payload, i)[0]
                samples += [(w >> 24) & 255, (w >> 16) & 255, (w >> 8) & 255, w & 255]
        elif tag == b"TIME":
            drops.append(struct.unpack_from("<I", payload, 12)[0])
        else:
            raise AssertionError("unexpected chunk %r" % tag)
    assert drops == [], "the framer reported overruns: %s" % drops
    assert len(samples) >= 2 * H_TOTAL
    frame = bars_frame()
    twice = frame + frame
    # Every other clock: the samples are frame[k0], frame[k0+2], ...
    starts = [k for k in range(2) if all(samples[i] == twice[k + 2 * i] for i in range(len(samples)))]
    assert starts, "framed samples are not the bars picture every other clock"
