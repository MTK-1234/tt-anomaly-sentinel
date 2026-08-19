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
    adds 1 ns of propagation delay.  FallingEdge is 10 ns after the
    rising edge — safe for any combinational depth in this design."""
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


# ══════════════════════════════════════════════════════════════════
# CORE TESTS (Blocks 1-5)
# ══════════════════════════════════════════════════════════════════

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


# ── Test 2: Normal Noisy Signal ──────────────────────────────────

@cocotb.test()
async def test_normal_noisy_signal(dut):
    """50 cycles of ±1 noise around 128 must stay Normal with no alarm.
    Uses alternating 127/128 to avoid triggering the stuck-sensor detector."""
    dut._log.info("TEST 2: Normal Noisy Signal (±1 around 128, 50 cycles)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    for i in range(50):
        dut.ui_in.value = 127 + (i % 2)   # alternates 127, 128
        await RisingEdge(dut.clk)

    await settle(dut)

    event    = read_event_code(dut)
    fsm      = read_fsm_state(dut)
    baseline = read_baseline(dut)

    dut._log.info(f"  baseline={baseline} event={bin(event)} fsm={bin(fsm)}")

    assert event == 0b000,          f"Noisy signal must be Normal (000), got {bin(event)}"
    assert fsm   == 0b00,           f"Noisy signal must stay FINE (00), got {bin(fsm)}"
    assert 126 <= baseline <= 129,  f"Baseline should be near 128, got {baseline}"
    dut._log.info("  PASS")


# ── Test 3: Transient Glitch ─────────────────────────────────────

@cocotb.test()
async def test_transient_glitch(dut):
    """A single-cycle spike to 255 must trigger Glitch (001), then clear."""
    dut._log.info("TEST 3: Transient Glitch (single spike to 255)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Phase 1 — Settle with ±1 noise (avoids stuck alarm)
    for i in range(20):
        dut.ui_in.value = 127 + (i % 2)
        await RisingEdge(dut.clk)

    # Phase 2 — Inject single spike
    dut.ui_in.value = 255
    await RisingEdge(dut.clk)

    # Phase 3 — Return to normal and read after 1-cycle event pipeline
    dut.ui_in.value = 128
    await RisingEdge(dut.clk)
    await settle(dut)

    event = read_event_code(dut)
    dut._log.info(f"  1 cycle after spike: event={bin(event)} (expect 001)")
    assert event == 0b001, f"Single spike should trigger Glitch (001), got {bin(event)}"

    # Phase 4 — Verify the glitch clears (use noise to avoid stuck alarm)
    for i in range(5):
        dut.ui_in.value = 127 + (i % 2)
        await RisingEdge(dut.clk)
    await settle(dut)

    event = read_event_code(dut)
    dut._log.info(f"  After settling: event={bin(event)} (expect 000)")
    assert event == 0b000, f"Glitch should clear to Normal (000), got {bin(event)}"
    dut._log.info("  PASS")


# ── Test 4: Permanent Baseline Shift ─────────────────────────────

@cocotb.test()
async def test_permanent_shift(dut):
    """A sustained jump from ~128→200 must raise an alarm and
       the baseline must converge near the new value."""
    dut._log.info("TEST 4: Permanent Baseline Shift (128 → 200)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Phase 1 — Settle with noise
    for i in range(20):
        dut.ui_in.value = 127 + (i % 2)
        await RisingEdge(dut.clk)

    # Phase 2 — Shift to 200 and verify alarm fires
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

    # Phase 1 — Normal (use noise to avoid stuck alarm): wake must be low
    for i in range(20):
        dut.ui_in.value = 127 + (i % 2)
        await RisingEdge(dut.clk)
    await settle(dut)

    wake  = read_wake(dut)
    event = read_event_code(dut)
    dut._log.info(f"  Normal: wake={wake} event={bin(event)}")
    assert wake == 0, f"wake should be 0 when Normal, got wake={wake} event={bin(event)}"

    # Phase 2 — Trigger a glitch: wake must go high
    dut.ui_in.value = 255
    await RisingEdge(dut.clk)
    dut.ui_in.value = 128
    await RisingEdge(dut.clk)
    await settle(dut)

    wake  = read_wake(dut)
    event = read_event_code(dut)
    dut._log.info(f"  Alarm: wake={wake} event={bin(event)}")
    assert wake == 1, f"wake should be 1 during alarm, got wake={wake} event={bin(event)}"

    # Phase 3 — Settle back with noise: wake must return low
    for i in range(10):
        dut.ui_in.value = 127 + (i % 2)
        await RisingEdge(dut.clk)
    await settle(dut)

    wake  = read_wake(dut)
    event = read_event_code(dut)
    dut._log.info(f"  Settled: wake={wake} event={bin(event)}")
    assert wake == 0, f"wake should return to 0 after alarm clears, got wake={wake}"
    dut._log.info("  PASS")


# ══════════════════════════════════════════════════════════════════
# ENHANCEMENT TESTS (Blocks 6-8)
# ══════════════════════════════════════════════════════════════════

# ── Test 7: Slow Drift Detection (Momentum Engine) ───────────────

@cocotb.test()
async def test_slow_drift(dut):
    """A steadily increasing input should trigger Drift Warning (110)
       when the momentum engine is enabled."""
    dut._log.info("TEST 7: Slow Drift Detection (momentum ON)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Enable momentum engine: uio_in[7] = 1
    dut.uio_in.value = 0x80

    # Ramp the input: 128, 129, 130, ... 167  (40 steps)
    drift_seen = False
    for i in range(40):
        dut.ui_in.value = min(255, 128 + i)
        await RisingEdge(dut.clk)
        await settle(dut)
        event = read_event_code(dut)
        if event == 0b110:
            drift_seen = True

    dut._log.info(f"  drift_seen={drift_seen}")
    assert drift_seen, "Expected Drift Warning (110) during steady ramp with momentum ON"
    dut._log.info("  PASS")


# ── Test 8: Stuck Sensor Detection ────────────────────────────────

@cocotb.test()
async def test_stuck_sensor(dut):
    """16+ consecutive identical samples must trigger Stuck Sensor (111)."""
    dut._log.info("TEST 8: Stuck Sensor Detection")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Phase 1 — Settle with noise so stuck_ctr stays at 0
    for i in range(20):
        dut.ui_in.value = 127 + (i % 2)
        await RisingEdge(dut.clk)

    # Phase 2 — Feed constant 128 for 25 cycles (exceeds 16-cycle threshold)
    for _ in range(25):
        dut.ui_in.value = 128
        await RisingEdge(dut.clk)
    await settle(dut)

    event = read_event_code(dut)
    dut._log.info(f"  After 25 constant cycles: event={bin(event)} (expect 111: Stuck)")
    assert event == 0b111, f"Expected Stuck Sensor (111), got {bin(event)}"

    # Phase 3 — Verify self-healing: one different sample should clear it
    dut.ui_in.value = 130
    await RisingEdge(dut.clk)
    # After this edge: stuck_ctr resets. Next cycle event clears.
    dut.ui_in.value = 130
    await RisingEdge(dut.clk)
    await settle(dut)

    event = read_event_code(dut)
    dut._log.info(f"  After signal change: event={bin(event)} (expect not 111)")
    assert event != 0b111, f"Stuck alarm should clear after signal change, got {bin(event)}"
    dut._log.info("  PASS")


# ── Test 9: Momentum Disabled ────────────────────────────────────

@cocotb.test()
async def test_momentum_disable(dut):
    """With cfg_momentum_en=0, the Drift Warning must NOT fire
       even during a steady ramp."""
    dut._log.info("TEST 9: Momentum Disabled (drift must not fire)")
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Momentum explicitly disabled (default)
    dut.uio_in.value = 0x00

    # Same ramp as test_slow_drift
    drift_seen = False
    for i in range(40):
        dut.ui_in.value = min(255, 128 + i)
        await RisingEdge(dut.clk)
        await settle(dut)
        event = read_event_code(dut)
        if event == 0b110:
            drift_seen = True

    dut._log.info(f"  drift_seen={drift_seen} (expect False)")
    assert not drift_seen, "Drift Warning should NOT fire when momentum is disabled"
    dut._log.info("  PASS")
