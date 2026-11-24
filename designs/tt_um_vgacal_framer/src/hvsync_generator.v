/*
 * Copyright (c) 2024 Zachary Catlin
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// A parameterised VGA timing generator with the same interface as the
// "hvsync_generator" module in the Tiny Tapeout VGA Playground
// (https://tinytapeout.github.io/vga-playground/) and the same rotation of
// the line/frame (relative to the VESA standards) so that (hpos, vpos) ==
// (0, 0) is the first pixel of image data: hpos/vpos are the position of
// the pixel whose colour the design should output *this* cycle (registered,
// combinational colour computed from them lines up with hsync/vsync, which
// are also registered).
//
// It deliberately differs from the playground/demo module in one respect:
// that module computes hsync/vsync from the *current* (pre-increment)
// hpos/vpos, so its sync pulses are phase-delayed by one clock relative to
// hpos/vpos's own count -- its hsync leading edge lands on hpos 657 instead
// of 656, and (because vpos only advances on the hpos wrap, one clock after
// the hsync edge) its vsync edge falls 144 clocks into a line instead of
// coinciding with an hsync edge. A VGA sink delimits lines and samples
// vsync at hsync leading edges, so both are real, VESA-visible phase
// errors of one pixel and one line -- not something a capture tool can
// correct, since a real monitor sees the same shift. This generator
// computes the sync pulses from *next* hpos/vpos (hpos_n/vpos_n/vline_n
// below) instead, which puts the hsync leading edge on hpos == H_ACTIVE +
// H_FRONT exactly and the vsync edge on an hsync leading edge, as VESA
// requires. hpos/vpos themselves are unaffected (still the same
// free-running position counters), so a design that computes colour
// combinationally from hpos/vpos, blanked with display_on, needs no
// per-design correction for this.
module hvsync_generator #(
    // length of the addressable portion of a line (all H lengths in pixels)
    parameter H_ACTIVE = 640,
    // length of the right border and front porch of a line
    parameter H_FRONT = 16,
    // length of the HSync pulse
    parameter H_SYNC = 96,
    // length of the back porch and left border of a line
    parameter H_BACK = 48,
    // height of the addressable portion of a frame (all V heights in lines)
    parameter V_ACTIVE = 480,
    // height of the bottom border and front porch of a frame
    parameter V_FRONT = 10,
    // height of the VSync pulse
    parameter V_SYNC = 2,
    // height of the back porch and top border of a frame
    parameter V_BACK = 33,
    // hsync polarity: 0 = pulse is low (active low), 1 = pulse is high
    parameter H_POL = 0,
    // vsync polarity: 0 = pulse is low (active low), 1 = pulse is high
    parameter V_POL = 0
) (
    input  wire       clk,   // clock, assumed to be the pixel clock for the mode
    input  wire       reset, // reset (active HIGH)
    output reg        vsync, // VSync
    output reg        hsync, // HSync
    output reg  [9:0] hpos,  // horizontal position in frame
    output reg  [9:0] vpos,  // vertical position in frame
    output wire       display_on  // are we in the "addressable" part of the frame
                                   // (i.e., the part which actually contains image data)?
);

  localparam H_TOTAL = H_ACTIVE + H_FRONT + H_SYNC + H_BACK;
  localparam V_TOTAL = V_ACTIVE + V_FRONT + V_SYNC + V_BACK;
  localparam H_SYNC_START = H_ACTIVE + H_FRONT;

  // hpos/vpos *after* this edge -- the free-running position counters,
  // unaffected by anything below.
  wire       h_last = (hpos == H_TOTAL - 1);
  wire [9:0] hpos_n = h_last ? 10'd0 : hpos + 10'd1;
  wire [9:0] vpos_n = h_last ? ((vpos == V_TOTAL - 1) ? 10'd0 : vpos + 10'd1) : vpos;

  // The line number as the *sync* counts it: a VGA line begins at the hsync
  // leading edge, which is H_SYNC_START clocks into hpos's own line, so
  // from there on the sync is already on the next line (one line ahead of
  // vpos_n until vpos_n itself wraps at the start of the following line).
  wire [9:0] vline_n = (hpos_n >= H_SYNC_START)
                     ? ((vpos_n == V_TOTAL - 1) ? 10'd0 : vpos_n + 10'd1) : vpos_n;

  wire h_pulse = (hpos_n >= H_SYNC_START) && (hpos_n < H_SYNC_START + H_SYNC);
  wire v_pulse = (vline_n >= V_ACTIVE + V_FRONT) && (vline_n < V_ACTIVE + V_FRONT + V_SYNC);

  always @(posedge clk) begin
    if (reset) begin
      hsync <= H_POL ? 1'b0 : 1'b1;
      vsync <= V_POL ? 1'b0 : 1'b1;
      hpos  <= 10'd0;
      vpos  <= 10'd0;
    end else begin
      hsync <= H_POL ? h_pulse : ~h_pulse;
      vsync <= V_POL ? v_pulse : ~v_pulse;
      hpos  <= hpos_n;
      vpos  <= vpos_n;
    end
  end

  assign display_on = (hpos < H_ACTIVE) && (vpos < V_ACTIVE);

endmodule
