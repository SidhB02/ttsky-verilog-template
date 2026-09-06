# Flux-Bias Sequencer - full top-level test (real chip pins)
# SPDX-License-Identifier: Apache-2.0
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
        # uio_in[2]=cfg_load_en=1, uio_in[1:0]=chunk
        dut.uio_in.value = (1 << 2) | chunk
        await RisingEdge(dut.clk)
    dut.uio_in.value = 0
    await ClockCycles(dut.clk, 2)


SETTLE_STATE = 3

async def fake_comparator(dut, fail_once_on_channel=None):
    """Watches the FSM's internal state (via hierarchical access) for
    entry into SETTLE - this fires exactly once per channel, right after
    that channel's serial transfer finishes, with no shared-bus timing
    ambiguity (unlike watching cs_n directly)."""
    failed_channels = set()
    prev_state = -1

    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        fsm_state = int(dut.user_project.fsm_inst.state.value)
        ch = int(dut.user_project.fsm_inst.ch_count.value)
        sent_code = int(dut.user_project.fsm_inst.reg_code_out.value)

        transfer_just_finished = (fsm_state == SETTLE_STATE and prev_state != SETTLE_STATE)
        prev_state = fsm_state

        await NextTimeStep()

        if transfer_just_finished:
            current_ui = int(dut.ui_in.value)
            start_bit = current_ui & 0b100  # preserve ui_in[2]

            if fail_once_on_channel is not None and ch == fail_once_on_channel \
                    and ch not in failed_channels:
                new_status = 0b01  # too-low, force a retry
                failed_channels.add(ch)
                result = "TOO-LOW, retrying"
            else:
                new_status = 0b00  # lock
                result = "LOCKED"

            dut._log.info(f"  >> Channel {ch}: sent DAC code 0x{sent_code:02X}  ->  {result}")
            dut.ui_in.value = start_bit | new_status


@cocotb.test()
async def test_config_load_and_full_scan(dut):
    dut._log.info("Start full top-level test")

    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    # Load config: 4 initial codes, lock_window (unused downstream), step_size
    payload = build_payload(0x10, 0x20, 0x30, 0x40, 0x0F, 0x05)
    await load_config(dut, payload)
    dut._log.info("Config loaded")

    # Wait for the FSM to leave PRELOAD and settle in IDLE before triggering
    for _ in range(30):
        await RisingEdge(dut.clk)
        await ReadOnly()
        fsm_state = int(dut.user_project.fsm_inst.state.value)
        await NextTimeStep()
        if fsm_state == 0:  # IDLE
            break

    # Start the fake comparator watching the live SPI bus
    cocotb.start_soon(fake_comparator(dut, fail_once_on_channel=None))

    # Pulse start_scan (ui_in[2]), keep comparator bits at 0 initially
    dut.ui_in.value = 0b100
    await RisingEdge(dut.clk)
    dut.ui_in.value = 0b000

    # Watch uo_out[5] (scan_complete) for up to 200 cycles
    scan_complete_seen = False
    for i in range(200):
        await RisingEdge(dut.clk)
        await ReadOnly()
        uo = int(dut.uo_out.value)
        scan_complete = (uo >> 5) & 0x1
        if scan_complete:
            scan_complete_seen = True
            lock_flag = (uo >> 6) & 0x1
            dut._log.info(f"Scan complete! Final channel locked: {bool(lock_flag)}")
            break
        await NextTimeStep()

    assert scan_complete_seen, "scan_complete never pulsed within 200 cycles"


@cocotb.test()
async def test_scan_with_retry_on_channel(dut):
    dut._log.info("Start retry test")

    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    payload = build_payload(0x11, 0x22, 0x33, 0x44, 0x0F, 0x08)
    await load_config(dut, payload)

    # Wait for the FSM to leave PRELOAD and settle in IDLE before triggering
    for _ in range(30):
        await RisingEdge(dut.clk)
        await ReadOnly()
        fsm_state = int(dut.user_project.fsm_inst.state.value)
        await NextTimeStep()
        if fsm_state == 0:  # IDLE
            break

    # channel 1 fails once before locking
    cocotb.start_soon(fake_comparator(dut, fail_once_on_channel=1))

    dut.ui_in.value = 0b100
    await RisingEdge(dut.clk)
    dut.ui_in.value = 0b000

    scan_complete_seen = False
    for _ in range(300):
        await RisingEdge(dut.clk)
        await ReadOnly()
        uo = int(dut.uo_out.value)
        scan_complete = (uo >> 5) & 0x1
        if scan_complete:
            scan_complete_seen = True
            break
        await NextTimeStep()

    assert scan_complete_seen, "scan_complete never pulsed (retry path)"


