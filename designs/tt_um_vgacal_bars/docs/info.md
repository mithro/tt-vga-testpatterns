## What it does

A VGA calibration pattern at 640x480@60 Hz, driving a
[Tiny VGA PMOD](https://github.com/mole99/tiny-vga). The screen is 64 vertical bars,
10 pixels wide each, running through every one of the 6-bit colour's 64 values in
order: colour index `c = (x / 10) & 0x3F` for `x` in `0..639`, the same on every row.
Bit 5 down to bit 0 of `c` are `rr gg bb`, which is exactly the layout the Tiny VGA
PMOD wants, so no expansion is needed.

This is a reference pattern for `tt-vga-capture`: the picture is simple enough to
reconstruct pixel-exactly from a captured stream and compare against a Python
renderer (`tools/render.py:bars`), so it doubles as an end-to-end calibration check
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
2. Check the screen shows 64 vertical bars sweeping smoothly from black on the left
   through every colour to white-ish on the right (repeating the 6-bit colour cycle).
3. Assert reset: the pattern is unaffected (it has no state besides the sync counters).

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
