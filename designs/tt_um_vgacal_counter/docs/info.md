## What it does

A VGA calibration pattern at 640x480@60 Hz, driving a
[Tiny VGA PMOD](https://github.com/mole99/tiny-vga). The picture encodes two
binary counters as blocks of white (`0x3F`) and blue (`0x03`) pixels, so a
capture pipeline that reconstructs frames from a captured stream can be
checked for dropped or duplicated frames and lines, not just correct colour:

- **Rows 0..59**: an 8-bit frame counter that increments once per frame, on
  the vsync leading edge. Eight 80x60-pixel blocks, block `i` (`x` in
  `[80*i, 80*i+80)`) is white if bit `7-i` of the counter is set, else blue
  -- block 0 (leftmost) is the most-significant bit. Frame 0 is the counter
  value during the first frame after reset.
- **Rows 60..479**: a 9-bit line number, redrawn in every 40-line band. A
  band starting at `y = 60 + 40*k` shows, in its first 20 rows, the 9-bit
  value `y` (the band's own first row) as nine 60x20-pixel blocks (`x` in
  `[60*j, 60*j+60)`, block `j` = bit `8-j`, most-significant first); the
  remaining 20 rows of the band, and any `x >= 540`, are black. The last
  band (`k=10`, `y=460..479`) is naturally truncated to just its 20 label
  rows, since the picture ends at `y=479`.

This is a reference pattern for `tt-vga-capture`: `tools/check.py` decodes
the frame counter directly from the reconstructed picture (it is visible IN
the picture) and diffs each reconstructed frame against
`tools/render.py:counter()` for that counter value, and asserts consecutive
reconstructed frames carry consecutive counter values -- so this design
doubles as the capture pipeline's frame-accounting check.

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
2. Check the top block row changes once per frame (roughly 60 times a
   second -- too fast to read by eye, but visibly "busy"), and that the
   line-number blocks below it read a plausible, monotonically increasing
   binary count down the screen.
3. Assert reset: the frame counter and sync counters zero, and the picture
   restarts from frame 0.

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
