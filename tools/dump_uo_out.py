# SPDX-License-Identifier: Apache-2.0
"""Simulate a Tiny Tapeout project with Icarus Verilog and dump uo_out once per
clock (one byte per clock) to a binary file.

    uv run --no-project tools/dump_uo_out.py --top tt_um_vga_pattern \
        --out tmp/vga_pattern.bin --clocks 840000 src/a.v src/b.v

The dump is sampled on the falling clock edge, like the PIO sampler.
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", required=True)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--clocks", type=int, default=2 * 800 * 525)
    ap.add_argument("--ui-in", type=int, default=0)
    ap.add_argument("--build-dir", type=pathlib.Path, default=pathlib.Path("tmp/sim"))
    ap.add_argument("sources", nargs="+")
    a = ap.parse_args()

    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not iverilog or not vvp:
        print("iverilog/vvp not on PATH", file=sys.stderr)
        return 2
    a.build_dir.mkdir(parents=True, exist_ok=True)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    vvp_file = a.build_dir / f"{a.top}.vvp"
    cmd = [iverilog, "-g2012", f"-DTOP={a.top}", "-o", str(vvp_file), str(HERE / "tb_dump_uo_out.v"), *a.sources]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)
    cmd = [vvp, "-n", str(vvp_file), f"+out={a.out}", f"+clocks={a.clocks}", f"+ui_in={a.ui_in}"]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"wrote {a.out} ({a.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
