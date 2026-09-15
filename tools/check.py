# SPDX-License-Identifier: Apache-2.0
"""End-to-end check: simulate a design, wrap the dump into a vgacap stream,
reconstruct frames with vgacap-frames, and diff the last frame against the
design's reference render, pixel-exactly.

    uv run tools/check.py tt_um_vgacal_bars
    uv run tools/check.py tt_um_vgacal_bars --frames 3
    uv run tools/check.py tt_um_vgacal_modes --ui-in 2

tt_um_vgacal_modes is checked once per ui_in sub-case (see MODE_CASES): the
three timings plus the two polarity inversions on mode 0, each asserting
what vgacap-frames reports about the frame (mode name, clocks per line,
lines per frame, both sync polarities) as well as diffing the picture.
Without --ui-in all five sub-cases run, which is what `make check` does.

--frames N simulates N frames' worth of clocks (plus a small margin) and
checks the *last* frame vgacap-frames reconstructs from that capture.
vgacap's timing learner needs to see three vsync entries before it can
reconstruct a full, non-partial frame, so N must be >= 3 (N=3 reconstructs
exactly one full frame; larger N is only useful to check that steady-state
frames past the first also come out pixel-exact).

If --frames is omitted, the default depends on the design (see
DEFAULT_FRAMES below): 3 for designs that draw the same picture every
frame (bars/grid), but 5 for the frame-counter designs (counter/prbs) --
N=3 only ever reconstructs a single frame, which would never exercise
those designs' consecutive-counter assertion (see check()'s
MIN_FRAME_COUNTER_FRAMES check, which FAILs outright if fewer than 2
frames come out). This is also what the top-level Makefile's generic
`check-%` target relies on, since it never passes --frames itself.

VGACAP (the vgacap checkout, with a build already at <VGACAP>/build and the
Python package at <VGACAP>/python -- both are required) defaults to
../vgacap relative to the repo root; override with the VGACAP environment
variable if that checkout lives somewhere else, e.g.:

    VGACAP=/path/to/vgacap uv run tools/check.py tt_um_vgacal_bars
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys

import numpy as np

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

sys.path.insert(0, str(REPO_ROOT))
from tools import render  # noqa: E402

H_TOTAL = 800
V_TOTAL = 525

# Design name -> reference renderer (returns a (h, w) uint8 array of 6-bit
# Tiny VGA colour values). These designs draw the same picture every frame,
# so only the last reconstructed frame is checked.
REFERENCE_RENDERS = {
    "tt_um_vgacal_bars": render.bars,
    "tt_um_vgacal_grid": render.grid,
}

# Design name -> reference renderer that takes the design's own 8-bit frame
# counter (render.counter/render.prbs). These designs draw a different
# picture each frame *and* draw that frame counter into the picture itself
# (top-left block row), so every reconstructed frame is checked individually:
# the frame counter is decoded from the reconstructed picture (see
# decode_frame_counter/FRAME_COUNTER_ROW below) and the reference is
# rendered for that same counter value before diffing.
FRAME_COUNTER_RENDERS = {
    "tt_um_vgacal_counter": render.counter,
    "tt_um_vgacal_prbs": render.prbs,
}

# Row (within the reconstructed 480-line frame) of the 8-block frame-counter
# strip each frame-counter design draws, sampled at the middle of each
# block's column (x = 40 + 80*i for block i).
FRAME_COUNTER_ROW = {
    "tt_um_vgacal_counter": 30,  # middle of the 80x60 block row (y in [0, 60))
    "tt_um_vgacal_prbs": 4,      # middle of the 80x8 block row (y in [0, 8))
}

# Default --frames per design, used whenever the caller doesn't pass an
# explicit --frames (in particular by the top-level Makefile's generic
# `check-%` target). --frames 3 is the minimum vgacap's timing learner
# needs to reconstruct a single full frame, which is enough for the
# same-picture-every-frame designs (bars/grid), but the whole point of the
# frame-counter designs (counter/prbs) is to prove *consecutive*
# reconstructed frames carry consecutive counters -- an assertion that is
# vacuous (never executed) with only one reconstructed frame. Default those
# two to 5, which reconstructs 3 frames (see MIN_FRAME_COUNTER_FRAMES
# below), so the default `make check` run actually exercises it.
DEFAULT_FRAMES = {
    "tt_um_vgacal_counter": 5,
    "tt_um_vgacal_prbs": 5,
}
DEFAULT_FRAMES_FALLBACK = 3

# Designs whose picture *and* timing depend on ui_in: each is checked once
# per sub-case below, driving ui_in through tools/dump_uo_out.py --ui-in, and
# each sub-case asserts the whole line vgacap-frames prints about the frame
# (mode name, clocks per line, lines per frame, both sync polarities) on top
# of the usual pixel-exact picture diff.
#
# The five sub-cases are the three modes plus the two polarity inversions on
# mode 0. Inverting a polarity does not move the sync pulses or change their
# width, so vgacap still identifies the mode from (cpl, lpf) and reconstructs
# the identical picture -- only the reported polarity flips, which is exactly
# what makes these two cases worth checking separately.
#
# Fields: ui_in, mode name vgacap should report, clocks per line, lines per
# frame, hsync polarity, vsync polarity ("pos"/"neg" as vgacap-frames prints
# them). The renderer is render.modes(ui_in), which takes the mode from
# ui_in[1:0] (the picture does not depend on the polarity bits).
MODE_CASES = {
    "tt_um_vgacal_modes": [
        (0x0, "640x480@60", 800, 525, "neg", "neg"),
        (0x1, "800x600@60", 1056, 628, "pos", "pos"),
        (0x2, "720x400@70", 900, 449, "neg", "pos"),
        (0x4, "640x480@60", 800, 525, "pos", "neg"),  # mode 0, hsync inverted
        (0x8, "640x480@60", 800, 525, "neg", "pos"),  # mode 0, vsync inverted
    ],
}

# "frame 0: 640x480 mode=640x480@60 cpl=800 lpf=525 hsync=neg vsync=neg partial=0"
FRAME_LINE_RE = re.compile(
    r"^frame (?P<index>\d+): (?P<w>\d+)x(?P<h>\d+) mode=(?P<mode>\S+) "
    r"cpl=(?P<cpl>\d+) lpf=(?P<lpf>\d+) hsync=(?P<hsync>\S+) vsync=(?P<vsync>\S+) "
    r"partial=(?P<partial>\d+)$"
)

# A frame-counter design's check is only meaningful if it reconstructs at
# least two frames (otherwise the consecutive-counter assertion never
# runs): check() FAILs outright if fewer are reconstructed, rather than
# silently passing a single-frame check as if it had proven the guarantee.
MIN_FRAME_COUNTER_FRAMES = 2


def rgb_to_img6(rgb: np.ndarray) -> np.ndarray:
    """Inverse of render.to_rgb: reconstruct the 6-bit (rr gg bb) image from
    an (h, w, 3) RGB24 array whose channel values are each one of the four
    to_rgb levels (0, 85, 170, 255). Relies on those being exact multiples
    of 85, so integer division recovers the 2-bit level exactly."""
    lvl = (rgb.astype(np.uint16) // 85).astype(np.uint8)
    r, g, b = lvl[..., 0], lvl[..., 1], lvl[..., 2]
    return ((r << 4) | (g << 2) | b).astype(np.uint8)


def decode_frame_counter(img6: np.ndarray, row: int) -> int:
    """Decode a design's 8-bit frame counter from its own reconstructed
    picture: 8 blocks at (x = 40 + 80*i, y = row) for i in 0..7, white
    (0x3F) = bit set, blue (0x03) = bit clear, block 0 = most-significant
    bit -- see FRAME_COUNTER_RENDERS designs' docs/info.md."""
    value = 0
    for i in range(8):
        x = 40 + 80 * i
        px = int(img6[row, x])
        if px == 0x3F:
            bit = 1
        elif px == 0x03:
            bit = 0
        else:
            raise ValueError(
                f"unexpected frame-counter block pixel {px:#04x} at (x={x}, y={row}) "
                f"-- expected 0x3f (white) or 0x03 (blue)"
            )
        value = (value << 1) | bit
    return value


