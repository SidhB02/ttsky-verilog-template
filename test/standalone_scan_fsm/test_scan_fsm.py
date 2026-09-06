import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

IDLE, SELECT_CH, LOAD_CODE, SETTLE, SAMPLE, LOCK_CHECK, ADJUST_CODE, NEXT_CHANNEL, DONE = range(9)

STATE_NAMES = ["IDLE", "SELECT_CH", "LOAD_CODE", "SETTLE", "SAMPLE",
               "LOCK_CHECK", "ADJUST_CODE", "NEXT_CHANNEL", "DONE"]


async def reset_dut(dut):
    dut.start_scan.value = 0
    dut.serializer_done.value = 0
    dut.comparator_status.value = 0
    dut.retry_limit_reached.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def wait_for_state(dut, target_state, timeout_cycles=30):
    for _ in range(timeout_cycles):
        await RisingEdge(dut.clk)
        if dut.state_out.value == target_state:
            return
    assert False, f"Timed out waiting for state {STATE_NAMES[target_state]}, " \
                   f"last state was {STATE_NAMES[int(dut.state_out.value)]}"


async def run_one_channel_immediate_lock(dut):
    """Drives one channel through LOAD_CODE -> SETTLE -> SAMPLE -> LOCK_CHECK
    with an immediate lock (comparator_status=00), ending at NEXT_CHANNEL."""
    await wait_for_state(dut, LOAD_CODE)
    dut.serializer_done.value = 1
    await wait_for_state(dut, SETTLE)
    dut.serializer_done.value = 0
    await wait_for_state(dut, SAMPLE)
    dut.comparator_status.value = 0b00
    await wait_for_state(dut, LOCK_CHECK)
    await wait_for_state(dut, NEXT_CHANNEL)


@cocotb.test()
async def test_reset_goes_to_idle(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)
    assert dut.state_out.value == IDLE
    assert dut.current_channel.value == 0


@cocotb.test()
async def test_immediate_lock_loops_back_for_next_channel(dut):
    """Channel 0 locks immediately -> NEXT_CHANNEL -> not last channel
    -> loops back to SELECT_CH, current_channel increments to 1."""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.start_scan.value = 1
    await RisingEdge(dut.clk)
    dut.start_scan.value = 0

    assert dut.current_channel.value == 0
    await run_one_channel_immediate_lock(dut)
    await wait_for_state(dut, SELECT_CH)   # loops back, not DONE
    assert dut.current_channel.value == 1, \
        f"expected channel to advance to 1, got {int(dut.current_channel.value)}"


@cocotb.test()
async def test_full_scan_all_four_channels_reaches_done(dut):
    """Drive all 4 channels through immediate lock, confirm it correctly
    reaches DONE only after the 4th channel, then returns to IDLE."""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.start_scan.value = 1
    await RisingEdge(dut.clk)
    dut.start_scan.value = 0

    for ch in range(4):
        assert dut.current_channel.value == ch, \
            f"expected channel {ch} before processing, got {int(dut.current_channel.value)}"
        await run_one_channel_immediate_lock(dut)

        if ch < 3:
            await wait_for_state(dut, SELECT_CH)  # loop to next channel
        else:
            await wait_for_state(dut, DONE)        # last channel -> DONE
            await wait_for_state(dut, IDLE)


@cocotb.test()
async def test_retry_then_lock(dut):
    """Comparator says too-low first, retry limit not reached -> ADJUST_CODE
    -> LOAD_CODE again -> this time locks -> NEXT_CHANNEL."""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.retry_limit_reached.value = 0
    dut.start_scan.value = 1
    await RisingEdge(dut.clk)
    dut.start_scan.value = 0

    # first pass: fails (too-low)
    await wait_for_state(dut, LOAD_CODE)
    dut.serializer_done.value = 1
    await wait_for_state(dut, SETTLE)
    dut.serializer_done.value = 0
    await wait_for_state(dut, SAMPLE)
    dut.comparator_status.value = 0b01  # too-low
    await wait_for_state(dut, LOCK_CHECK)
    await wait_for_state(dut, ADJUST_CODE)
    await wait_for_state(dut, LOAD_CODE)  # retried

    # second pass: locks
    dut.serializer_done.value = 1
    await wait_for_state(dut, SETTLE)
    dut.serializer_done.value = 0
    await wait_for_state(dut, SAMPLE)
    dut.comparator_status.value = 0b00
    await wait_for_state(dut, LOCK_CHECK)
    await wait_for_state(dut, NEXT_CHANNEL)


@cocotb.test()
async def test_never_locks_does_not_stall(dut):
    """Comparator always fails, retry_limit_reached eventually goes high
    -> FSM must give up and move to NEXT_CHANNEL instead of looping forever."""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.start_scan.value = 1
    await RisingEdge(dut.clk)
    dut.start_scan.value = 0

    await wait_for_state(dut, LOAD_CODE)
    dut.serializer_done.value = 1
    await wait_for_state(dut, SETTLE)
    dut.serializer_done.value = 0
    await wait_for_state(dut, SAMPLE)
    dut.comparator_status.value = 0b10  # too-high, never locks
    dut.retry_limit_reached.value = 1   # already at limit
    await wait_for_state(dut, LOCK_CHECK)
    await wait_for_state(dut, NEXT_CHANNEL)  # must give up, not loop forever


@cocotb.test()
async def test_reset_mid_scan(dut):
    """Reset asserted while mid-scan (e.g. in SETTLE) must immediately force
    the FSM back to IDLE with channel counter cleared."""
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.start_scan.value = 1
    await RisingEdge(dut.clk)
    dut.start_scan.value = 0
    await wait_for_state(dut, LOAD_CODE)
    dut.serializer_done.value = 1
    await wait_for_state(dut, SETTLE)

    # reset mid-scan
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    assert dut.state_out.value == IDLE, "FSM did not return to IDLE on reset"
    assert dut.current_channel.value == 0, "channel counter not cleared on reset"
    dut.rst_n.value = 1
