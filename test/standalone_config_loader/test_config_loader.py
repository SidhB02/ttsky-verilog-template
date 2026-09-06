import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles, ReadOnly


async def reset_dut(dut):
    dut.cfg_data.value = 0
    dut.cfg_load_en.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def load_config(dut, payload_48bit):
    """Shifts in a 48-bit payload, 2 bits at a time, MSB-first."""
    dut.cfg_load_en.value = 1
    for i in range(24):
        chunk = (payload_48bit >> (46 - i * 2)) & 0b11
        dut.cfg_data.value = chunk
        await RisingEdge(dut.clk)
    dut.cfg_load_en.value = 0
    await ClockCycles(dut.clk, 1)


def build_payload(code0, code1, code2, code3, lock_window, step_size):
    return (code0 << 40) | (code1 << 32) | (code2 << 24) | (code3 << 16) | (lock_window << 8) | step_size


async def count_cfg_done_pulses(dut, cycles, counter):
    """Runs concurrently: watches cfg_done for `cycles` clock edges,
    safely reading via ReadOnly without ever driving signals itself."""
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        await ReadOnly()
        if dut.cfg_done.value == 1:
            counter[0] += 1


@cocotb.test()
async def test_config_load_basic(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    payload = build_payload(0x11, 0x22, 0x33, 0x44, 0x0F, 0x05)
    await load_config(dut, payload)

    assert dut.init_code0.value == 0x11, f"code0: {dut.init_code0.value}"
    assert dut.init_code1.value == 0x22, f"code1: {dut.init_code1.value}"
    assert dut.init_code2.value == 0x33, f"code2: {dut.init_code2.value}"
    assert dut.init_code3.value == 0x44, f"code3: {dut.init_code3.value}"
    assert dut.lock_window.value == 0x0F, f"lock_window: {dut.lock_window.value}"
    assert dut.step_size.value == 0x05, f"step_size: {dut.step_size.value}"


@cocotb.test()
async def test_cfg_done_pulses_once(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    payload = build_payload(0xAA, 0xBB, 0xCC, 0xDD, 0x03, 0x02)

    counter = [0]
    monitor_task = cocotb.start_soon(count_cfg_done_pulses(dut, 26, counter))

    # Driver: separate coroutine, only ever drives, never reads in ReadOnly phase
    dut.cfg_load_en.value = 1
    for i in range(24):
        chunk = (payload >> (46 - i * 2)) & 0b11
        dut.cfg_data.value = chunk
        await RisingEdge(dut.clk)
    dut.cfg_load_en.value = 0

    await ClockCycles(dut.clk, 2)   # let the monitor finish its 26 cycles
    await monitor_task

    assert counter[0] == 1, f"expected cfg_done to pulse exactly once, got {counter[0]}"


@cocotb.test()
async def test_reset_clears_outputs(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    payload = build_payload(0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF)
    await load_config(dut, payload)
    assert dut.init_code0.value == 0xFF

    await reset_dut(dut)
    assert dut.init_code0.value == 0, "code0 not cleared after reset"
    assert dut.lock_window.value == 0, "lock_window not cleared after reset"
    assert dut.step_size.value == 0, "step_size not cleared after reset"


@cocotb.test()
async def test_two_consecutive_loads(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    payload1 = build_payload(0x01, 0x02, 0x03, 0x04, 0x05, 0x06)
    await load_config(dut, payload1)
    assert dut.init_code0.value == 0x01

    payload2 = build_payload(0x10, 0x20, 0x30, 0x40, 0x50, 0x60)
    await load_config(dut, payload2)
    assert dut.init_code0.value == 0x10, "second load did not overwrite first"
    assert dut.step_size.value == 0x60
