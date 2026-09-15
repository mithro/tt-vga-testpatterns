/*
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 *
 * tt_um_vgacal_grid - white (0x3F) one-pixel grid every 8 pixels, plus a
 * one-pixel white border around the whole frame, dark red (0x10) elsewhere.
 * Useful for checking sample phase and pixel alignment. For a Tiny VGA
 * PMOD, 640x480@60.
 */

`default_nettype none

module tt_um_vgacal_grid (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire       hsync, vsync, display_on;
  wire [9:0] hpos, vpos;

  hvsync_generator vga_sync (
      .clk       (clk),
      .reset     (~rst_n),
      .hsync     (hsync),
      .vsync     (vsync),
      .hpos      (hpos),
      .vpos      (vpos),
      .display_on(display_on)
  );

  // hpos==0 and vpos==0 are already covered by grid (0 % 8 == 0), so border
  // only needs to add the two edges the 8-pixel grid never lands on:
  // hpos==639 and vpos==479.
  wire border   = (hpos == 10'd639) || (vpos == 10'd479);
  wire grid     = (hpos[2:0] == 3'b000) || (vpos[2:0] == 3'b000);
  wire white    = border || grid;

  // Colour index is a 6-bit value, bits [5:0] = rr gg bb, which is exactly
  // the layout the Tiny VGA PMOD wants -- no further expansion needed.
  // Combinational from hpos/vpos, blanked by display_on: hvsync_generator's
  // sync pulses are phase-corrected (see its header comment) so this lines
  // up with hsync/vsync exactly, with no per-design correction needed.
  wire [5:0] pixel_index = white ? 6'h3F : 6'h10;
  wire [5:0] color = display_on ? pixel_index : 6'h00;

  // Tiny VGA PMOD: {HSync, B0, G0, R0, VSync, B1, G1, R1}.
  // color[5:0] is rr gg bb, so color[5]=R1, color[4]=R0, color[3]=G1,
  // color[2]=G0, color[1]=B1, color[0]=B0.
  assign uo_out  = {hsync, color[0], color[2], color[4], vsync, color[1], color[3], color[5]};
  assign uio_out = 8'h00;
  assign uio_oe  = 8'h00;

  // avoid linter warnings about unused pins:
  wire _unused = &{ena, ui_in, uio_in, 1'b0};

endmodule
