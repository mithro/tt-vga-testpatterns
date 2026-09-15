/*
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 *
 * tt_um_vgacal_prbs - a per-pixel pseudo-random picture from a 16-bit
 * Fibonacci LFSR, with the same 8-bit frame counter as tt_um_vgacal_counter
 * drawn as a strip across the top 8 rows so a capture pipeline can tell
 * which frame (and hence which LFSR seed) it is looking at. For a Tiny VGA
 * PMOD, 640x480@60.
 *
 * Picture (see docs/info.md for the full description):
 *   - Rows 0..7 (y < 8): the 8-bit frame counter, 8 blocks of 80x8 px,
 *     white (0x3F) if bit (7-i) of the frame counter is set, else blue
 *     (0x03) -- same encoding as tt_um_vgacal_counter's top block row.
 *   - Rows 8..479: the low 6 bits of a 16-bit Fibonacci LFSR
 *     (x^16+x^14+x^13+x^11+1: bit = s[0]^s[2]^s[3]^s[5], s <= {bit, s[15:1]}),
 *     seeded with 16'hACE1 ^ frame at the first active pixel of row 8 and
 *     advanced once per active pixel after that, in raster order,
 *     continuously across rows (not reset per row).
 */

`default_nettype none

module tt_um_vgacal_prbs (
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

  // 8-bit frame counter: same construction as tt_um_vgacal_counter (see
  // its project.v for the reasoning) -- increments on the vsync leading
  // edge, so the active area of frame N always shows frame == N.
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

  // hpos/vpos *after* this edge -- duplicated from hvsync_generator (see
  // its header comment and docs/timing.md) since the generator does not
  // expose hpos_n/vpos_n as ports and the LFSR needs to know, one clock
  // ahead, whether the *upcoming* pixel is the first of row 8 of a new
  // frame (reseed) or elsewhere in the active LFSR area (advance) -- the
  // same one-clock-ahead phase hpos/vpos/colour themselves use.
  localparam H_TOTAL = 800;
  localparam V_TOTAL = 525;
  wire       h_last = (hpos == H_TOTAL - 1);
  wire [9:0] hpos_n = h_last ? 10'd0 : hpos + 10'd1;
  wire [9:0] vpos_n = h_last ? ((vpos == V_TOTAL - 1) ? 10'd0 : vpos + 10'd1) : vpos;

  wire lfsr_reseed_n = (hpos_n == 10'd0) && (vpos_n == 10'd8);
  wire lfsr_active_n = (hpos_n < 10'd640) && (vpos_n >= 10'd8) && (vpos_n < 10'd480);

  reg  [15:0] lfsr;
  wire        lfsr_bit  = lfsr[0] ^ lfsr[2] ^ lfsr[3] ^ lfsr[5];
  wire [15:0] lfsr_next = {lfsr_bit, lfsr[15:1]};

  always @(posedge clk) begin
    if (!rst_n) begin
      lfsr <= 16'hACE1;  // == 16'hACE1 ^ frame, since frame == 0 at reset
    end else if (lfsr_reseed_n) begin
      lfsr <= 16'hACE1 ^ {8'h00, frame};
    end else if (lfsr_active_n) begin
      lfsr <= lfsr_next;
    end
  end

  // Rows 0..7: 8-bit frame counter, 8 blocks of 80 px (8*80 = 640, so the
  // whole row width is covered).
  wire       in_counter_rows = vpos < 10'd8;
  wire [2:0] counter_blk     = hpos / 10'd80;  // 0..7
  wire       counter_bit     = frame[7-counter_blk];

  // Rows 8..479: low 6 bits of the LFSR.
  wire       in_lfsr_rows = (vpos >= 10'd8) && (vpos < 10'd480);

  wire [5:0] pixel_index = in_counter_rows ? (counter_bit ? 6'h3F : 6'h03)
                         : in_lfsr_rows    ? lfsr[5:0]
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