def vgacap_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("VGACAP", str(REPO_ROOT / ".." / "vgacap"))).resolve()


def design_sources(design: str) -> list[pathlib.Path]:
    src_dir = REPO_ROOT / "designs" / design / "src"
    sources = sorted(src_dir.glob("*.v"))
    if not sources:
        raise FileNotFoundError(f"no .v sources found in {src_dir}")
    return sources


def run_dump(
    design: str,
    frames: int,
    out_dir: pathlib.Path,
    ui_in: int = 0,
    h_total: int = H_TOTAL,
    v_total: int = V_TOTAL,
) -> pathlib.Path:
    # A few lines of margin beyond whole frames so vgaframe has enough
    # trailing samples to close out the last frame's last line.
    margin_clocks = 5 * h_total
    clocks = frames * h_total * v_total + margin_clocks
    # tb_dump_uo_out.v stores +out= in a reg [1023:0] (128 chars): pass a
    # short relative filename (cwd=out_dir) rather than an absolute path,
    # since a worktree checkout can put the repo root deep enough that an
    # absolute path here gets silently truncated by $value$plusargs.
    dump_name = f"{design}.bin"
    cmd = [
        sys.executable,
        str(HERE / "dump_uo_out.py"),
        "--top", design,
        "--out", dump_name,
        "--clocks", str(clocks),
        "--ui-in", str(ui_in),
        "--build-dir", "sim",
        *[str(p) for p in design_sources(design)],
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=out_dir)
    return out_dir / dump_name


