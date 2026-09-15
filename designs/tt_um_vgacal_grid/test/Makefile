# SPDX-License-Identifier: Apache-2.0
# cocotb test Makefile for tt_um_vgacal_grid.
#
# Run with:  uv run make -C designs/tt_um_vgacal_grid/test
# (uv run so cocotb runs under the project's uv-managed Python.)

SIM ?= icarus
TOPLEVEL_LANG = verilog

SRC_DIR = $(CURDIR)/../src
VERILOG_SOURCES = $(SRC_DIR)/project.v $(SRC_DIR)/hvsync_generator.v

COCOTB_TOPLEVEL = tt_um_vgacal_grid
COCOTB_TEST_MODULES = test_grid

include $(shell cocotb-config --makefiles)/Makefile.sim
