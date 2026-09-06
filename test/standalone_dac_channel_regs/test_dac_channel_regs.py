import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles


async def reset_dut(dut):
    dut.ch_sel.value = 0
    dut.code_wr_en.value = 0
    dut.code_in.value = 0
    dut.lock_wr_en.value = 0
    dut.lock_in.value = 0
    dut.retry_inc.value = 0
    dut.retry_rst.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def write_code(dut, ch, value):
    dut.ch_sel.value = ch
    dut.code_in.value = value
    dut.code_wr_en.value = 1
    await RisingEdge(dut.clk)
    dut.code_wr_en.value = 0
    await ClockCycles(dut.clk, 1)


async def write_lock(dut, ch, value):
    dut.ch_sel.value = ch
    dut.lock_in.value = value
    dut.lock_wr_en.value = 1
    await RisingEdge(dut.clk)
    dut.lock_wr_en.value = 0
    await ClockCycles(dut.clk, 1)


async def pulse_retry_inc(dut, ch):
    dut.ch_sel.value = ch
    dut.retry_inc.value = 1
    await RisingEdge(dut.clk)
    dut.retry_inc.value = 0
    await ClockCycles(dut.clk, 1)


async def pulse_retry_rst(dut, ch):
    dut.ch_sel.value = ch
    dut.retry_rst.value = 1
    await RisingEdge(dut.clk)
    dut.retry_rst.value = 0
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_reset_clears_all_channels(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for ch in range(4):
        dut.ch_sel.value = ch
        await ClockCycles(dut.clk, 1)
        assert dut.code_out.value == 0, f"ch{ch} code not cleared"
        assert dut.lock_out.value == 0, f"ch{ch} lock not cleared"
        assert dut.retry_out.value == 0, f"ch{ch} retry not cleared"


@cocotb.test()
async def test_code_write_and_channel_isolation(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Write distinct codes to each channel
    test_codes = [0x11, 0x22, 0x33, 0x44]
    for ch, val in enumerate(test_codes):
        await write_code(dut, ch, val)

    # Verify each channel kept its own value (no cross-talk)
    for ch, val in enumerate(test_codes):
        dut.ch_sel.value = ch
        await ClockCycles(dut.clk, 1)
        assert dut.code_out.value == val, f"ch{ch} expected 0x{val:02X}, got {dut.code_out.value}"


@cocotb.test()
async def test_lock_flag_write_and_isolation(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Lock channel 1 and 3 only
    await write_lock(dut, 1, 1)
    await write_lock(dut, 3, 1)

    expected = {0: 0, 1: 1, 2: 0, 3: 1}
    for ch, exp in expected.items():
        dut.ch_sel.value = ch
        await ClockCycles(dut.clk, 1)
        assert dut.lock_out.value == exp, f"ch{ch} lock expected {exp}, got {dut.lock_out.value}"


@cocotb.test()
async def test_retry_counter_increment(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Increment channel 2's retry counter 3 times
    for _ in range(3):
        await pulse_retry_inc(dut, 2)

    dut.ch_sel.value = 2
    await ClockCycles(dut.clk, 1)
    assert dut.retry_out.value == 3, f"expected retry=3, got {dut.retry_out.value}"

    # Other channels should be untouched
    for ch in [0, 1, 3]:
        dut.ch_sel.value = ch
        await ClockCycles(dut.clk, 1)
        assert dut.retry_out.value == 0, f"ch{ch} retry should still be 0"


@cocotb.test()
async def test_retry_reset(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Bump channel 0's retry to 2, then reset it
    await pulse_retry_inc(dut, 0)
    await pulse_retry_inc(dut, 0)

    dut.ch_sel.value = 0
    await ClockCycles(dut.clk, 1)
    assert dut.retry_out.value == 2, f"expected retry=2 before reset, got {dut.retry_out.value}"

    await pulse_retry_rst(dut, 0)

    dut.ch_sel.value = 0
    await ClockCycles(dut.clk, 1)
    assert dut.retry_out.value == 0, f"expected retry=0 after reset, got {dut.retry_out.value}"
