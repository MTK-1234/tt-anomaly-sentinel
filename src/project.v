`default_nettype none

module tt_um_MTK1234_anomaly_sentinel (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

    // ========================================================
    // 1. PIN DIRECTION & ROUTING
    // ========================================================
    assign uio_oe = 8'b0011_1111;

    wire [7:0] raw_in              = ui_in;
    wire       cfg_thresh_scale    = uio_in[6];
    wire       cfg_momentum_en     = uio_in[7];

    // Tie off unused inputs to suppress Verilator lint warnings.
    // The synthesiser optimises this away to zero area.
    wire _unused = &{ena, uio_in[5:0], 1'b0};

    reg  [7:0] baseline_out;
    reg  [2:0] event_code;
    reg  [1:0] debug_fsm;

    wire       wake_cpu_int        = (event_code != 3'b000);

    assign uo_out       = baseline_out;
    assign uio_out[2:0] = event_code;
    assign uio_out[3]   = wake_cpu_int;
    assign uio_out[5:4] = debug_fsm;
    assign uio_out[7:6] = 2'b00;

    // ========================================================
    // 2. HARDWARE LOGIC (The Sentinel Core)
    // ========================================================

    // --- Core tracking registers ---
    reg [7:0] baseline;
    reg [7:0] mad;
    reg       prev_sign;
    reg [3:0] corr_ctr;
    reg signed [4:0] tpe_ctr;
    reg [1:0] state;

    // --- Block 6 registers (Momentum Drift Engine) ---
    reg [7:0] prev_baseline;
    reg signed [4:0] drift_ctr;

    // --- Block 7 registers (Stuck Sensor Detector) ---
    reg [3:0] stuck_ctr;

    localparam STATE_FINE   = 2'b00;
    localparam STATE_HOLD   = 2'b01;
    localparam STATE_COARSE = 2'b10;

    // --- Combinational datapath ---
    wire [7:0] abs_diff  = (raw_in > baseline) ? (raw_in - baseline) : (baseline - raw_in);
    wire       sign_diff = (raw_in > baseline);

    // Saturating threshold: mad×2 or mad×4
    wire [8:0] thresh_x4  = {mad[6:0], 2'b00};
    wire [7:0] thresh_4s  = (thresh_x4 > 9'd255) ? 8'd255 : thresh_x4[7:0];
    wire [7:0] threshold  = cfg_thresh_scale ? thresh_4s : {mad[6:0], 1'b0};

    wire       is_outlier = (abs_diff > threshold);

    wire tpe_sat_pos   = (tpe_ctr >= 5'sd14);
    wire tpe_sat_neg   = (tpe_ctr <= -5'sd15);
    wire tpe_saturated = tpe_sat_pos | tpe_sat_neg;

    // ========================================================
    // Clocked logic — all 8 blocks
    // ========================================================
    always @(posedge clk) begin
        if (!rst_n) begin
            baseline      <= 8'd128;
            mad           <= 8'd4;
            prev_sign     <= 1'b0;
            corr_ctr      <= 4'd0;
            tpe_ctr       <= 5'sd0;
            state         <= STATE_FINE;
            prev_baseline <= 8'd128;
            drift_ctr     <= 5'sd0;
            stuck_ctr     <= 4'd0;
            event_code    <= 3'b000;
            debug_fsm     <= 2'b00;
            baseline_out  <= 8'd128;
        end else if (ena) begin

            // ----------------------------------------------------------
            // Block 2: Innovation Correlation Monitor
            //   Only update when abs_diff > 0 so a constant signal does
            //   not ramp corr_ctr and falsely trigger COARSE.
            // ----------------------------------------------------------
            if (abs_diff > 8'd0) begin
                prev_sign <= sign_diff;
                if (sign_diff == prev_sign) begin
                    if (corr_ctr < 4'd15) corr_ctr <= corr_ctr + 1;
                end else begin
                    if (corr_ctr > 4'd0) corr_ctr <= corr_ctr - 1;
                end
            end

            // ----------------------------------------------------------
            // Block 3: Temporal Persistence Engine
            //   Snap ±1 → 0 to prevent arithmetic right-shift stuck at −1.
            // ----------------------------------------------------------
            if (is_outlier) begin
                if (sign_diff && !tpe_sat_pos) tpe_ctr <= tpe_ctr + 1;
                else if (!sign_diff && !tpe_sat_neg) tpe_ctr <= tpe_ctr - 1;
            end else begin
                tpe_ctr <= (tpe_ctr == 5'sd1 || tpe_ctr == -5'sd1)
                            ? 5'sd0
                            : (tpe_ctr >>> 1);
            end

            // ----------------------------------------------------------
            // Block 6: Momentum Drift Engine  [NEW]
            //   Tracks rate-of-change of the baseline.  Detects slow
            //   drift that stays below the MAD threshold per-sample.
            //   Gated by cfg_momentum_en — disabled when pin is low.
            // ----------------------------------------------------------
            if (cfg_momentum_en) begin
                prev_baseline <= baseline;
                if (baseline > prev_baseline) begin
                    if (drift_ctr < 5'sd14) drift_ctr <= drift_ctr + 1;
                end else if (baseline < prev_baseline) begin
                    if (drift_ctr > -5'sd14) drift_ctr <= drift_ctr - 1;
                end else begin
                    drift_ctr <= (drift_ctr == 5'sd1 || drift_ctr == -5'sd1)
                                  ? 5'sd0 : (drift_ctr >>> 1);
                end
            end else begin
                prev_baseline <= baseline;
                drift_ctr     <= 5'sd0;
            end

            // ----------------------------------------------------------
            // Block 7: Flat-Line / Stuck Sensor Detector  [NEW]
            //   Counts consecutive cycles where abs_diff == 0.
            //   After 16 identical samples, the sensor is flagged stuck.
            //   Self-healing: any change resets the counter.
            // ----------------------------------------------------------
            if (abs_diff == 8'd0) begin
                if (stuck_ctr < 4'd15) stuck_ctr <= stuck_ctr + 1;
            end else begin
                stuck_ctr <= 4'd0;
            end

            // ----------------------------------------------------------
            // Block 4 & 1: Tri-Mode FSM & Baseline Update
            //   COARSE resets corr_ctr (halved), tpe_ctr, and drift_ctr
            //   so the FSM can exit once baseline catches up.
            //   Last NBA wins — intentionally overrides Blocks 2/3/6.
            // ----------------------------------------------------------
            if (tpe_saturated || corr_ctr > 4'd12) begin
                state <= STATE_COARSE;

                // Saturating baseline — COARSE step (±8)
                baseline <= sign_diff
                    ? ((baseline > 8'd247) ? 8'd255 : (baseline + 8'd8))
                    : ((baseline < 8'd8)   ? 8'd0   : (baseline - 8'd8));

                corr_ctr  <= {1'b0, corr_ctr[3:1]};   // halve
                tpe_ctr   <= 5'sd0;                     // consumed
                drift_ctr <= 5'sd0;                     // consumed
            end
            else if (is_outlier) begin
                state <= STATE_HOLD;
            end
            else begin
                state <= STATE_FINE;
                if (abs_diff > 8'd0) begin
                    // Saturating baseline — FINE step (±1)
                    baseline <= sign_diff
                        ? ((baseline == 8'd255) ? 8'd255 : (baseline + 8'd1))
                        : ((baseline == 8'd0)   ? 8'd0   : (baseline - 8'd1));
                end

                if (abs_diff > mad && mad < 8'd127) mad <= mad + 1;
                else if (abs_diff < mad && mad > 8'd1) mad <= mad - 1;
            end

            // ----------------------------------------------------------
            // Block 8: Extended Event Classifier  [ENHANCED]
            //   Priority-encoded from highest to lowest:
            //     111 = Stuck Sensor   (flat-line for 16 cycles)
            //     110 = Drift Warning  (momentum engine, when enabled)
            //     011 = Volatility     (MAD explosion)
            //     010 = Baseline Shift (COARSE mode active)
            //     001 = Transient Glitch (HOLD mode active)
            //     000 = Normal / Sleep
            //   Codes 100, 101 reserved for future use.
            //   NOTE: reads PREVIOUS cycle's state/counters (NBA latency).
            // ----------------------------------------------------------
            if (stuck_ctr == 4'd15) begin
                event_code <= 3'b111;    // Stuck Sensor
            end else if (cfg_momentum_en
                         && (drift_ctr >= 5'sd12 || drift_ctr <= -5'sd12)) begin
                event_code <= 3'b110;    // Drift Warning
            end else if (mad > 8'd64) begin
                event_code <= 3'b011;    // Volatility Alarm
            end else if (state == STATE_COARSE) begin
                event_code <= 3'b010;    // Baseline Shift
            end else if (state == STATE_HOLD) begin
                event_code <= 3'b001;    // Transient Glitch
            end else begin
                event_code <= 3'b000;    // Normal / Sleep
            end

            baseline_out <= baseline;
            debug_fsm    <= state;
        end
    end

endmodule
