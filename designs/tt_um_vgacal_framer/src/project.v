/*
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 *
 * tt_um_vgacal_framer - vgacap's RTL capture framer, on a known picture.
 *
 * The tt_um_vgacal_bars picture (640x480@60, 64 bars, Tiny VGA byte layout)
 * goes into vgacap_raw_framer (mithro/vgacap rtl/), sampled on every other
 * clock so the framer's one-byte-a-clock output keeps up with its header
 * overhead. Out come vgacap chunk bytes: uo_out carries the byte, uio[0]
 * is high on the clocks that carry one. A capture of uio+uo_out, kept where
 * uio[0] is set, is a vgacap chunk stream (after a host-written VGCH header)
 * whose RAW samples must be the bars picture's samples, every other clock.
 *
 * uio[0] is an output; uio[7:1] stay inputs (the Pi Pmod HAT ties
 * ui_in[3:1] to uio[3:1]).
 */

`default_nettype none

module tt_um_vgacal_framer (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
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

  // hpos / 10 as counters, not a divider: tt_um_vgacal_bars' combinational
  // divide is too slow for one 25 MHz cycle on the iCE40UP5K once it feeds a
  // register (21 MHz) instead of the pins. bar10 counts 0..9, bar is
  // hpos / 10; both restart where hpos does (and are 0 through reset, as
  // hpos is), so the picture is the bars design's exactly.
  reg [3:0] bar10;
  reg [6:0] bar;
  always @(posedge clk)
    if (!rst_n || hpos == 10'd799) begin
      bar10 <= 4'd0;
      bar   <= 7'd0;
    end else if (bar10 == 4'd9) begin
      bar10 <= 4'd0;
      bar   <= bar + 7'd1;
    end else
      bar10 <= bar10 + 4'd1;
  wire [5:0] bar_index = bar[5:0];
  wire [5:0] color = display_on ? bar_index : 6'h00;
  wire [7:0] vga = {hsync, color[0], color[2], color[4], vsync, color[1], color[3], color[5]};

  // Every other clock. The picture byte is registered first: the bars'
  // hpos / 10 feeding the framer's input register directly missed 25 MHz
  // on the iCE40UP5K (21 MHz).
  reg half;
  reg [7:0] vga_q;
  always @(posedge clk)
    if (!rst_n) begin
      half <= 1'b0;
      vga_q <= 8'h00;
    end else begin
      half <= ~half;
      vga_q <= vga;
    end

  wire [7:0]  out_data;
  wire        out_valid;
  wire [31:0] dropped;

  vgacap_raw_framer framer (
      .sys_clk     (clk),
      .sys_rst     (~rst_n),
      .sample      (vga_q),
      .sample_valid(half),
      .out_data    (out_data),
      .out_valid   (out_valid),
      .out_ready   (1'b1),
      .dropped     (dropped)
  );

  // Registered: the framer's output byte is a mux off its FSM state, and
  // straight to the pins that path missed 25 MHz on the iCE40UP5K.
  reg [7:0] uo_q;
  reg       valid_q;
  always @(posedge clk) begin
    if (!rst_n) begin
      uo_q <= 8'h00;
      valid_q <= 1'b0;
    end else begin
      uo_q <= out_valid ? out_data : 8'h00;
      valid_q <= out_valid;
    end
  end

  assign uo_out  = uo_q;
  assign uio_out = {7'b0, valid_q};
  assign uio_oe  = 8'h01;

  wire _unused = &{ena, ui_in, uio_in, dropped, 1'b0};

endmodule
