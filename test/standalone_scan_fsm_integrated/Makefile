SIM ?= icarus
TOPLEVEL_LANG ?= verilog

VERILOG_SOURCES += $(PWD)/dac_serializer.v
VERILOG_SOURCES += $(PWD)/dac_channel_regs.v
VERILOG_SOURCES += $(PWD)/scan_fsm.v
TOPLEVEL = scan_fsm
MODULE = test_scan_fsm_integrated

include $(shell cocotb-config --makefiles)/Makefile.sim
