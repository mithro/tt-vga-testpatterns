/*
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 *
 * tt_um_vgacal_counter - an 8-bit frame counter and 9-bit line-number
 * strips, both drawn as binary blocks, for checking that a capture
 * pipeline reconstructs every frame exactly once (no drops, no repeats).
 * For a Tiny VGA PMOD, 640x480@60.
 *
 * Picture (see docs/info.md for the full description):
 *   - Rows 0..59: eight 80x60 blocks. Block i (x in [80i, 80i+80)) is
 *     white (0x3F) if bit (7-i) of the frame counter is set, else blue
 *     (0x03) -- i.e. block 0 (leftmost) is the MSB.
 *   - Rows 60..479: in every 40-line band starting at y = 60 + 40k, the
 *     first 20 rows show the 9-bit line number of that band's first row
 *     (60 + 40k) as nine 60x20 blocks (x in [60j, 60j+60), block j = bit
 *     8-j), the remaining 20 rows (and any x >= 540) are black. The last
 *     band (k=10, y=460..479) is truncated to exactly its 20 label rows.
 */

`default_nettype none

module tt_um_vgacal_counter (
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

  // 8-bit frame counter: increments once per frame, on the vsync leading
  // edge (vsync is active low here, so this is the high-to-low
  // transition). Frame 0 is the counter value during the first frame
  // after reset. The increment only ever happens during vertical
  // blanking -- after the active area of the frame that just finished and
  // before the active area of the next one begins -- so the active-area
  // picture for frame N always shows frame == N, with no race against the
  // picture logic below.
  reg [7:0] frame;
  reg       vsync_prev;
  always @(posedge clk) begin
    if (!rst_n) begin
      frame      <= 8'd0;
      vsync_prev <= 1'b1;
    end else begin
      if (vsync_prev && !vsync) frame <= frame + 8'd1;
      vsync_prev <= vsync;
    end
  end

  // Rows 0..59: 8-bit frame counter, 8 blocks of 80 px (8*80 = 640, so the
  // whole row width is covered, no black margin needed).
  wire       in_counter_rows = vpos < 10'd60;
  wire [2:0] counter_blk     = hpos / 10'd80;          // 0..7
  wire       counter_bit     = frame[7-counter_blk];

  // Rows 60..479: 9-bit line-number strip, 9 blocks of 60 px (9*60 = 540
  // < 640, so x >= 540 is black), in every 40-line band's first 20 rows.
  wire [9:0] ry            = vpos - 10'd60;            // valid only when in_line_rows
  wire [9:0] band_k        = ry / 10'd40;
  wire [9:0] band_offset   = ry - band_k * 10'd40;     // ry % 40
  wire [9:0] line_label    = 10'd60 + band_k * 10'd40; // y of the band's first row
  wire       in_line_rows  = (vpos >= 10'd60) && (vpos < 10'd480);
  wire       in_label_row  = in_line_rows && (band_offset < 10'd20);
  wire [3:0] label_blk     = hpos / 10'd60;            // 0..10; only 0..8 is a real block
  wire       in_label_blk  = in_label_row && (label_blk < 4'd9);
  wire       label_bit     = line_label[8-label_blk];

  wire [5:0] pixel_index = in_counter_rows ? (counter_bit ? 6'h3F : 6'h03)
                         : in_label_blk    ? (label_bit ? 6'h3F : 6'h03)
                                           : 6'h00;
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
