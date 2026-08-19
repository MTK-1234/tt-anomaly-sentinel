import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, ClockCycles


# ── Helper Utilities ──────────────────────────────────────────────

async def reset_dut(dut):
    """Apply a clean hardware reset and release. All inputs set to defaults."""
    dut.ena.value    = 1
    dut.ui_in.value  = 128   # mid-scale default
    dut.uio_in.value = 0     # both config bits low
    dut.rst_n.value  = 0     # assert reset
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value  = 1     # release reset
    await ClockCycles(dut.clk, 2)
    await FallingEdge(dut.clk)  # let GL gate delays settle


async def settle(dut):
    """Wait for outputs to stabilise after a rising edge.
    In gate-level simulation with UNIT_DELAY=#1, every standard cell
    adds 1 ns of propagation delay.  The combinational path from a
    flip-flop to the pad can be 5-8 gates deep (~8 ns).
    FallingEdge is 10 ns after the rising edge — safe for any depth."""
    await FallingEdge(dut.clk)


def read_event_code(dut):
    """Read event_code[2:0] from uio_out."""
    return int(dut.uio_out.value) & 0x07


def read_fsm_state(dut):
    """Read debug_fsm[1:0] from uio_out[5:4]."""
    return (int(dut.uio_out.value) >> 4) & 0x03


def read_baseline(dut):
    """Read baseline_out from uo_out."""
    return int(dut.uo_out.value)


def read_wake(dut):
    """Read wake_cpu_int from uio_out[3]."""
    return (int(dut.uio_out.value) >> 3) & 0x01


# ── Test 1: Reset Values ─────────────────────────────────────────

@cocotb.test()
async def test_reset_values(dut):
    """After reset, baseline=128, event=Normal, FSM=FINE, wake=0."""
    dut._log.info("TEST 1: Reset Values")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    baseline = read_baseline(dut)
    event    = read_event_code(dut)
    fsm      = read_fsm_state(dut)
    wake     = read_wake(dut)

    dut._log.info(f"  baseline={baseline} event={bin(event)} fsm={bin(fsm)} wake={wake}")

    assert baseline == 128, f"baseline should be 128 after reset, got {baseline}"
    assert event == 0b000,  f"event should be 000 (Normal) after reset, got {bin(event)}"
    assert fsm   == 0b00,   f"FSM should be FINE (00) after reset, got {bin(fsm)}"
    assert wake  == 0,       f"wake should be 0 after reset, got {wake}"
    dut._log.info("  PASS")


# ── Test 2: Normal Flat Signal ────────────────────────────────────

