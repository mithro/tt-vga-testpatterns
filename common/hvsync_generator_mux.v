/*
 * Copyright (c) 2026 mithro
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

// A run-time mode-switchable VGA timing generator.
//
// This is common/hvsync_generator.v with its *parameters* replaced by a
// small constant table selected at run time by cfg_in[1:0], plus run-time
// sync-polarity inversion (cfg_in[2] / cfg_in[3]). Everything else -- in
// particular the VESA-correct sync phase, computing the sync pulses from
// the *next* hpos/vpos rather than the current (pre-increment) ones -- is
// identical to that module, and the same contract holds: hpos/vpos are the
// position of the pixel whose colour the design should output *this* cycle,
// so plain combinational colour blanked by display_on lines up exactly with
// hsync/vsync. See common/hvsync_generator.v's header and docs/timing.md.
//
// Modes (cfg_in[1:0]):
//   0, 3: 640x480@60   800 x 525   640,16,96,48  / 480,10,2,33   hsync -, vsync -
//   1:    800x600@60  1056 x 628   800,40,128,88 / 600,1,4,23    hsync +, vsync +
//   2:    720x400@70   900 x 449   720,18,108,54 / 400,12,2,35   hsync -, vsync +
// cfg_in[2] inverts hsync's polarity and cfg_in[3] inverts vsync's,
// relative to the selected mode's default above.
//
// hpos/vpos are 11 bits wide (not 10 as in hvsync_generator.v): 800x600@60
// is 1056 clocks per line, which does not fit in 10 bits.
//
// **cfg_in is only sampled at a frame boundary** (the clock edge that wraps
// both counters back to 0, i.e. the last clock of the last line of a
// frame), and on reset. A mode change therefore takes effect at the start
// of the next frame and can never corrupt a frame that is already being
// drawn, nor leave the counters stranded past a shorter mode's totals: they
// are both 0 at the instant the new constants take effect. The counter wrap
// tests are ">=" rather than "==" so that even an out-of-range value (which
// the above makes unreachable) would recover on the next line/frame instead
// of free-running.
//
// One consequence of sampling cfg_in on the reset edge itself: the idle
// levels hsync/vsync are held at during reset are derived from the
// *previous* cfg for the first reset clock (the cfg register and the sync
// registers update on the same edge), and are correct from the second reset
// clock onwards. Reset is asserted for far more than two clocks in the Tiny
// Tapeout harness (and in this repo's testbenches), so this is not
// observable; it is noted here only because the module is otherwise
// exactly synchronous with cfg_in.
module hvsync_generator_mux (
    input  wire        clk,    // clock, assumed to be the pixel clock for the mode
    input  wire        reset,  // reset (active HIGH)
    input  wire  [3:0] cfg_in, // {vsync_invert, hsync_invert, mode[1:0]}; sampled at a frame boundary
    output reg         vsync,  // VSync
    output reg         hsync,  // HSync
    output reg  [10:0] hpos,   // horizontal position in frame
    output reg  [10:0] vpos,   // vertical position in frame
    output wire        display_on,  // in the "addressable" part of the frame?
    output wire        line_end,    // this clock edge wraps hpos back to 0
    output wire  [1:0] mode         // the mode currently in effect (latched cfg_in[1:0])
);

  // The configuration actually in effect, sampled from cfg_in at a frame
  // boundary (see the header comment).
  reg [3:0] cfg;
  assign mode = cfg[1:0];

  // Per-mode constants. Only the four "edge" positions per axis are needed:
  // the active width/height, where the sync pulse starts and ends, and the
  // total minus one (the counter wrap value).
  reg [10:0] h_active, h_sync_start, h_sync_end, h_total_m1;
  reg [10:0] v_active, v_sync_start, v_sync_end, v_total_m1;
  reg        h_pol_mode, v_pol_mode;

  always @(*) begin
    case (cfg[1:0])
      2'd1: begin  // 800x600@60: 800,40,128,88 / 600,1,4,23, both syncs high
        h_active = 11'd800; h_sync_start = 11'd840; h_sync_end = 11'd968; h_total_m1 = 11'd1055;
        v_active = 11'd600; v_sync_start = 11'd601; v_sync_end = 11'd605; v_total_m1 = 11'd627;
        h_pol_mode = 1'b1; v_pol_mode = 1'b1;
      end
      2'd2: begin  // 720x400@70: 720,18,108,54 / 400,12,2,35, hsync low, vsync high
        h_active = 11'd720; h_sync_start = 11'd738; h_sync_end = 11'd846; h_total_m1 = 11'd899;
        v_active = 11'd400; v_sync_start = 11'd412; v_sync_end = 11'd414; v_total_m1 = 11'd448;
        h_pol_mode = 1'b0; v_pol_mode = 1'b1;
      end
      default: begin  // 0 and 3: 640x480@60: 640,16,96,48 / 480,10,2,33, both syncs low
        h_active = 11'd640; h_sync_start = 11'd656; h_sync_end = 11'd752; h_total_m1 = 11'd799;
        v_active = 11'd480; v_sync_start = 11'd490; v_sync_end = 11'd492; v_total_m1 = 11'd524;
        h_pol_mode = 1'b0; v_pol_mode = 1'b0;
      end
    endcase
  end

  // Effective polarities: the mode's default, inverted by cfg[3:2].
  // 0 = the pulse is low (active low), 1 = the pulse is high.
  wire h_pol = h_pol_mode ^ cfg[2];
  wire v_pol = v_pol_mode ^ cfg[3];

  // hpos/vpos *after* this edge -- the free-running position counters.
  wire        h_last = (hpos >= h_total_m1);
  wire        v_last = (vpos >= v_total_m1);
  wire [10:0] hpos_n = h_last ? 11'd0 : hpos + 11'd1;
  wire [10:0] vpos_n = h_last ? (v_last ? 11'd0 : vpos + 11'd1) : vpos;

  assign line_end = h_last;

  // The line number as the *sync* counts it: a VGA line begins at the hsync
  // leading edge, which is h_sync_start clocks into hpos's own line, so from
  // there on the sync is already on the next line. (Same reasoning as in
  // common/hvsync_generator.v.)
  wire [10:0] vline_n = (hpos_n >= h_sync_start)
                      ? ((vpos_n >= v_total_m1) ? 11'd0 : vpos_n + 11'd1) : vpos_n;

  wire h_pulse = (hpos_n >= h_sync_start) && (hpos_n < h_sync_end);
  wire v_pulse = (vline_n >= v_sync_start) && (vline_n < v_sync_end);

  always @(posedge clk) begin
    if (reset) begin
      cfg   <= cfg_in;
      hsync <= h_pol ? 1'b0 : 1'b1;
      vsync <= v_pol ? 1'b0 : 1'b1;
      hpos  <= 11'd0;
      vpos  <= 11'd0;
    end else begin
      // A frame boundary: both counters wrap back to 0 on this edge, so the
      // new mode's constants take effect with the counters already at 0.
      if (h_last && v_last) cfg <= cfg_in;
      hsync <= h_pol ? h_pulse : ~h_pulse;
      vsync <= v_pol ? v_pulse : ~v_pulse;
      hpos  <= hpos_n;
      vpos  <= vpos_n;
    end
  end

  assign display_on = (hpos < h_active) && (vpos < v_active);

endmodule
