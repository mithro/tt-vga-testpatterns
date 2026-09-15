# Timing: a real one-pixel/one-line sync-phase bug, and why it wasn't vgacap

While building Task 1's pixel-exact check (`tools/check.py`: simulate a
design, capture it through `vgacap`'s stream/frame-reconstruction pipeline,
diff the reconstructed picture against `tools/render.py` pixel-for-pixel),
the reconstructed picture came out shifted by one pixel horizontally and one
line vertically relative to the design's own `hpos`/`vpos`. The first
instinct was to "correct" for that in each design (registering colour, and
offsetting `vpos`). That was wrong: both were compensating, in the wrong
layer, for a real phase bug in the *generator* that `common/hvsync_generator.v`
had copied faithfully from the Tiny Tapeout VGA Playground / fpgas.online
demo's `hvsync_generator.v`. This note records the finding so later designs
in this repo (and, ideally, the upstream playground/demo module) don't
reintroduce it.

## What VESA requires

A VGA line begins at the hsync leading edge; a VGA sink (a monitor, or a
capture tool reconstructing frames from a sync stream) starts counting a new
line's pixels from there, and delimits a new frame by sampling vsync *at*
that same hsync edge. So, for correct video:

- the hsync leading edge must land exactly `H_ACTIVE + H_FRONT` clocks into
  the active+front-porch part of the line (`hpos == 656` for 640x480@60);
- the vsync leading edge must coincide with an hsync leading edge, not fall
  in the middle of a line.

`vgacap`'s frame reconstruction (`vgacap/src/frame/timing.c`,
`vgacap/src/frame/frame.c`) does exactly this: it marks a new line each time
the incoming hsync sample enters its pulse level, and only samples vsync at
that same instant. That is the standard behaviour, and it needed no change.

## The bug

The playground/demo generator (and, by direct inheritance, the first cut of
`common/hvsync_generator.v`) computes `hsync`/`vsync` from the *current*
(pre-increment) `hpos`/`vpos`, using a registered (`<=`) assignment that
updates on the same edge as `hpos`/`vpos` themselves:

```verilog
hsync <= ~((hpos >= H_ACTIVE+H_FRONT) & (hpos < H_ACTIVE+H_FRONT+H_SYNC));
hpos  <= (hpos >= H_TOTAL-1) ? 0 : hpos + 1;
```

Because both are non-blocking assignments evaluated from the *same*
pre-edge `hpos`, the value visible on `hsync` next cycle reflects `hpos` as
it was *last* cycle, not the `hpos` that will be current next cycle. Sync
therefore lags the position counters by one clock:

- **Horizontally:** `hsync` first reads low on the cycle where `hpos == 657`
  (measured: falling edges at `hpos,vpos = (657,0), (657,1), (657,2)`), not
  656. A VGA sink's column 0 is `H_SYNC + H_BACK` (144) clocks after that
  edge, i.e. sample `657 + 144 ≡ hpos 1` -- one pixel late.
- **Vertically:** because `vpos` only advances on the `hpos` wrap (one clock
  *after* the hsync leading edge that starts a line), the vsync leading edge
  falls on `(hpos, vpos) = (1, 490)` -- 144 clocks *into* an hsync-delimited
  line, not on the hsync edge itself (measured: `k=392001 →
  (hpos,vpos)=(1,490)`, i.e. 144 clocks after the previous hsync edge and
  656 clocks before the next one). A sink that samples vsync at hsync edges
  (every real sink, `vgacap` included) attributes that pulse to the
  *following* line, one line late.

**This is a property of the source, not of the capture tool**: a real
monitor delimits lines and samples vsync at hsync edges too, so it sees the
exact same one-pixel/one-line shift a design built on the unmodified
generator would show combinational colour for. It is not something a
capture/reconstruction tool can or should correct.

**The demo is not actually pixel-exact.** Simulating the unmodified
fpgas.online `tt_um_vga_pattern` and reconstructing it: its 80-pixel colour
bars land at columns 79/159/239/319 (nominal 80/160/240/320) and its
top/bottom split lands at row 239 (nominal 240) -- shifted by exactly one
pixel and one line, same as above. Its features are coarse enough (80 px /
half a screen) that a casual look never revealed the shift; this repo's
1-pixel-wide `tt_um_vgacal_grid` picture did.

