# SPDX-License-Identifier: Apache-2.0
"""End-to-end check: simulate a design, wrap the dump into a vgacap stream,
reconstruct frames with vgacap-frames, and diff the last frame against the
design's reference render, pixel-exactly.

    uv run tools/check.py tt_um_vgacal_bars
    uv run tools/check.py tt_um_vgacal_bars --frames 3

VGACAP (the vgacap checkout, with a build already at <VGACAP>/build and the
Python package at <VGACAP>/python) defaults to ../vgacap relative to the
repo root; override with the VGACAP environment variable.
"""
from __future__ import annotations

import argparse
import os
import pathlib
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
# Tiny VGA colour values).
REFERENCE_RENDERS = {
    "tt_um_vgacal_bars": render.bars,
    "tt_um_vgacal_grid": render.grid,
}


def vgacap_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("VGACAP", str(REPO_ROOT / ".." / "vgacap"))).resolve()


def design_sources(design: str) -> list[pathlib.Path]:
    src_dir = REPO_ROOT / "designs" / design / "src"
    sources = sorted(src_dir.glob("*.v"))
    if not sources:
        raise FileNotFoundError(f"no .v sources found in {src_dir}")
    return sources


def run_dump(design: str, frames: int, out_dir: pathlib.Path) -> pathlib.Path:
    # A few lines of margin beyond whole frames so vgaframe has enough
    # trailing samples to close out the last frame's last line.
    margin_clocks = 5 * H_TOTAL
    clocks = frames * H_TOTAL * V_TOTAL + margin_clocks
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
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(binary), str(stream_path), str(out_prefix)]
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.stdout


def last_frame_ppm(out_prefix: pathlib.Path) -> pathlib.Path:
    ppms = sorted(out_prefix.parent.glob(f"{out_prefix.name}-*.ppm"))
    if not ppms:
        raise FileNotFoundError(f"no frames written to {out_prefix}-NNNN.ppm")
    return ppms[-1]


def check(design: str, frames: int, vgacap: pathlib.Path) -> bool:
    if design not in REFERENCE_RENDERS:
        print(f"no reference render registered for {design!r}", file=sys.stderr)
        return False

    work_dir = REPO_ROOT / "tmp" / "check" / design
    work_dir.mkdir(parents=True, exist_ok=True)

    dump_path = run_dump(design, frames, work_dir)
    stream_path = work_dir / f"{design}.vgacap"
    dump_to_stream(dump_path, stream_path, desc=f"iverilog {design}", vgacap=vgacap)

    out_prefix = work_dir / "frames" / design
    run_vgacap_frames(vgacap, stream_path, out_prefix)

    ppm_path = last_frame_ppm(out_prefix)
    sys.path.insert(0, str(vgacap / "python"))
    from vgacap.ppm import read_ppm  # noqa: E402 (deferred: needs VGACAP on sys.path)

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
    ap.add_argument("--frames", type=int, default=3)
    a = ap.parse_args(argv)

    vgacap = vgacap_dir()
    ok = check(a.design, a.frames, vgacap)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
