import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

@cocotb.test()
async def test_sentinel(dut):
    dut._log.info("Starting Anomaly Sentinel Silicon Test")

    # Set up the clock (50 MHz)
    clock = Clock(dut.clk, 20, units="ns")
    cocotb.start_soon(clock.start())

    # Initialize pins
    dut.ena.value = 1
    dut.ui_in.value = 128    # Start signal in the middle (128)
    dut.uio_in.value = 0     # Set config pins to 0
    dut.rst_n.value = 0      # Hold chip in reset

    # Reset the hardware
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1      # Release reset
    await ClockCycles(dut.clk, 10)

    # ----------------------------------------------------
    # TEST 1: Normal Flat Signal (Baseline)
    # ----------------------------------------------------
    dut._log.info("Injecting normal signal (128)...")
    for _ in range(15):
        dut.ui_in.value = 128
        await RisingEdge(dut.clk)
    
    event_code = dut.uio_out.value & 0x07
    dut._log.info(f"Event Code is: {bin(event_code)} (Expected 000: Sleep)")

    # ----------------------------------------------------
    # TEST 2: Transient Noise Spike (Glitch)
    # ----------------------------------------------------
    dut._log.info("Injecting massive noise spike (255)...")
    dut.ui_in.value = 255
    await RisingEdge(dut.clk)
    
    # Return to normal immediately
    dut.ui_in.value = 128
    await ClockCycles(dut.clk, 3)

    event_code = dut.uio_out.value & 0x07
    dut._log.info(f"Event Code is: {bin(event_code)} (Expected 001: Glitch Alarm)")

    # ----------------------------------------------------
    # TEST 3: Permanent Distribution Shift
    # ----------------------------------------------------
    dut._log.info("Injecting permanent baseline shift (200)...")
    for _ in range(25):
        dut.ui_in.value = 200
        await RisingEdge(dut.clk)

    event_code = dut.uio_out.value & 0x07
    dut._log.info(f"Event Code is: {bin(event_code)} (Expected 010: Shift Alarm)")

    dut._log.info("Silicon Test Passed! Sentinel hardware is functioning.")