def dump_to_stream(dump_path: pathlib.Path, stream_path: pathlib.Path, desc: str, vgacap: pathlib.Path) -> None:
    sys.path.insert(0, str(vgacap / "python"))
    from vgacap.stream import TINYVGA_MAP, Header, Writer  # noqa: E402 (deferred: needs VGACAP on sys.path)

    data = dump_path.read_bytes()
    header = Header(sample_bits=8, samples_per_word=4, flags=0, signal_map=TINYVGA_MAP, mode=3, clock_hz=0, desc=desc)
    chunk_samples = 65536
    with open(stream_path, "wb") as fp:
        w = Writer(fp, header)
        for start in range(0, len(data), chunk_samples):
            w.raw(list(data[start:start + chunk_samples]))


def run_vgacap_frames(vgacap: pathlib.Path, stream_path: pathlib.Path, out_prefix: pathlib.Path) -> str:
    binary = vgacap / "build" / "vgacap-frames"
    if not binary.exists():
        raise FileNotFoundError(f"vgacap-frames not found at {binary} (build vgacap first)")
    # Clear any frames left over from a previous run: vgacap-frames only
    # ever adds -NNNN.ppm files, so a run that reconstructs fewer frames
    # than the previous one would otherwise leave a stale, higher-numbered
    # PPM behind for last_frame_ppm() to pick up.
    if out_prefix.parent.exists():
        shutil.rmtree(out_prefix.parent)
    out_prefix.parent.mkdir(parents=True)
    cmd = [str(binary), str(stream_path), str(out_prefix)]
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.stdout


def all_frame_ppms(out_prefix: pathlib.Path) -> list[pathlib.Path]:
    ppms = sorted(out_prefix.parent.glob(f"{out_prefix.name}-*.ppm"))
    if not ppms:
        raise FileNotFoundError(f"no frames written to {out_prefix}-NNNN.ppm")
    return ppms


def last_frame_ppm(out_prefix: pathlib.Path) -> pathlib.Path:
    return all_frame_ppms(out_prefix)[-1]


def parse_frame_lines(stdout: str) -> list[dict[str, str]]:
    """The per-frame summary lines vgacap-frames prints on stdout, as dicts
    (see FRAME_LINE_RE). Anything else on stdout is ignored."""
    return [m.groupdict() for m in map(FRAME_LINE_RE.match, stdout.splitlines()) if m]


