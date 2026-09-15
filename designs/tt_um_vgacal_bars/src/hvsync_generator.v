/*
 * Copyright (c) 2024 Zachary Catlin
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// This is a parameterised version of the "hvsync_generator" module from the
// Tiny Tapeout VGA Playground (https://tinytapeout.github.io/vga-playground/),
// with the timing constants for a mode passed in as parameters instead of
// being hard-coded for 640x480@60. With the default parameters (640x480@60,
// both syncs active low) it is bit-for-bit identical to the playground
// version, so designs ported from there keep behaving the same way.
//
// As in the playground version, we rotate the parts of the line and frame
// (relative to the VESA standards) so that (hpos, vpos) == (0, 0) is the
// first pixel of image data: hpos/vpos are the position of the pixel whose
// colour the design should output *next* cycle (both are registered, one
// clock ahead of hsync/vsync, which are also registered) -- follow this
// same one-cycle convention in the design so that hsync/vsync and colour
// line up exactly.
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

  wire h_pulse = (hpos >= (H_ACTIVE + H_FRONT)) & (hpos < (H_ACTIVE + H_FRONT + H_SYNC));
  wire v_pulse = (vpos >= (V_ACTIVE + V_FRONT)) & (vpos < (V_ACTIVE + V_FRONT + V_SYNC));

  always @(posedge clk) begin
    if (reset) begin
      hsync <= H_POL ? 1'b0 : 1'b1;
      vsync <= V_POL ? 1'b0 : 1'b1;
      hpos  <= 10'd0;
      vpos  <= 10'd0;
    end else begin
      hsync <= H_POL ? h_pulse : ~h_pulse;
      vsync <= V_POL ? v_pulse : ~v_pulse;
      hpos  <= (hpos >= (H_TOTAL - 1)) ? 10'd0 : hpos + 10'd1;
      if (hpos >= (H_TOTAL - 1)) begin
        vpos <= (vpos >= (V_TOTAL - 1)) ? 10'd0 : vpos + 10'd1;
      end
    end
  end

  assign display_on = (hpos < H_ACTIVE) && (vpos < V_ACTIVE);

endmodule
