# SPDX-License-Identifier: Apache-2.0
"""Build every design's iCE40UP5K bitstream for the Tiny Tapeout FPGA
emulation boards (FabricFox v2 breakout) and write bitstreams/.

    uv run --no-project python tools/build.py
    uv run --no-project python tools/build.py tt_um_vgacal_modes

This clones TinyTapeout/tt-support-tools at a pinned commit (see
TT_SUPPORT_TOOLS_COMMIT) into tmp/tt-support-tools and runs its
`tt_fpga.py harden --breakout-target fabricfox` once per design, which is
yosys `synth_ice40 -top tt_fpga_top -json`, then `nextpnr-ice40
--pcf-allow-unconstrained --seed N --freq F --package sg48 --up5k --pcf
fpga/tt_fpga_fabricfoxv2.pcf`, then `icepack`. TT_FPGA_SEED and
TT_FPGA_FREQ (the environment variables tt_fpga.py reads) are pinned to
SEED and TARGET_FREQ_MHZ here so the committed bitstreams are reproducible
and are timed against the 25 MHz the boards clock a project at, not
tt_fpga.py's own 12 MHz default.

Each design is hardened in a *copy* under tmp/build/<design>/, not in
designs/<design>/: tt_fpga.py writes a generated `_tt_fpga_top.v` into the
project's src/ and a build/ directory next to it, neither of which belongs
in the checkout. Only the resulting .bin is copied back, to
bitstreams/<design>.bin, alongside a generated bitstreams/README.md
recording each design's size, resource usage and nextpnr max frequency plus
the exact tool and tt-support-tools versions used.

This script is deliberately stdlib-only (it runs under `uv run
--no-project`); the heavier dependencies tt_fpga.py itself needs are
supplied per-invocation with `uv run --with`.

The oss-cad-suite that provides yosys/nextpnr-ice40/icepack defaults to
/home/tim/tools/oss-cad-suite/bin and can be pointed elsewhere with the
OSS_CAD_SUITE_BIN environment variable. It is a large download, which is
why this build is not part of CI -- CI checks the committed bitstreams with
tools/check_bitstreams.py instead.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DESIGNS_DIR = REPO_ROOT / "designs"
BITSTREAMS_DIR = REPO_ROOT / "bitstreams"
TMP_DIR = REPO_ROOT / "tmp"

# tt-support-tools, pinned. This was the tip of main on 2026-09-15; bump it
# deliberately (and rebuild every bitstream) rather than tracking main, so a
# rebuild of one design cannot silently differ from the others.
TT_SUPPORT_TOOLS_REPO = "https://github.com/TinyTapeout/tt-support-tools.git"
TT_SUPPORT_TOOLS_COMMIT = "01d5d2814fa9dd61e9d211e0b235a4a592a9316a"

# tt_fpga.py imports project.py, which pulls in a fair chunk of the full
# tt-support-tools dependency set even though hardening only needs info.yaml
# parsed. Installed on the fly by `uv run --with`, not added to this repo's
# own pyproject.toml, since nothing but this script needs them. Python 3.13:
# some of these (klayout in particular) have no 3.14 wheels yet.
TT_FPGA_PYTHON = "3.13"
TT_FPGA_DEPS = [
    "pyyaml", "chevron", "klayout", "requests", "mistune", "cairosvg",
    "python-frontmatter", "configupdater", "matplotlib", "gdstk", "mpremote",
    "GitPython",
]

DEFAULT_OSS_CAD_SUITE_BIN = "/home/tim/tools/oss-cad-suite/bin"

# The Welland boards clock a project at 25 MHz, so that is what the place
# and route must close timing at; SEED is pinned for reproducibility.
TARGET_FREQ_MHZ = 25
SEED = 10

# "Info: Max frequency for clock 'clk$SB_IO_IN_$glb_clk': 37.02 MHz (PASS at 25.00 MHz)"
NEXTPNR_FMAX_RE = re.compile(
    r"^Info: Max frequency for clock\s+'(?P<clock>[^']+)':\s+(?P<mhz>[\d.]+) MHz\s+"
    r"\((?P<verdict>PASS|FAIL) at (?P<target>[\d.]+) MHz\)"
)
# "Info: 	         ICESTORM_LC:     150/   5280     2%"
NEXTPNR_UTIL_RE = re.compile(r"^Info:\s+(?P<kind>\w+):\s+(?P<used>\d+)/\s*(?P<total>\d+)")
# "      74   SB_LUT4" in yosys's final "Printing statistics" block
YOSYS_CELL_RE = re.compile(r"^\s+(?P<count>\d+)\s+(?P<cell>SB_\w+)\s*$")


def oss_cad_suite_bin() -> pathlib.Path:
    return pathlib.Path(os.environ.get("OSS_CAD_SUITE_BIN", DEFAULT_OSS_CAD_SUITE_BIN))


def build_env() -> dict[str, str]:
    """The environment tt_fpga.py is run in: oss-cad-suite first on PATH (so
    its yosys/nextpnr-ice40/icepack are the ones used, whatever else is
    installed), and the seed/frequency it reads pinned."""
    env = dict(os.environ)
    env["PATH"] = f"{oss_cad_suite_bin()}{os.pathsep}{env.get('PATH', '')}"
    env["TT_FPGA_SEED"] = str(SEED)
    env["TT_FPGA_FREQ"] = str(TARGET_FREQ_MHZ)
    return env


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def check_tools(env: dict[str, str]) -> dict[str, str]:
    """Verify yosys/nextpnr-ice40/icepack are on PATH and capture the version
    strings recorded in bitstreams/README.md."""
    bindir = oss_cad_suite_bin()
    if not bindir.is_dir():
        sys.exit(
            f"oss-cad-suite not found at {bindir}; set OSS_CAD_SUITE_BIN to the "
            f"bin/ directory of an oss-cad-suite install"
        )
    versions = {}
    version_file = bindir.parent / "VERSION"
    if version_file.is_file():
        versions["oss-cad-suite"] = version_file.read_text().strip()
    for tool, args in (("yosys", ["--version"]), ("nextpnr-ice40", ["--version"])):
        exe = shutil.which(tool, path=env["PATH"])
        if not exe:
            sys.exit(f"{tool} not found on PATH ({env['PATH'].split(os.pathsep)[0]})")
        out = subprocess.run([exe, *args], check=True, capture_output=True, text=True)
        versions[tool] = (out.stdout + out.stderr).strip().splitlines()[0]
    # icestorm's icepack has no --version flag of its own, so it is only
    # checked for existence; its version is the oss-cad-suite build above.
    if not shutil.which("icepack", path=env["PATH"]):
        sys.exit("icepack not found on PATH")
    return versions


def ensure_tt_support_tools() -> pathlib.Path:
    """A shallow checkout of tt-support-tools at TT_SUPPORT_TOOLS_COMMIT in
    tmp/, fetched by SHA so the pin is exact rather than "whatever main was
    when the clone ran"."""
    dest = TMP_DIR / "tt-support-tools"
    git = ["git", "-C", str(dest)]
    if (dest / ".git").is_dir():
        head = subprocess.run(
            [*git, "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        if head == TT_SUPPORT_TOOLS_COMMIT:
            print(f"tt-support-tools already at {head[:12]} in {dest}")
            return dest
        print(f"tt-support-tools at {head[:12]}, want {TT_SUPPORT_TOOLS_COMMIT[:12]}: refetching")
    else:
        dest.mkdir(parents=True, exist_ok=True)
        run(["git", "init", "--quiet", str(dest)])
        run([*git, "remote", "add", "origin", TT_SUPPORT_TOOLS_REPO])
    run([*git, "fetch", "--quiet", "--depth", "1", "origin", TT_SUPPORT_TOOLS_COMMIT])
    run([*git, "checkout", "--quiet", "--detach", TT_SUPPORT_TOOLS_COMMIT])
    return dest


def all_designs() -> list[str]:
    return sorted(p.name for p in DESIGNS_DIR.iterdir() if (p / "info.yaml").is_file())


def harden(design: str, tt_tools: pathlib.Path, env: dict[str, str]) -> pathlib.Path:
    """Run tt_fpga.py harden on a throwaway copy of the design and return its
    build directory (holding the .bin and both tool logs)."""
    work = TMP_DIR / "build" / design
    if work.exists():
        shutil.rmtree(work)
    work.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DESIGNS_DIR / design, work)

    with_args = []
    for dep in TT_FPGA_DEPS:
        with_args += ["--with", dep]
    run(
        [
            "uv", "run", "--no-project", "--python", TT_FPGA_PYTHON, *with_args,
            "python", str(tt_tools / "tt_fpga.py"),
            "--project-dir", str(work),
            "harden", "--breakout-target", "fabricfox",
        ],
        env=env,
        cwd=REPO_ROOT,
    )
    return work / "build"


def parse_nextpnr_log(path: pathlib.Path) -> dict:
    """The final max frequency and the device utilisation from a
    nextpnr-ice40 log. nextpnr reports the max frequency several times as
    placement and routing progress; the last one is the one that counts."""
    fmax: dict | None = None
    util: dict[str, tuple[int, int]] = {}
    for line in path.read_text(errors="replace").splitlines():
        m = NEXTPNR_FMAX_RE.match(line)
        if m:
            fmax = {
                "clock": m["clock"],
                "mhz": float(m["mhz"]),
                "pass": m["verdict"] == "PASS",
                "target_mhz": float(m["target"]),
            }
            continue
        m = NEXTPNR_UTIL_RE.match(line)
        if m:
            # Later blocks repeat the same numbers; last wins.
            util[m["kind"]] = (int(m["used"]), int(m["total"]))
    if fmax is None:
        raise ValueError(f"no max frequency line found in {path}")
    return {"fmax": fmax, "util": util}


def parse_yosys_log(path: pathlib.Path) -> dict[str, int]:
    """The SB_* cell counts from the last "Printing statistics" block of a
    yosys log (the post-synth_ice40 one)."""
    text = path.read_text(errors="replace")
    marker = "Printing statistics."
    tail = text[text.rindex(marker):] if marker in text else text
    cells: dict[str, int] = {}
    for line in tail.splitlines():
        m = YOSYS_CELL_RE.match(line)
        if m:
            # The block prints local counts and then the same totals again
            # for the whole hierarchy; last wins.
            cells[m["cell"]] = int(m["count"])
    if not cells:
        raise ValueError(f"no SB_* cell counts found in {path}")
    return cells


def summarise(design: str, build_dir: pathlib.Path) -> dict:
    pnr = parse_nextpnr_log(build_dir / "02-nextpnr.log")
    cells = parse_yosys_log(build_dir / "01-synth.log")
    luts = cells.get("SB_LUT4", 0)
    ffs = sum(n for cell, n in cells.items() if cell.startswith("SB_DFF"))
    lc_used, lc_total = pnr["util"].get("ICESTORM_LC", (0, 0))
    return {
        "design": design,
        "bin": build_dir / f"{design}.bin",
        "size": (build_dir / f"{design}.bin").stat().st_size,
        "luts": luts,
        "ffs": ffs,
        "lc_used": lc_used,
        "lc_total": lc_total,
        "fmax_mhz": pnr["fmax"]["mhz"],
        "fmax_pass": pnr["fmax"]["pass"],
        "target_mhz": pnr["fmax"]["target_mhz"],
    }


def write_readme(results: list[dict], versions: dict[str, str]) -> pathlib.Path:
    path = BITSTREAMS_DIR / "README.md"
    lines = [
        "<!-- SPDX-License-Identifier: Apache-2.0 -->",
        "",
        "# Bitstreams",
        "",
        "iCE40UP5K bitstreams for the Tiny Tapeout FPGA emulation boards",
        "(FabricFox v2 breakout, `sg48` package), one per design. **Generated by",
        "`tools/build.py` -- do not edit by hand**; rerun",
        "`uv run --no-project python tools/build.py` to regenerate both the",
        "bitstreams and this file.",
        "",
        f"Place and route targets {TARGET_FREQ_MHZ} MHz (the rate the boards clock a",
        f"project at) with `--seed {SEED}`; every design must report a max frequency",
        "at or above that target, which `tools/build.py` enforces.",
        "",
        "| Design | Size (bytes) | LUT4 | FF | Logic cells | Max frequency |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        lc = f"{r['lc_used']} / {r['lc_total']}" if r["lc_total"] else str(r["lc_used"])
        lines.append(
            f"| `{r['design']}` | {r['size']} | {r['luts']} | {r['ffs']} | {lc} | "
            f"{r['fmax_mhz']:.2f} MHz |"
        )
    lines += [
        "",
        "LUT4 and FF counts are yosys's post-`synth_ice40` cell counts; \"logic",
        "cells\" is nextpnr's `ICESTORM_LC` utilisation (a LUT and its flip-flop",
        "share one cell, so it is not the sum of the two columns). Max frequency is",
        "nextpnr's final post-routing estimate for the design's clock.",
        "",
        "## Provenance",
        "",
        f"- tt-support-tools: [`{TT_SUPPORT_TOOLS_COMMIT}`]"
        f"(https://github.com/TinyTapeout/tt-support-tools/commit/{TT_SUPPORT_TOOLS_COMMIT})",
        "  (`tt_fpga.py harden --breakout-target fabricfox`)",
    ]
    for name, version in versions.items():
        lines.append(f"- {name}: `{version}`")
    lines += [
        "",
        "The flow is yosys `synth_ice40 -top tt_fpga_top -json`, then",
        "`nextpnr-ice40 --pcf-allow-unconstrained --seed "
        f"{SEED} --freq {TARGET_FREQ_MHZ} --package sg48 --up5k --pcf "
        "fpga/tt_fpga_fabricfoxv2.pcf`, then `icepack`.",
        "",
    ]
    BITSTREAMS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "designs", nargs="*",
        help="designs to build (default: all of them). bitstreams/README.md is "
             "only rewritten when every design is built, so it never lists a "
             "stale subset.",
    )
    a = ap.parse_args(argv)

    designs = a.designs or all_designs()
    unknown = [d for d in designs if not (DESIGNS_DIR / d / "info.yaml").is_file()]
    if unknown:
        sys.exit(f"no such design(s): {', '.join(unknown)}")

    env = build_env()
    versions = check_tools(env)
    for name, version in versions.items():
        print(f"{name}: {version}")
    tt_tools = ensure_tt_support_tools()

    BITSTREAMS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for design in designs:
        build_dir = harden(design, tt_tools, env)
        r = summarise(design, build_dir)
        shutil.copyfile(r["bin"], BITSTREAMS_DIR / f"{design}.bin")
        results.append(r)
        print(
            f"{design}: {r['size']} bytes, {r['luts']} LUT4, {r['ffs']} FF, "
            f"{r['lc_used']}/{r['lc_total']} LC, Fmax {r['fmax_mhz']:.2f} MHz "
            f"({'PASS' if r['fmax_pass'] else 'FAIL'} at {r['target_mhz']:.2f} MHz)",
            flush=True,
        )

    slow = [r for r in results if not r["fmax_pass"]]
    if slow:
        for r in slow:
            print(
                f"FAIL {r['design']}: max frequency {r['fmax_mhz']:.2f} MHz is below "
                f"the {r['target_mhz']:.2f} MHz target",
                file=sys.stderr,
            )
        return 1

    if a.designs:
        print(
            "built a subset: bitstreams/README.md left alone (rerun without "
            "arguments to regenerate it)"
        )
    else:
        print(f"wrote {write_readme(results, versions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
