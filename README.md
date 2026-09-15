# tt-vga-testpatterns

Calibration designs for checking a Tiny VGA capture pipeline end to end.
Each design is a [Tiny Tapeout](https://tinytapeout.com) template project
(`info.yaml`, `src/`, `docs/info.md`, `test/` with cocotb) that draws a
known picture, plus a Python reference renderer that produces the same
picture for pixel-exact comparison. The designs are built for the
iCE40UP5K Tiny Tapeout FPGA emulation boards (FabricFox breakout) with
`tt_fpga.py harden` from tt-support-tools, and the bitstreams are committed.

The capture pipeline they validate lives in
[mithro/vgacap](https://github.com/mithro/vgacap); the design and work log in
[mithro/tt-vga-capture](https://github.com/mithro/tt-vga-capture).

> **Caution: AI in use.** This project is being built with Claude Code.
> Check the designs and the reference renders before relying on them.

| Design | Purpose | `ui_in` |
|---|---|---|
| `tt_um_vgacal_bars` | all 64 colours in bars | unused |
| `tt_um_vgacal_grid` | one-pixel grid and border: sample phase and pixel alignment | unused |
| `tt_um_vgacal_counter` | frame and line counters encoded in pixel blocks | unused |
| `tt_um_vgacal_modes` | `ui_in` selects timing and sync polarities | `[1:0]` mode: 0/3 = 640x480@60, 1 = 800x600@60, 2 = 720x400@70; `[2]` invert HSync; `[3]` invert VSync |
| `tt_um_vgacal_prbs` | pseudo-random pixels seeded per frame: bit-error rate | unused |

## Development

- `make sim` -- run every design's cocotb tests (`uv run make -C
  designs/<design>/test`).
- `make check` -- simulate every design, wrap the dump into a vgacap
  capture stream, reconstruct it with `vgacap-frames`, and diff the result
  pixel-exactly against `tools/render.py` (`tools/check.py`). Needs a
  sibling checkout of [mithro/vgacap](https://github.com/mithro/vgacap)
  built at `<VGACAP>/build`, with its Python package at `<VGACAP>/python`;
  this defaults to `../vgacap` (i.e. next to this repo) but can be pointed
  elsewhere with the `VGACAP` environment variable, e.g.
  `VGACAP=/path/to/vgacap make check`. `tt_um_vgacal_modes` is checked
  once per `ui_in` sub-case (the three timings and the two polarity
  inversions of mode 0), each asserting the mode, clocks per line, lines
  per frame and sync polarities `vgacap-frames` reports as well as the
  picture; `uv run python tools/check.py tt_um_vgacal_modes --ui-in 2`
  runs just one of them.
- `make sync-common` -- copy `common/hvsync_generator.v` into every
  design's `src/` (the Tiny Tapeout hardening flow only reads a design's
  own `src/`); run this after editing the shared generator.
- See [`docs/timing.md`](docs/timing.md) for a real VESA sync-phase bug
  found (and fixed) in the shared VGA timing generator during Task 1.

## License

Apache-2.0, see [LICENSE](LICENSE).