## Cycle timelines (measured, from the raw simulated dump)

Sample *n* is one clock cycle, sampled on the falling edge mid-cycle (the
same phase `tools/dump_uo_out.py`'s testbench and vgacap's PIO sampler both
use). With the *original* (unmodified) generator:

```
hpos[n+1] = hpos[n] + 1 (mod 800)          vpos[n+1] = vpos[n] + 1 when hpos[n] == 799
hsync[n]  = ~pulse_h(hpos[n] - 1)          vsync[n]  = ~pulse_v(vpos[n-1])
```

First hsync falling edges: `k = 657, 1457, 2257 → (hpos,vpos) = (657,0),
(657,1), (657,2)`. First vsync falling edge: `k = 392001 → (hpos,vpos) =
(1,490)` -- 144 clocks after the hsync edge at `k = 391344`
(`(657, 489)`... i.e. mid-line) and 656 clocks before the next hsync edge at
`k = 392657`.

A probe design (colour = `vpos[5:0]` in columns 0..319, `hpos[5:0]` in
columns 320..639, combinational, demo-style, generator unmodified)
reconstructs with the *original* generator as:

```
row   0: vpos-ident = 1    col 320 (hpos-ident) = 1 (hpos 321), col 639 = 0 (blank, hpos 640)
row   1: vpos-ident = 2
row 478: vpos-ident = 31   (= 479 & 0x3F)
row 479: all zero          (blank: vpos 480)
```

i.e. reconstructed `row r ← vpos r+1`, `col c ← hpos c+1`: exactly the
"design registers colour, +1-line vpos offset" pattern the first cut of
`tt_um_vgacal_bars`/`tt_um_vgacal_grid` (wrongly) compensated for in RTL.

## The fix

Fixed once, in `common/hvsync_generator.v`: compute `h_pulse`/`v_pulse` from
*next* `hpos`/`vpos` (`hpos_n`/`vpos_n`) instead of the current
(pre-increment) values, and additionally track the line number the way sync
counts it (`vline_n`: one line ahead of `vpos_n` from the hsync leading edge
onward, since sync considers itself on the next line from that point). This
puts the hsync leading edge exactly on `hpos == H_ACTIVE + H_FRONT` and the
vsync leading edge exactly on an hsync leading edge, as VESA requires.
`hpos`/`vpos` themselves are untouched -- still the same free-running
position counters -- so no design-side compensation is needed: colour is
plain combinational from `hpos`/`vpos`, blanked by `display_on`.

Verified by simulation: with the fixed generator, both `tt_um_vgacal_bars`
and `tt_um_vgacal_grid` (plain combinational colour, no per-design
correction) reconstruct through the *unmodified* `vgacap` pipeline with
**zero mismatching pixels**, and the probe design above reconstructs
`row r ← vpos r`, `col c ← hpos c` with the blanking edges (`col 639`,
`row 479`) in the right place.

## For later designs / the playground authors

Every Tiny Tapeout VGA design built on the stock (unfixed) playground
generator has this same one-pixel/one-line phase error, whether or not it's
ever pixel-checked closely enough to notice. `common/hvsync_generator.v` in
this repo fixes it while keeping the same parameter and port interface, so:

- Designs in this repo (`counter`, `modes`, `prbs`, ...) should keep using
  plain combinational colour from `hpos`/`vpos`, blanked by `display_on` --
  no registered-colour or `vpos`-offset workaround needed or wanted.
- A design ported *from* the playground gets a one-pixel/one-line
  *improvement* from this generator, not a regression, since the playground
  version is the one with the phase bug.
- This is not something `vgacap` should change: it delimits lines and
  samples vsync at hsync edges, which is the standard, VESA-correct
  behaviour, and a real monitor would show the same shift the unfixed
  generator produces. If the upstream playground/demo `hvsync_generator.v`
  is ever revisited, the fix in `common/hvsync_generator.v` (compute the
  sync pulses from the *next* `hpos`/`vpos` rather than the current one) is
  the one to port back.
