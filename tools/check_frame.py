# SPDX-License-Identifier: Apache-2.0
"""Frame-mode check: the real board program, on an emulated board, fed by RTL.

`ttcap capture --mode frame` captures whole frames at the design's real
clock with `vgacap`'s `frame_rp2.py`. This runs *exactly that built script*
on `ttcap.emu.Board` -- an emulated RP2350 running MicroPython's own
`rp2.asm_pio`, a cycle-level PIO, control-block DMA and the board's
fragmented heap -- with the pins driven by an Icarus simulation of the
calibration design (`dump_uo_out.py`), at the system-clock ratio the SDK
really uses (4 or 2 clocks a pixel). Every picture it reconstructs must be
pixel-identical to the design's reference render.

    uv run tools/check_frame.py                       # every design
    uv run tools/check_frame.py tt_um_vgacal_prbs
    uv run tools/check_frame.py tt_um_vgacal_modes --ui-in 1

Needs the same `VGACAP` checkout as check.py (built, with `ttcap.emu`).
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import check  # noqa: E402
import compare_capture  # noqa: E402

#: (design, ui_in, VGA mode, project clock, system clock / project clock).
#: The ratios are the SDK's jitter-free choices measured on fpga-4: 100 MHz
#: for 25 MHz, 80 MHz for 40 MHz, 113 MHz for 28.25 MHz.
CASES = [
    ("tt_um_vgacal_bars", 0, "640x480@60", 25_000_000, 4),
    ("tt_um_vgacal_grid", 0, "640x480@60", 25_000_000, 4),
    ("tt_um_vgacal_counter", 0, "640x480@60", 25_000_000, 4),
    ("tt_um_vgacal_prbs", 0, "640x480@60", 25_000_000, 4),
    ("tt_um_vgacal_modes", 0, "640x480@60", 25_000_000, 4),
    ("tt_um_vgacal_modes", 1, "800x600@60", 40_000_000, 2),
    ("tt_um_vgacal_modes", 2, "720x400@70", 28_250_000, 4),
    ("tt_um_vgacal_modes", 4, "640x480@60", 25_000_000, 4),
    ("tt_um_vgacal_modes", 8, "640x480@60", 25_000_000, 4),
]

#: Frames of RTL to simulate. The emulator repeats the dump, so it is an
#: exact number of frames (no margin) and the repeat is seamless -- except
#: for the frame-counter designs, whose counter jumps back, which the
#: per-picture decode of the counter copes with.
SIM_FRAMES = 3
PICTURES = 2

#: The emulated heap, as contiguous free blocks: about fpga-4's (~420 KB
#: free in pieces, largest ~142 KB), where whole 640x480 frames fit in one
#: capture. With less, a picture is swept from two frames and a design that
#: changes every frame (prbs) is torn -- correctly, and ttcap says so -- so
#: the check also insists on one capture per picture where the heap allows.
HEAP = (142_000, 96_000, 64_000, 48_000, 40_000, 32_000)


def run_case(design: str, ui_in: int, vga: str, clock_hz: int, ratio: int, vgacap: pathlib.Path,
             work: pathlib.Path) -> tuple[bool, str]:
    sys.path.insert(0, str(vgacap / "python"))
    from ttcap import mp  # noqa: E402 (needs VGACAP on sys.path)
    from ttcap.boards import RP2350_DBV3
    from ttcap.capture import CaptureRequest, stream_header_bytes
    from ttcap.emu import Board, Waveform
    from vgacap.modes import MODES

    mode = MODES[vga]
    clocks = SIM_FRAMES * mode.cpl * mode.lpf
    dump = work / f"{design}-{ui_in}.bin"
    sim = subprocess.run(
        [sys.executable, str(HERE / "dump_uo_out.py"), "--top", design, "--out", dump.name,
         "--clocks", str(clocks), "--ui-in", str(ui_in), "--build-dir", "sim",
         *[str(p) for p in check.design_sources(design)]],
        cwd=work, capture_output=True, text=True)
    if sim.returncode:
        return False, "RTL simulation failed (exit %d): %s" % (
            sim.returncode, (sim.stderr or sim.stdout).strip()[-300:])
    uo = dump.read_bytes()
    if len(uo) != clocks:
        return False, f"dump has {len(uo)} clocks, wanted {clocks}"

    profile = RP2350_DBV3
    req = CaptureRequest(
        profile=profile, project=None, design=design, clock_hz=clock_hz, seconds=0,
        max_bytes=0, script="frame_rp2.py", vga_mode=vga, max_frames=PICTURES,
        edge="rising", ui_in=ui_in or None,
    )
    board = Board(
        Waveform(uo, profile.uo_gpios, profile.clk_gpio, period=ratio, high=ratio // 2, delay=1),
        sysclk_hz=clock_hz * ratio,
        heap_blocks=HEAP,
        max_cycles=60 * clock_hz * ratio,
    )
    out = board.run_script(mp.build(req.cfg(), req.script))
    from vgacap.stream import read_chunks
    region = req.cfg()["region_lines"]
    windows = [int.from_bytes(p[6:8], "little") for tag, p in read_chunks(out) if tag == "FRAM"]
    if mode.v_active * mode.cpl <= 380_000 and any(n != region for n in windows):
        return False, "a picture took several captures (%s lines) though the heap holds it" % windows
    stream = work / f"{design}-{ui_in}.vgacap"
    stream.write_bytes(stream_header_bytes(req) + out)

    prefix = work / f"{design}-{ui_in}-f"
    frames = subprocess.run([str(vgacap / "build" / "vgacap-frames"), str(stream), str(prefix)],
                            capture_output=True, text=True, check=True).stdout
    ppms = sorted(work.glob(f"{design}-{ui_in}-f-*.ppm"))
    if len(ppms) != PICTURES:
        return False, f"{len(ppms)} picture(s), wanted {PICTURES}: {frames.strip()[-200:]}"
    verdicts = []
    for ppm in ppms:
        got = compare_capture.read_ppm(ppm)
        got6 = check.rgb_to_img6(got)
        want6, why = compare_capture.reference(design, got6, ui_in)
        bad = int((got6 != want6).sum()) if got6.shape == want6.shape else -1
        if bad:
            return False, f"{ppm.name}: {bad} pixel(s) differ ({why})"
        verdicts.append(why)
    return True, "%d picture(s) pixel-exact at %d Hz, %d clocks a pixel (%s)" % (
        len(ppms), clock_hz, ratio, "; ".join(verdicts))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("design", nargs="?")
    ap.add_argument("--ui-in", type=lambda s: int(s, 0))
    a = ap.parse_args(argv)
    vgacap = check.vgacap_dir()
    cases = [c for c in CASES if (a.design is None or c[0] == a.design)
             and (a.ui_in is None or c[1] == a.ui_in)]
    if not cases:
        print("no such case", file=sys.stderr)
        return 2
    failed = 0
    with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp", prefix="check_frame-") as tmp:
        work = pathlib.Path(tmp)
        for design, ui_in, vga, clock_hz, ratio in cases:
            ok, detail = run_case(design, ui_in, vga, clock_hz, ratio, vgacap, work)
            failed += not ok
            print("%s %s ui_in=%#x %s: %s" % ("PASS" if ok else "FAIL", design, ui_in, vga, detail),
                  flush=True)
    print("%d case(s), %d failed" % (len(cases), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
