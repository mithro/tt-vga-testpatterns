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

| Design | Purpose |
|---|---|
| `tt_um_vgacal_bars` | all 64 colours in bars |
| `tt_um_vgacal_grid` | one-pixel grid and border: sample phase and pixel alignment |
| `tt_um_vgacal_counter` | frame and line counters encoded in pixel blocks |
| `tt_um_vgacal_modes` | `ui_in` selects timing (640x480, 800x600, 720x400) and sync polarities |
| `tt_um_vgacal_prbs` | pseudo-random pixels seeded per frame: bit-error rate |

## License

Apache-2.0, see [LICENSE](LICENSE).
