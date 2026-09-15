## What it does

A VGA calibration pattern in three different timings, driving a
[Tiny VGA PMOD](https://github.com/mole99/tiny-vga). `ui_in[1:0]` selects the mode
and `ui_in[3:2]` inverts the sync polarities, so one design exercises a capture
pipeline's mode detection, its clocks-per-line / lines-per-frame measurement and
its sync-polarity reporting without reprogramming anything.

| `ui[1:0]` | Mode | Clocks/line | Lines/frame | HSync | VSync | Bar width |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 640x480@60 | 800 (640 + 16 + 96 + 48) | 525 (480 + 10 + 2 + 33) | low | low | 10 px |
| 1 | 800x600@60 | 1056 (800 + 40 + 128 + 88) | 628 (600 + 1 + 4 + 23) | high | high | 12 px |
| 2 | 720x400@70 | 900 (720 + 18 + 108 + 54) | 449 (400 + 12 + 2 + 35) | low | high | 11 px |
| 3 | same as 0 | | | | | |

`ui[2]` inverts HSync's polarity and `ui[3]` inverts VSync's, each relative to its
mode's default in the table above. Inverting a polarity changes nothing else: the
pulse stays in the same place and keeps the same width, so the picture reconstructs
identically and only the reported polarity changes.

The picture is the `tt_um_vgacal_bars` pattern scaled to the mode's active width:
64 vertical bars, `bar_width = active_width / 64` pixels each (10, 12 and 11 px for
the three modes), colour index `c = min(x / bar_width, 63)`, the same on every
active row. 64 bars do not divide 800 or 720 evenly, so the *last* bar absorbs the
remainder: it is 44 px wide at 800x600 and 27 px wide at 720x400 (10 px in all the
modes that are 640 wide, where the division is exact). Bits 5..0 of `c` are
`rr gg bb`, exactly the layout the Tiny VGA PMOD wants.

`ui_in[3:0]` is only sampled at a frame boundary (the clock edge that wraps both
position counters back to zero), so changing the mode mid-frame takes effect at the
start of the *next* frame and never corrupts the frame being drawn. That also means
the timing counters are always at zero when a new mode's constants take effect, so
they can never be stranded beyond a shorter mode's totals.

Timing comes from `hvsync_generator_mux.v`, which is this repo's
`common/hvsync_generator.v` with its compile-time parameters replaced by a run-time
constant table. It keeps that module's VESA-correct sync phase (sync pulses computed
from the *next* position, so the HSync leading edge lands exactly `H_ACTIVE +
H_FRONT` clocks into the line and the VSync edge coincides with an HSync edge); see
`docs/timing.md` for why that matters. Colour outputs are blanked to black outside
the visible area, as VGA requires.

## How to test

Plug a Tiny VGA PMOD into the output header, connect a monitor, drive `ui_in[3:0]`
(DIP switches or the RP2040), and release reset.

1. With `ui_in = 0`, check the monitor reports 640x480 at 60 Hz and shows 64 bars,
   10 px each, sweeping through every 6-bit colour.
2. Set `ui_in = 1`: the monitor should re-sync to 800x600 at 60 Hz with 12 px bars
   (the rightmost bar wider, 44 px). Set `ui_in = 2` for 720x400 at 70 Hz with
   11 px bars (rightmost 27 px).
3. Set `ui_in = 4` (mode 0, HSync inverted) or `ui_in = 8` (mode 0, VSync
   inverted). Most monitors will still sync -- the pulses are unmoved, only their
   sense is flipped -- but will report the mode differently, or lose sync if they
   trust the polarity; a capture tool should report `hsync=pos` / `vsync=pos`.
4. Switch modes while running: the change appears at the start of the next frame,
   never as a torn frame.

The project clock should be the selected mode's pixel clock for a monitor to lock:
25.175 MHz for 640x480@60 (what `clock_hz` requests), 40 MHz for 800x600@60 and
28.322 MHz for 720x400@70. The design itself is clock-rate agnostic -- it counts
clocks, not nanoseconds -- so a capture tool that measures clocks per line sees the
right numbers at any clock rate.

## Pinout

| Pin | Direction | Function |
| --- | --------- | -------- |
| `ui[0]` | in | Mode select bit 0 |
| `ui[1]` | in | Mode select bit 1 |
| `ui[2]` | in | Invert HSync polarity |
| `ui[3]` | in | Invert VSync polarity |
| `ui[7:4]` | in | Unused |
| `uo[0]` | out | R1 (red, MSB) |
| `uo[1]` | out | G1 (green, MSB) |
| `uo[2]` | out | B1 (blue, MSB) |
| `uo[3]` | out | VSync |
| `uo[4]` | out | R0 (red, LSB) |
| `uo[5]` | out | G0 (green, LSB) |
| `uo[6]` | out | B0 (blue, LSB) |
| `uo[7]` | out | HSync |
| `uio[7:0]` | bidir | Unused (driven as inputs) |

## Clock

`clock_hz` is 25175000, the 640x480@60 pixel clock (mode 0). See "How to test" for
the other modes' nominal pixel clocks.
