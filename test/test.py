# Flux-Bias Sequencer - full top-level test (real chip pins only)
# SPDX-License-Identifier: Apache-2.0
#
# This test uses ONLY the chip's real pins (ui_in, uo_out, uio_in/out) -
# no internal hierarchy access (e.g. dut.user_project.fsm_inst.*).
# This is required so the exact same test works for both RTL simulation
# and gate-level (post-synthesis netlist) simulation, where internal
# signal names no longer exist after synthesis flattens the design into
# standard cells.
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, ReadOnly, NextTimeStep


def build_payload(code0, code1, code2, code3, lock_window, step_size):
    return (code0 << 40) | (code1 << 32) | (code2 << 24) | (code3 << 16) | (lock_window << 8) | step_size


async def reset_dut(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def load_config(dut, payload_48bit):
    """Shifts a 48-bit config payload into uio_in[1:0], 2 bits/cycle,
    with uio_in[2] (cfg_load_en) held high."""
    for i in range(24):
        chunk = (payload_48bit >> (46 - i * 2)) & 0b11
        dut.uio_in.value = (1 << 2) | chunk
        await RisingEdge(dut.clk)
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 2)


async def wait_until_idle(dut, settle_cycles=30):
    """Waits a fixed, generous number of cycles after config load to let
    the chip finish its internal PRELOAD sequence (writing the 4 initial
    codes into the register file) before a scan is triggered. This is a
    fixed margin rather than a pin-detected condition, since there is no
    dedicated 'preload done' pin exposed at the top level."""
    await ClockCycles(dut.clk, settle_cycles)


async def fake_comparator(dut, fail_once_on_channel=None):
    """Watches uo_out[2] (CS, active-low) for the falling-to-rising
    transition that marks the end of a channel's serial transfer, then
    drives ui_in[1:0] (comparator feedback) accordingly. Pin-only - safe
    for both RTL and gate-level simulation."""
    failed_channels = set()
    prev_cs_n = 1

    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        uo = int(dut.uo_out.value)
        cs_n = (uo >> 2) & 0x1
        ch = (uo >> 3) & 0b11

        transfer_just_finished = (prev_cs_n == 0 and cs_n == 1)
        prev_cs_n = cs_n

        await NextTimeStep()

        if transfer_just_finished:
            current_ui = int(dut.ui_in.value)
            start_bit = current_ui & 0b100  # preserve ui_in[2]

            if fail_once_on_channel is not None and ch == fail_once_on_channel \
                    and ch not in failed_channels:
                new_status = 0b01  # too-low, force a retry
                failed_channels.add(ch)
            else:
                new_status = 0b00  # lock

            dut.ui_in.value = start_bit | new_status


async def fake_comparator_always_fail(dut, fail_channel):
    """Like fake_comparator, but one specific channel ALWAYS fails
    (too-high), to exercise the give-up-after-retries path."""
    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        uo = int(dut.uo_out.value)
        cs_n = (uo >> 2) & 0x1
        ch = (uo >> 3) & 0b11

        transfer_just_finished = (getattr(fake_comparator_always_fail, "_prev_cs_n", 1) == 0 and cs_n == 1)
        fake_comparator_always_fail._prev_cs_n = cs_n

        await NextTimeStep()

        if transfer_just_finished:
            current_ui = int(dut.ui_in.value)
            start_bit = current_ui & 0b100

            if ch == fail_channel:
                new_status = 0b10  # too-high, never locks
            else:
                new_status = 0b00

            dut.ui_in.value = start_bit | new_status


