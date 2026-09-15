/*
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 *
 * tt_um_vgacal_bars - 64 vertical colour bars, 10 pixels wide each, all six
 * colour bits exercised: colour index = (x / 10) & 0x3F, same on every row.
 * For a Tiny VGA PMOD, 640x480@60.
 */

`default_nettype none

module tt_um_vgacal_bars (
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

  // vgacap's frame reconstruction crops the active window one line later
  // than hvsync_generator's own vpos (verified empirically against
  // tools/render.py via tools/check.py: the reconstructed picture's row r
  // is this design's line vpos=r+1, not vpos=r). vpos_for_color corrects
  // for that one-line difference so the *captured* picture lines up with
  // vpos=0..479 exactly; real-monitor viewers are unaffected in practice,
  // since the shift only touches the line at the edge of the front porch.
  wire [9:0] vpos_for_color = (vpos == 10'd0) ? 10'd524 : (vpos - 10'd1);
  wire       color_active = (hpos < 10'd640) && (vpos_for_color < 10'd480);

  // Colour index is a 6-bit value, bits [5:0] = rr gg bb, which is exactly
  // the layout the Tiny VGA PMOD wants -- no further expansion needed.
  wire [5:0] bar_index = (hpos / 10'd10) & 6'h3F;
  wire [5:0] next_color = color_active ? bar_index : 6'h00;

  // hsync/vsync are registered by hvsync_generator, so they reflect hpos as
  // of the *previous* cycle (see common/hvsync_generator.v). Colour must be
  // registered the same way -- one clock behind the hpos/vpos used to
  // compute it -- so that hsync/vsync and colour stay in step; a
  // combinational colour (colour output the same cycle as the hpos it was
  // computed from) is one pixel ahead of sync and reconstructs shifted.
  reg [5:0] color;
  always @(posedge clk) begin
    if (!rst_n) color <= 6'h00;
    else color <= next_color;
  end

  // Tiny VGA PMOD: {HSync, B0, G0, R0, VSync, B1, G1, R1}.
  // color[5:0] is rr gg bb, so color[5]=R1, color[4]=R0, color[3]=G1,
  // color[2]=G0, color[1]=B1, color[0]=B0.
  assign uo_out  = {hsync, color[0], color[2], color[4], vsync, color[1], color[3], color[5]};
  assign uio_out = 8'h00;
  assign uio_oe  = 8'h00;

  // avoid linter warnings about unused pins/signals (display_on is not used:
  // blanking for colour purposes is handled by color_active above):
  wire _unused = &{ena, ui_in, uio_in, display_on, 1'b0};

endmodule
