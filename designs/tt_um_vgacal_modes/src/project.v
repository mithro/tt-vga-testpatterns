/*
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 *
 * tt_um_vgacal_modes - the colour-bar pattern in three different VGA
 * timings, selected at run time, with independently invertible sync
 * polarities: a calibration design for a capture pipeline's mode detection
 * and polarity reporting.
 *
 *   ui_in[1:0]  0 or 3 = 640x480@60, 1 = 800x600@60, 2 = 720x400@70
 *   ui_in[2]    invert hsync polarity (relative to the mode's default)
 *   ui_in[3]    invert vsync polarity (relative to the mode's default)
 *
 * ui_in[3:0] is sampled only at a frame boundary (see
 * hvsync_generator_mux.v), so a mode change takes effect at the start of
 * the next frame and never corrupts a frame already being drawn.
 *
 * Picture: 64 vertical colour bars scaled to the mode's active width --
 * bar width = active_width / 64, i.e. 10 px at 640 wide, 12 px at 800 and
 * 11 px at 720 -- with the colour index clipped at 63, so the last (63rd)
 * bar absorbs the width that does not divide evenly (44 px at 800 wide,
 * 27 px at 720). Every active row is identical.
 */

`default_nettype none

module tt_um_vgacal_modes (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  wire       hsync, vsync, display_on, line_end;
  wire [1:0] mode;
  wire [10:0] hpos, vpos;

  hvsync_generator_mux vga_sync (
      .clk       (clk),
      .reset     (~rst_n),
      .cfg_in    (ui_in[3:0]),
      .hsync     (hsync),
      .vsync     (vsync),
      .hpos      (hpos),
      .vpos      (vpos),
      .display_on(display_on),
      .line_end  (line_end),
      .mode      (mode)
  );

  // Bar width for the mode in effect: 640/64 = 10, 800/64 = 12,
  // 720/64 = 11. Held as (width - 1) because that is what the comparator
  // below wants.
  wire [3:0] bar_w_m1 = (mode == 2'd1) ? 4'd11 : (mode == 2'd2) ? 4'd10 : 4'd9;

  // Colour index = min(hpos / bar_width, 63), computed without a divider:
  // bar_pos counts 0..bar_width-1 within the current bar and bar_idx is the
  // bar number, both reset at the start of every line and stepped in
  // lockstep with hpos, so that when hpos holds x, bar_idx holds
  // min(x / bar_width, 63). bar_idx saturates at 63 (`&bar_idx`) rather
  // than wrapping, which is what clips the last bar; past the active width
  // display_on blanks the output anyway.
  reg [3:0] bar_pos;
  reg [5:0] bar_idx;
  always @(posedge clk) begin
    if (!rst_n || line_end) begin
      bar_pos <= 4'd0;
      bar_idx <= 6'd0;
    end else if (bar_pos >= bar_w_m1) begin
      bar_pos <= 4'd0;
      bar_idx <= (&bar_idx) ? bar_idx : bar_idx + 6'd1;
    end else begin
      bar_pos <= bar_pos + 4'd1;
    end
  end

  // Combinational from bar_idx (which tracks hpos exactly), blanked by
  // display_on: hvsync_generator_mux's sync pulses are phase-correct, so
  // this lines up with hsync/vsync with no per-design correction.
  wire [5:0] color = display_on ? bar_idx : 6'h00;

  // Tiny VGA PMOD: {HSync, B0, G0, R0, VSync, B1, G1, R1}.
  // color[5:0] is rr gg bb, so color[5]=R1, color[4]=R0, color[3]=G1,
  // color[2]=G0, color[1]=B1, color[0]=B0.
  assign uo_out  = {hsync, color[0], color[2], color[4], vsync, color[1], color[3], color[5]};
  assign uio_out = 8'h00;
  assign uio_oe  = 8'h00;

  // avoid linter warnings about unused pins:
  wire _unused = &{ena, ui_in[7:4], uio_in, 1'b0};

endmodule
