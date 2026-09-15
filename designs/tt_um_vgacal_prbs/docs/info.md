## What it does

A VGA calibration pattern at 640x480@60 Hz, driving a
[Tiny VGA PMOD](https://github.com/mole99/tiny-vga). The picture is a
per-pixel pseudo-random value, useful for bit-error-rate style checks of a
capture pipeline (a stuck or swapped signal bit tends to show up as a
structured artefact in an otherwise "random-looking" picture, rather than a
subtle colour shift):

- **Rows 0..7** (`y < 8`): the same 8-bit frame counter as
  `tt_um_vgacal_counter`, drawn as eight 80x8-pixel blocks (white = bit set,
  blue = bit clear, block 0 = most-significant bit), so a capture pipeline
  can tell which frame -- and hence which LFSR seed -- it is looking at.
- **Rows 8..479**: the low 6 bits of a 16-bit Fibonacci LFSR (taps
  `x^16+x^14+x^13+x^11+1`, i.e. `bit = s[0]^s[2]^s[3]^s[5]`,
  `s <= {bit, s[15:1]}`), seeded with `16'hACE1 ^ frame` (the 8-bit frame
  counter, zero-extended to 16 bits) at the first active pixel of row 8, and
  advanced once per active pixel after that, in raster order, continuously
  across rows (it does not reset at the start of each row).

This is a reference pattern for `tt-vga-capture`: `tools/render.py` runs the
identical LFSR in Python, `tools/check.py` decodes the frame counter from
the reconstructed picture's top strip and diffs the rest of each
reconstructed frame against `tools/render.py:prbs()` for that counter
value, and asserts consecutive reconstructed frames carry consecutive
counter values.

Timing comes from `hvsync_generator.v`, the same module (and the same
interface) used by `tt_um_vgacal_bars`/`tt_um_vgacal_grid`: 800 clocks per
line (640 visible + 16 front porch + 96 sync + 48 back porch) and 525 lines
per frame (480 visible + 10 + 2 + 33), with both sync pulses active low.
Colour outputs are blanked to black outside the visible area, as VGA
requires.

## How to test

Plug a Tiny VGA PMOD into the output header, connect a monitor, and release
reset. The project clock must be 25.175 MHz (that is what `clock_hz`
requests).

1. Check the monitor reports a 640x480 60 Hz mode.
2. Check the screen below the top strip shows visual noise with no obvious
   repeating structure, and that the top 8-row strip changes once per
   frame.
3. Assert reset: the frame counter and sync counters zero, and the picture
   restarts from frame 0 (so the LFSR reseeds with `16'hACE1 ^ 0`).

## Pinout

| Pin | Direction | Function |
| --- | --------- | -------- |
| `uo[0]` | out | R1 (red, MSB) |
| `uo[1]` | out | G1 (green, MSB) |
| `uo[2]` | out | B1 (blue, MSB) |
| `uo[3]` | out | VSync (active low) |
| `uo[4]` | out | R0 (red, LSB) |
| `uo[5]` | out | G0 (green, LSB) |
| `uo[6]` | out | B0 (blue, LSB) |
| `uo[7]` | out | HSync (active low) |
| `ui[7:0]` | in | Unused |
| `uio[7:0]` | bidir | Unused (driven as inputs) |

## Clock

`clock_hz` is 25175000, the standard 640x480@60 pixel clock.