def check_mode_case(
    design: str, case: tuple, frames: int, vgacap: pathlib.Path, read_ppm
) -> bool:
    """One (ui_in, expected reported timing) sub-case of a MODE_CASES design:
    simulate with that ui_in, reconstruct, and check both what
    vgacap-frames *reports* about the frame (mode/cpl/lpf/polarities) and
    the reconstructed picture, pixel-exactly, against render.modes(ui_in)."""
    ui_in, mode_name, cpl, lpf, hsync, vsync = case
    label = f"ui_in={ui_in:#04x} ({mode_name} hsync={hsync} vsync={vsync})"
    print(f"--- {design}: {label}")

    work_dir = REPO_ROOT / "tmp" / "check" / design / f"ui_in_{ui_in:02x}"
    work_dir.mkdir(parents=True, exist_ok=True)

    dump_path = run_dump(design, frames, work_dir, ui_in=ui_in, h_total=cpl, v_total=lpf)
    stream_path = work_dir / f"{design}.vgacap"
    dump_to_stream(dump_path, stream_path, desc=f"iverilog {design} ui_in={ui_in}", vgacap=vgacap)

    out_prefix = work_dir / "frames" / design
    try:
        stdout = run_vgacap_frames(vgacap, stream_path, out_prefix)
    except subprocess.CalledProcessError as e:
        print(f"FAIL {label}: vgacap-frames exited {e.returncode}")
        return False

    lines = parse_frame_lines(stdout)
    if not lines:
        print(f"FAIL {label}: vgacap-frames reported no frames")
        return False
    # The last reported frame corresponds to the last PPM checked below.
    got = lines[-1]
    want = {
        "mode": mode_name,
        "cpl": str(cpl),
        "lpf": str(lpf),
        "hsync": hsync,
        "vsync": vsync,
        "partial": "0",
    }
    wrong = {k: (got[k], v) for k, v in want.items() if got[k] != v}
    if wrong:
        detail = ", ".join(f"{k}: got {g}, want {w}" for k, (g, w) in sorted(wrong.items()))
        print(f"FAIL {label}: vgacap-frames reported {detail}")
        return False

    try:
        ppm_path = last_frame_ppm(out_prefix)
    except FileNotFoundError as e:
        print(f"FAIL {label}: {e}")
        return False

    got_rgb = read_ppm(ppm_path)
    want_rgb = render.to_rgb(render.modes(ui_in=ui_in))
    if got_rgb.shape != want_rgb.shape:
        print(f"FAIL {label}: shape mismatch: got {got_rgb.shape}, want {want_rgb.shape}")
        return False
    mismatch = int(np.any(got_rgb != want_rgb, axis=-1).sum())
    if mismatch:
        print(f"FAIL {label}: {mismatch} mismatching pixels")
        return False

    print(f"PASS {label}")
    return True


def check_modes(
    design: str, frames: int, vgacap: pathlib.Path, only_ui_in: int | None = None
) -> bool:
    """Every MODE_CASES sub-case of `design` (or just the one whose ui_in is
    `only_ui_in`). All sub-cases are run even if an early one fails, so one
    run reports every broken mode rather than only the first."""
    sys.path.insert(0, str(vgacap / "python"))
    from vgacap.ppm import read_ppm  # noqa: E402 (deferred: needs VGACAP on sys.path)

    cases = MODE_CASES[design]
    if only_ui_in is not None:
        cases = [c for c in cases if c[0] == only_ui_in]
        if not cases:
            known = ", ".join(f"{c[0]:#04x}" for c in MODE_CASES[design])
            print(f"FAIL no --ui-in {only_ui_in:#04x} sub-case for {design} (have {known})")
            return False

    results = [check_mode_case(design, case, frames, vgacap, read_ppm) for case in cases]
    failed = len(results) - sum(results)
    if failed:
        print(f"FAIL {failed}/{len(results)} sub-cases failed")
        return False
    print(f"PASS ({len(results)} sub-cases)")
    return True