@cocotb.test()
async def test_normal_flat_signal(dut):
    """50 cycles of constant input=128 must stay Normal with no alarm."""
    dut._log.info("TEST 2: Normal Flat Signal (128 for 50 cycles)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for _ in range(50):
        dut.ui_in.value = 128
        await RisingEdge(dut.clk)

    await settle(dut)

    event    = read_event_code(dut)
    fsm      = read_fsm_state(dut)
    baseline = read_baseline(dut)

    dut._log.info(f"  baseline={baseline} event={bin(event)} fsm={bin(fsm)}")

    assert event == 0b000, f"Flat signal must be Normal (000), got {bin(event)}"
    assert fsm   == 0b00,  f"Flat signal must stay FINE (00), got {bin(fsm)}"
    assert baseline == 128, f"Baseline must stay 128 on flat input, got {baseline}"
    dut._log.info("  PASS")


# ── Test 3: Transient Glitch ─────────────────────────────────────

@cocotb.test()
async def test_transient_glitch(dut):
    """A single-cycle spike to 255 must trigger Glitch (001), then clear."""
    dut._log.info("TEST 3: Transient Glitch (single spike to 255)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Phase 1 — Settle at 128
    for _ in range(20):
        dut.ui_in.value = 128
        await RisingEdge(dut.clk)

    # Phase 2 — Inject single spike
    #   Edge A: spike sampled → NBA: state<=HOLD, event<=000 (old FINE)
    dut.ui_in.value = 255
    await RisingEdge(dut.clk)

    # Phase 3 — Return to normal
    #   Edge B: return sampled → NBA: state<=FINE, event<=001 (old HOLD)
    #   We read after FallingEdge (10 ns later) so all GL gates settle.
    dut.ui_in.value = 128
    await RisingEdge(dut.clk)
    await settle(dut)

    event = read_event_code(dut)
    dut._log.info(f"  1 cycle after spike: event={bin(event)} (expect 001)")
    assert event == 0b001, f"Single spike should trigger Glitch (001), got {bin(event)}"

    # Phase 4 — Verify the glitch clears within a few cycles
    for _ in range(5):
        await RisingEdge(dut.clk)
    await settle(dut)

    event = read_event_code(dut)
    dut._log.info(f"  After settling: event={bin(event)} (expect 000)")
    assert event == 0b000, f"Glitch should clear to Normal (000), got {bin(event)}"
    dut._log.info("  PASS")


# ── Test 4: Permanent Baseline Shift ─────────────────────────────

@cocotb.test()
async def test_permanent_shift(dut):
    """A sustained jump from 128→200 must raise an alarm and the
       baseline must converge near the new value."""
    dut._log.info("TEST 4: Permanent Baseline Shift (128 → 200)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Phase 1 — Settle at 128
    for _ in range(20):
        dut.ui_in.value = 128
        await RisingEdge(dut.clk)

    # Phase 2 — Shift to 200 and verify an alarm fires
    alarm_seen = False
    shift_seen = False
    for _ in range(100):
        dut.ui_in.value = 200
        await RisingEdge(dut.clk)
        await settle(dut)
        event = read_event_code(dut)
        if event != 0b000:
            alarm_seen = True
        if event == 0b010:
            shift_seen = True

    baseline = read_baseline(dut)
    dut._log.info(f"  After 100 cycles at 200: baseline={baseline}, "
                  f"alarm_seen={alarm_seen}, shift_seen={shift_seen}")

    assert alarm_seen, "Expected at least one alarm during a baseline shift"
    assert shift_seen, "Expected Shift alarm (010) during sustained offset"

    # Phase 3 — Verify baseline convergence (within ±8 of target, the
    #            COARSE step size, is the design's convergence bound)
    assert abs(baseline - 200) <= 8, \
        f"Baseline should converge within ±8 of 200, got {baseline}"
    dut._log.info("  PASS")


# ── Test 5: Baseline Saturation (no wrap-around) ─────────────────

@cocotb.test()
async def test_baseline_does_not_wrap(dut):
    """Driving raw_in to 0 and 255 must clamp baseline, never wrap."""
    dut._log.info("TEST 5: Baseline Saturation (no wrap-around)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    # ── Part A: Drive toward 0 ──
    await reset_dut(dut)
    for _ in range(150):
        dut.ui_in.value = 0
        await RisingEdge(dut.clk)
    await settle(dut)

    baseline = read_baseline(dut)
    dut._log.info(f"  Driving to 0 → baseline={baseline}")
    assert baseline <= 10,  f"Baseline should be near 0, got {baseline}"
    assert baseline < 128,  f"Baseline WRAPPED AROUND (>128)! got {baseline}"

    # ── Part B: Drive toward 255 ──
    await reset_dut(dut)
    for _ in range(150):
        dut.ui_in.value = 255
        await RisingEdge(dut.clk)
    await settle(dut)

    baseline = read_baseline(dut)
    dut._log.info(f"  Driving to 255 → baseline={baseline}")
    assert baseline >= 245, f"Baseline should be near 255, got {baseline}"
    assert baseline > 128,  f"Baseline WRAPPED AROUND (<128)! got {baseline}"
    dut._log.info("  PASS")


# ── Test 6: Wake Interrupt Logic ─────────────────────────────────

@cocotb.test()
async def test_wake_interrupt(dut):
    """wake_cpu_int must be HIGH when event_code != 000, LOW otherwise."""
    dut._log.info("TEST 6: Wake Interrupt Logic")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Phase 1 — Normal: wake must be low
    for _ in range(20):
        dut.ui_in.value = 128
        await RisingEdge(dut.clk)
    await settle(dut)

    wake  = read_wake(dut)
    event = read_event_code(dut)
    dut._log.info(f"  Normal: wake={wake} event={bin(event)}")
    assert wake == 0, f"wake should be 0 when Normal, got wake={wake} event={bin(event)}"

    # Phase 2 — Trigger a glitch, wake must go high
    #   Edge A: spike sampled → state<=HOLD, event<=000
    dut.ui_in.value = 255
    await RisingEdge(dut.clk)

    #   Edge B: return  → state<=FINE,  event<=001 (reads old HOLD)
    dut.ui_in.value = 128
    await RisingEdge(dut.clk)
    await settle(dut)          # ← wait for GL gate delays

    wake  = read_wake(dut)
    event = read_event_code(dut)
    dut._log.info(f"  Alarm: wake={wake} event={bin(event)}")
    assert wake == 1, f"wake should be 1 during alarm, got wake={wake} event={bin(event)}"

    # Phase 3 — Settle back, wake must return low
    for _ in range(10):
        await RisingEdge(dut.clk)
    await settle(dut)

    wake  = read_wake(dut)
    event = read_event_code(dut)
    dut._log.info(f"  Settled: wake={wake} event={bin(event)}")
    assert wake == 0, f"wake should return to 0 after alarm clears, got wake={wake}"
    dut._log.info("  PASS")
