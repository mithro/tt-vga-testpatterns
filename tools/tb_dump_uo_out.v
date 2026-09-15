// SPDX-License-Identifier: Apache-2.0
// Generic testbench: instantiate a Tiny Tapeout project (top module name
// given with -DTOP=...) and write uo_out once per clock, one byte per
// clock, to the file named by +out=<path>, for +clocks=<n> clocks after
// reset. The result is a raw sample dump that vgacap's Python writer wraps
// into a stream (sample_bits=8, samples_per_word=4, Tiny VGA map).
`timescale 1ns / 1ps
`default_nettype none

module tb_dump_uo_out;
  reg        clk = 0;
  reg        rst_n = 0;
  reg  [7:0] ui_in = 8'h00;
  reg  [7:0] uio_in = 8'h00;
  wire [7:0] uo_out;
  wire [7:0] uio_out;
  wire [7:0] uio_oe;

  `TOP dut (
      .ui_in  (ui_in),
      .uo_out (uo_out),
      .uio_in (uio_in),
      .uio_out(uio_out),
      .uio_oe (uio_oe),
      .ena    (1'b1),
      .clk    (clk),
      .rst_n  (rst_n)
  );

  integer fd;
  integer n_clocks;
  integer i;
  reg [1023:0] out_path;
  reg [7:0] ui_val;

  always #20 clk = ~clk;  // 25 MHz nominal; the period does not matter for the dump

  initial begin
    if (!$value$plusargs("out=%s", out_path)) out_path = "uo_out.bin";
    if (!$value$plusargs("clocks=%d", n_clocks)) n_clocks = 2 * 800 * 525;
    if ($value$plusargs("ui_in=%d", ui_val)) ui_in = ui_val;
    fd = $fopen(out_path, "wb");
    // hold reset for ten clocks
    repeat (10) @(posedge clk);
    #1 rst_n = 1;
    for (i = 0; i < n_clocks; i = i + 1) begin
      @(negedge clk);  // sample mid-period, after outputs settled (same phase as the PIO sampler)
      $fwrite(fd, "%c", uo_out);
    end
    $fclose(fd);
    $finish;
  end
endmodule
