## What it does

A VGA calibration pattern at 640x480@60 Hz, driving a
[Tiny VGA PMOD](https://github.com/mole99/tiny-vga). The picture is white (6-bit
colour `0x3F`) wherever `x % 8 == 0` or `y % 8 == 0`, plus a one-pixel white border
at `x == 0`, `x == 639`, `y == 0` and `y == 479`; everywhere else is dark red
(`0x10`).

Because the grid lines land on exact multiples of 8 (and the border marks the exact
edges of the addressable area), this pattern is a sample-phase and pixel-alignment
check: any off-by-one in sampling, cropping or timing shows up as a shifted or
broken grid rather than a uniform colour shift.

This is a reference pattern for `tt-vga-capture`: the picture is simple enough to
reconstruct pixel-exactly from a captured stream and compare against a Python
renderer (`tools/render.py:grid`), so it doubles as an end-to-end calibration check
for the capture pipeline.

Timing comes from `hvsync_generator.v`, the same module (and the same interface,
now parameterised) used by the Tiny Tapeout
[VGA Playground](https://tinytapeout.github.io/vga-playground/): 800 clocks per line
(640 visible + 16 front porch + 96 sync + 48 back porch) and 525 lines per frame
(480 visible + 10 + 2 + 33), with both sync pulses active low. Colour outputs are
blanked to black outside the visible area, as VGA requires.

## How to test

Plug a Tiny VGA PMOD into the output header, connect a monitor, and release reset.
The project clock must be 25.175 MHz (that is what `clock_hz` requests).

1. Check the monitor reports a 640x480 60 Hz mode.
2. Check the screen shows an 8-pixel white grid on a dark red background, with a
   solid white border one pixel in from every edge.
3. Assert reset: the pattern is unaffected (it has no state besides the sync
   counters).

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