def check(design: str, frames: int, vgacap: pathlib.Path, ui_in: int | None = None) -> bool:
    frame_counter_render = FRAME_COUNTER_RENDERS.get(design)
    if design not in REFERENCE_RENDERS and frame_counter_render is None and design not in MODE_CASES:
        print(f"no reference render registered for {design!r}", file=sys.stderr)
        return False
    if not (vgacap / "build").is_dir() or not (vgacap / "python").is_dir():
        print(
            f"FAIL VGACAP ({vgacap}) needs a build/ (built vgacap-frames) and a "
            f"python/ (the vgacap package); override with the VGACAP environment "
            f"variable if vgacap lives somewhere other than ../vgacap"
        )
        return False
    if frames < 3:
        print(
            f"FAIL --frames must be >= 3 (vgacap's timing learner needs three "
            f"vsync entries to reconstruct a full frame; got --frames {frames})"
        )
        return False

    if design in MODE_CASES:
        # Timing and picture both depend on ui_in: run each sub-case in its
        # own work directory (see check_modes).
        return check_modes(design, frames, vgacap, only_ui_in=ui_in)
    if ui_in is not None:
        print(f"FAIL --ui-in is only meaningful for {', '.join(sorted(MODE_CASES))}")
        return False

    work_dir = REPO_ROOT / "tmp" / "check" / design
    work_dir.mkdir(parents=True, exist_ok=True)

    dump_path = run_dump(design, frames, work_dir)
    stream_path = work_dir / f"{design}.vgacap"
    dump_to_stream(dump_path, stream_path, desc=f"iverilog {design}", vgacap=vgacap)

    out_prefix = work_dir / "frames" / design
    try:
        run_vgacap_frames(vgacap, stream_path, out_prefix)
    except subprocess.CalledProcessError as e:
        print(f"FAIL vgacap-frames exited {e.returncode}")
        return False

    sys.path.insert(0, str(vgacap / "python"))
    from vgacap.ppm import read_ppm  # noqa: E402 (deferred: needs VGACAP on sys.path)

    if frame_counter_render is not None:
        # A different picture every frame, with the frame counter drawn
        # into the picture itself: check every reconstructed frame
        # individually, mapping each one to the counter value decoded from
        # its own top-left block row (see decode_frame_counter), and assert
        # consecutive reconstructed frames carry consecutive counters (no
        # frame dropped or duplicated by the capture/reconstruction path).
        try:
            ppm_paths = all_frame_ppms(out_prefix)
        except FileNotFoundError as e:
            print(f"FAIL {e}")
            return False
        if len(ppm_paths) < MIN_FRAME_COUNTER_FRAMES:
            print(
                f"FAIL only {len(ppm_paths)} frame(s) reconstructed, need >= "
                f"{MIN_FRAME_COUNTER_FRAMES} to exercise the consecutive-counter "
                f"assertion (pass a larger --frames)"
            )
            return False

        row = FRAME_COUNTER_ROW[design]
        prev_counter: int | None = None
        counters: list[int] = []
        for ppm_path in ppm_paths:
            got_rgb = read_ppm(ppm_path)
            img6 = rgb_to_img6(got_rgb)
            try:
                counter_val = decode_frame_counter(img6, row)
            except ValueError as e:
                print(f"FAIL {ppm_path.name}: {e}")
                return False

            if prev_counter is not None:
                expected = (prev_counter + 1) & 0xFF
                if counter_val != expected:
                    print(
                        f"FAIL {ppm_path.name}: frame counter {counter_val} is not "
                        f"consecutive after {prev_counter} (expected {expected}) -- "
                        f"a frame was dropped or duplicated"
                    )
                    return False
            prev_counter = counter_val
            counters.append(counter_val)

            want6 = frame_counter_render(counter_val)
            want_rgb = render.to_rgb(want6)
            if got_rgb.shape != want_rgb.shape:
                print(
                    f"FAIL {ppm_path.name}: shape mismatch: got {got_rgb.shape}, "
                    f"want {want_rgb.shape}"
                )
                return False
            mismatch = int(np.any(got_rgb != want_rgb, axis=-1).sum())
            if mismatch:
                print(f"FAIL {ppm_path.name}: counter={counter_val}: {mismatch} mismatching pixels")
                return False

        print(f"PASS ({len(counters)} frames, counters {counters})")
        return True

    try:
        ppm_path = last_frame_ppm(out_prefix)
    except FileNotFoundError as e:
        print(f"FAIL {e}")
        return False

    got_rgb = read_ppm(ppm_path)
    want6 = REFERENCE_RENDERS[design]()
    want_rgb = render.to_rgb(want6)

    if got_rgb.shape != want_rgb.shape:
        print(f"FAIL shape mismatch: got {got_rgb.shape}, want {want_rgb.shape}")
        return False

    mismatch = int(np.any(got_rgb != want_rgb, axis=-1).sum())
    if mismatch:
        print(f"FAIL {mismatch} mismatching pixels")
        return False
    print("PASS")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("design")
    # No fixed default: a design's default depends on what its check needs
    # to actually exercise (see DEFAULT_FRAMES) -- resolved below once the
    # design name is known, so the top-level Makefile's `check-%` target
    # (which never passes --frames) gets the right default per design.
    ap.add_argument("--frames", type=int, default=None)
    # Only for a MODE_CASES design (tt_um_vgacal_modes): run just the one
    # sub-case with this ui_in instead of all of them. Without it every
    # sub-case runs, which is what `make check` relies on.
    ap.add_argument("--ui-in", type=lambda s: int(s, 0), default=None)
    a = ap.parse_args(argv)

    frames = a.frames if a.frames is not None else DEFAULT_FRAMES.get(a.design, DEFAULT_FRAMES_FALLBACK)

    vgacap = vgacap_dir()
    ok = check(a.design, frames, vgacap, ui_in=a.ui_in)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