@cocotb.test()
async def test_never_locks_does_not_stall(dut):
    """A channel that always fails (never locks) must eventually give up
    (after 4 retries) and move on, not stall the whole scan forever."""
    dut._log.info("Start never-locks test")

    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    payload = build_payload(0x50, 0x60, 0x70, 0x80, 0x0F, 0x05)
    await load_config(dut, payload)

    # Wait for FSM to settle in IDLE before triggering
    for _ in range(30):
        await RisingEdge(dut.clk)
        await ReadOnly()
        fsm_state = int(dut.user_project.fsm_inst.state.value)
        await NextTimeStep()
        if fsm_state == 0:
            break

    # Background task: channel 0 ALWAYS fails (too-high), every other channel locks
    async def always_fail_on_channel_0():
        prev_state = -1
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            fsm_state = int(dut.user_project.fsm_inst.state.value)
            ch = int(dut.user_project.fsm_inst.ch_count.value)
            sent_code = int(dut.user_project.fsm_inst.reg_code_out.value)
            transfer_just_finished = (fsm_state == SETTLE_STATE and prev_state != SETTLE_STATE)
            prev_state = fsm_state
            await NextTimeStep()

            if transfer_just_finished:
                current_ui = int(dut.ui_in.value)
                start_bit = current_ui & 0b100
                if ch == 0:
                    new_status = 0b10  # too-high, never locks
                    result = "TOO-HIGH (never locks)"
                else:
                    new_status = 0b00
                    result = "LOCKED"
                dut._log.info(f"  >> Channel {ch}: sent DAC code 0x{sent_code:02X}  ->  {result}")
                dut.ui_in.value = start_bit | new_status

    cocotb.start_soon(always_fail_on_channel_0())

    dut.ui_in.value = 0b100
    await RisingEdge(dut.clk)
    dut.ui_in.value = 0b000

    scan_complete_seen = False
    for _ in range(400):
        await RisingEdge(dut.clk)
        await ReadOnly()
        uo = int(dut.uo_out.value)
        scan_complete = (uo >> 5) & 0x1
        if scan_complete:
            scan_complete_seen = True
            lock_flag = (uo >> 6) & 0x1
            dut._log.info(f"Scan complete despite channel 0 never locking. "
                          f"Final (channel 3) locked: {bool(lock_flag)}")
            break
        await NextTimeStep()

    assert scan_complete_seen, \
        "FSM stalled: scan never completed when a channel never locks"


@cocotb.test()
async def test_reset_mid_scan(dut):
    """Asserting reset partway through a scan must immediately force the
    chip back to a clean idle state, not leave it stuck mid-sequence."""
    dut._log.info("Start reset-mid-scan test")

    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)

    payload = build_payload(0x10, 0x20, 0x30, 0x40, 0x0F, 0x05)
    await load_config(dut, payload)

    for _ in range(30):
        await RisingEdge(dut.clk)
        await ReadOnly()
        fsm_state = int(dut.user_project.fsm_inst.state.value)
        await NextTimeStep()
        if fsm_state == 0:
            break

    dut.ui_in.value = 0b100
    await RisingEdge(dut.clk)
    dut.ui_in.value = 0b000

    # Let it run partway into the scan (a handful of cycles, likely mid LOAD_CODE/SETTLE)
    await ClockCycles(dut.clk, 10)

    # Assert reset mid-scan
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)

    fsm_state_after_reset = int(dut.user_project.fsm_inst.state.value)
    fsm_ch_after_reset = int(dut.user_project.fsm_inst.ch_count.value)

    # PRELOAD (state 9) is the correct post-reset state per scan_fsm.v design
    assert fsm_state_after_reset == 9, \
        f"Expected PRELOAD (9) immediately after reset, got state={fsm_state_after_reset}"
    assert fsm_ch_after_reset == 0, \
        f"Expected channel counter cleared to 0 after reset, got {fsm_ch_after_reset}"

    dut._log.info("Reset mid-scan correctly forced FSM back to PRELOAD, channel counter cleared")
    dut.rst_n.value = 1