async def run_scan_and_wait_for_complete(dut, timeout_cycles=400):
    """Pulses start_scan (ui_in[2]) and waits for scan_complete (uo_out[5])
    to pulse. Returns the final lock_flag (uo_out[6]) value."""
    current_ui = int(dut.ui_in.value)
    dut.ui_in.value = current_ui | 0b100
    await RisingEdge(dut.clk)
    dut.ui_in.value = int(dut.ui_in.value) & ~0b100

    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        uo = int(dut.uo_out.value)
        scan_complete = (uo >> 5) & 0x1
        lock_flag = (uo >> 6) & 0x1
        if scan_complete:
            await NextTimeStep()
            return lock_flag
        await NextTimeStep()

    assert False, f"scan_complete never pulsed within {timeout_cycles} cycles"


@cocotb.test()
async def test_config_load_and_full_scan(dut):
    dut._log.info("Start: config load + full scan, all channels lock immediately")

    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    payload = build_payload(0x10, 0x20, 0x30, 0x40, 0x0F, 0x05)
    await load_config(dut, payload)
    await wait_until_idle(dut)

    cocotb.start_soon(fake_comparator(dut, fail_once_on_channel=None))

    final_lock = await run_scan_and_wait_for_complete(dut)
    dut._log.info(f"Scan complete. Final channel locked: {bool(final_lock)}")
    assert final_lock == 1, "expected final channel to be locked"


@cocotb.test()
async def test_scan_with_retry_on_channel(dut):
    dut._log.info("Start: scan with one forced retry")

    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    payload = build_payload(0x11, 0x22, 0x33, 0x44, 0x0F, 0x08)
    await load_config(dut, payload)
    await wait_until_idle(dut)

    # channel 1 fails once before locking
    cocotb.start_soon(fake_comparator(dut, fail_once_on_channel=1))

    final_lock = await run_scan_and_wait_for_complete(dut)
    dut._log.info(f"Scan complete (retry path). Final channel locked: {bool(final_lock)}")
    assert final_lock == 1, "expected final channel to be locked after retry"


@cocotb.test()
async def test_never_locks_does_not_stall(dut):
    dut._log.info("Start: never-locks-does-not-stall")

    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    payload = build_payload(0x50, 0x60, 0x70, 0x80, 0x0F, 0x05)
    await load_config(dut, payload)
    await wait_until_idle(dut)

    # reset the static state on the helper function between test runs
    if hasattr(fake_comparator_always_fail, "_prev_cs_n"):
        del fake_comparator_always_fail._prev_cs_n

    # channel 0 always fails (too-high), every other channel locks
    cocotb.start_soon(fake_comparator_always_fail(dut, fail_channel=0))

    final_lock = await run_scan_and_wait_for_complete(dut, timeout_cycles=400)
    dut._log.info("Scan completed despite channel 0 never locking "
                  f"(sequencer did not stall). Final channel locked: {bool(final_lock)}")
    # scan_complete pulsing at all (without timing out) IS the pass condition here -
    # the whole point is that a channel that never locks must not stall the scan.


@cocotb.test()
async def test_reset_mid_scan(dut):
    dut._log.info("Start: reset mid-scan")

    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    payload = build_payload(0x10, 0x20, 0x30, 0x40, 0x0F, 0x05)
    await load_config(dut, payload)
    await wait_until_idle(dut)

    current_ui = int(dut.ui_in.value)
    dut.ui_in.value = current_ui | 0b100
    await RisingEdge(dut.clk)
    dut.ui_in.value = int(dut.ui_in.value) & ~0b100

    # let it run partway into the scan
    await ClockCycles(dut.clk, 10)

    # assert reset mid-scan
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)

    # after reset, CS should be deselected (high) and scan_complete/lock_flag low -
    # a pin-only proxy for "back to a clean idle state"
    await ReadOnly()
    uo = int(dut.uo_out.value)
    cs_n = (uo >> 2) & 0x1
    scan_complete = (uo >> 5) & 0x1
    await NextTimeStep()

    assert cs_n == 1, f"expected CS deselected (high) after reset, got cs_n={cs_n}"
    assert scan_complete == 0, "expected scan_complete low immediately after reset"

    dut._log.info("Reset mid-scan correctly forced chip back to a clean idle state")
    dut.rst_n.value = 1
