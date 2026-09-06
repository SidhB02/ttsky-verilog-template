import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, ReadOnly, NextTimeStep

PRELOAD, IDLE, SELECT_CH, LOAD_CODE, SETTLE, SAMPLE, LOCK_CHECK, ADJUST_CODE, NEXT_CHANNEL, DONE = \
    9, 0, 1, 2, 3, 4, 5, 6, 7, 8

STATE_NAMES = {v: k for k, v in
               dict(PRELOAD=PRELOAD, IDLE=IDLE, SELECT_CH=SELECT_CH, LOAD_CODE=LOAD_CODE,
                    SETTLE=SETTLE, SAMPLE=SAMPLE, LOCK_CHECK=LOCK_CHECK,
                    ADJUST_CODE=ADJUST_CODE, NEXT_CHANNEL=NEXT_CHANNEL, DONE=DONE).items()}


async def reset_dut(dut):
    dut.start_scan.value = 0
    dut.comparator_status.value = 0
    dut.preload_en.value = 0
    dut.init_code0.value = 0x10
    dut.init_code1.value = 0x20
    dut.init_code2.value = 0x30
    dut.init_code3.value = 0x40
    dut.step_size.value = 0x05
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def wait_for_state(dut, target_state, timeout_cycles=60):
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if dut.state_out.value == target_state:
            return
    assert False, f"Timed out waiting for {STATE_NAMES[target_state]}, " \
                   f"last was {STATE_NAMES[int(dut.state_out.value)]}"


async def run_preload(dut):
    dut.preload_en.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)
    dut.preload_en.value = 0
    await wait_for_state(dut, IDLE)


async def fake_comparator(dut, fail_once_on_channel=None):
    """Background task: watches cs_n, and whenever a serial transfer
    finishes (cs_n returns high after being low), sets comparator_status
    for the FSM to sample. Locks immediately, except optionally fails
    once (too-low) on a specified channel to exercise the retry path."""
    failed_channels = set()
    prev_cs_n = 1

    while True:
        await RisingEdge(dut.clk)
        await ReadOnly()
        cs_n = int(dut.cs_n.value)
        ch = int(dut.current_channel.value)

        transfer_just_finished = (prev_cs_n == 0 and cs_n == 1)
        prev_cs_n = cs_n

        # leave the ReadOnly phase before driving any signal
        await NextTimeStep()

        if transfer_just_finished:
            if fail_once_on_channel is not None and ch == fail_once_on_channel \
                    and ch not in failed_channels:
                dut.comparator_status.value = 0b01  # too-low, force a retry
                failed_channels.add(ch)
            else:
                dut.comparator_status.value = 0b00  # lock


@cocotb.test()
async def test_preload_loads_initial_codes(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    assert dut.state_out.value == PRELOAD
    await run_preload(dut)
    assert dut.state_out.value == IDLE


@cocotb.test()
async def test_full_scan_all_lock_immediately(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)
    await run_preload(dut)

    cocotb.start_soon(fake_comparator(dut, fail_once_on_channel=None))

    dut.start_scan.value = 1
    await RisingEdge(dut.clk)
    dut.start_scan.value = 0

    await wait_for_state(dut, DONE, timeout_cycles=200)
    assert dut.current_channel.value == 3, "expected to finish on channel 3 (checked while still in DONE)"
    await wait_for_state(dut, IDLE)


@cocotb.test()
async def test_full_scan_with_one_retry(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)
    await run_preload(dut)

    cocotb.start_soon(fake_comparator(dut, fail_once_on_channel=2))

    dut.start_scan.value = 1
    await RisingEdge(dut.clk)
    dut.start_scan.value = 0

    await wait_for_state(dut, DONE, timeout_cycles=200)
    await wait_for_state(dut, IDLE)
    assert dut.lock_flag.value == 1 or dut.current_channel.value == 3
