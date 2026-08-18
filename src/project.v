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
    
    // Set Bidirectional Pins Direction (uio_oe)
    // We want uio[5:0] as OUTPUTS (Event Code & Debug) -> 1
    // We want uio[7:6] as INPUTS (Configuration) -> 0
    // Binary: 00111111 = Hex: 3F
    assign uio_oe = 8'b0011_1111; 

    // Route inputs to readable wire names
    wire [7:0] raw_in              = ui_in;
    wire       cfg_thresh_scale    = uio_in[6];
    wire       cfg_momentum_en     = uio_in[7];

    // Declare internal hardware registers for our outputs
    reg  [7:0] baseline_out;
    reg  [2:0] event_code;
    reg  [1:0] debug_fsm;
    
    // The wake interrupt is high anytime the event code is not 000
    wire       wake_cpu_int        = (event_code != 3'b000);

    // Route internal registers to the physical TT output pins
    assign uo_out       = baseline_out;
    assign uio_out[2:0] = event_code;
    assign uio_out[3]   = wake_cpu_int;
    assign uio_out[5:4] = debug_fsm;
    assign uio_out[7:6] = 2'b00; // Tie off unused output drivers for input pins

     // ========================================================
    // 2. HARDWARE LOGIC (The Sentinel Core)
    // ========================================================

    // Internal State Registers
    reg [7:0] baseline;
    reg [7:0] mad;
    reg       prev_sign;
    reg [3:0] corr_ctr;
    reg signed [4:0] tpe_ctr;
    reg [1:0] state;

    // FSM State Definitions
    localparam STATE_FINE   = 2'b00;
    localparam STATE_HOLD   = 2'b01;
    localparam STATE_COARSE = 2'b10;

    // --- Combinational Math ---
    // Absolute difference between raw input and current baseline
    wire [7:0] abs_diff  = (raw_in > baseline) ? (raw_in - baseline) : (baseline - raw_in);
    // 1 if input is higher, 0 if lower
    wire       sign_diff = (raw_in > baseline);
    
    // Dynamic Threshold: MAD * 2 or MAD * 4 based on config pin
    // Using bit-shifts (<< 1 or << 2) to avoid hardware multipliers
    wire [7:0] threshold = cfg_thresh_scale ? {mad[5:0], 2'b00} : {mad[6:0], 1'b0};
    wire       is_outlier = (abs_diff > threshold);

    // Temporal Persistence Saturation Checks
    wire tpe_sat_pos = (tpe_ctr >= 5'sd14);
    wire tpe_sat_neg = (tpe_ctr <= -5'sd15);
    wire tpe_saturated = tpe_sat_pos | tpe_sat_neg;

    always @(posedge clk) begin
        if (!rst_n) begin
            // Reset state
            baseline      <= 8'd128; // Start at center of 8-bit range
            mad           <= 8'd4;   // Small initial noise assumption
            prev_sign     <= 1'b0;
            corr_ctr      <= 4'd0;
            tpe_ctr       <= 5'sd0;
            state         <= STATE_FINE;
            event_code    <= 3'b000;
            debug_fsm     <= 2'b00;
            baseline_out  <= 8'd128;
        end else if (ena) begin
            
            // ----------------------------------------------------
            // Block 2: Innovation Correlation Monitor
            // ----------------------------------------------------
            prev_sign <= sign_diff;
            if (sign_diff == prev_sign) begin
                // Error stuck in same direction -> Correlated!
                if (corr_ctr < 4'd15) corr_ctr <= corr_ctr + 1;
            end else begin
                // Error flipping -> Healthy White Noise
                if (corr_ctr > 4'd0) corr_ctr <= corr_ctr - 1;
            end

            // ----------------------------------------------------
            // Block 3: Temporal Persistence Engine (Leaky Counter)
            // ----------------------------------------------------
            if (is_outlier) begin
                // Accumulate outlier persistence
                if (sign_diff && !tpe_sat_pos) tpe_ctr <= tpe_ctr + 1;
                else if (!sign_diff && !tpe_sat_neg) tpe_ctr <= tpe_ctr - 1;
            end else begin
                // Decay toward zero (Arithmetic shift right = divide by 2)
                // This gives it the "forgetting" memory property
                tpe_ctr <= (tpe_ctr >>> 1);
            end

            // ----------------------------------------------------
            // Block 4: Tri-Mode FSM & Block 1: Baseline Update
            // ----------------------------------------------------
            if (tpe_saturated || corr_ctr > 4'd12) begin
                state <= STATE_COARSE;
                // COARSE Tracking: Jump by 8 to rapidly catch the moving signal
                baseline <= sign_diff ? (baseline + 8'd8) : (baseline - 8'd8);
            end 
            else if (is_outlier) begin
                state <= STATE_HOLD;
                // HOLD Mode: Massive spike, do nothing to the baseline
            end 
            else begin
                state <= STATE_FINE;
                // FINE Tracking: Step by 1 to gently surf the noise
                if (abs_diff > 8'd0) begin
                    baseline <= sign_diff ? (baseline + 8'd1) : (baseline - 8'd1);
                end
                
                // Update MAD (Spread) ONLY in fine mode so outliers don't ruin it
                if (abs_diff > mad && mad < 8'd127) mad <= mad + 1;
                else if (abs_diff < mad && mad > 8'd1) mad <= mad - 1;
            end

            // ----------------------------------------------------
            // Block 5: Semantic Event Classifier
            // ----------------------------------------------------
            if (mad > 8'd64) begin
                event_code <= 3'b011; // Volatility Alarm (Massive noise environment)
            end else if (state == STATE_COARSE) begin
                event_code <= 3'b010; // Baseline Shift Alarm (Signal permanently moved)
            end else if (state == STATE_HOLD) begin
                event_code <= 3'b001; // Impulse Glitch Warning (1-cycle spike hit)
            end else begin
                event_code <= 3'b000; // Normal (All Clear, CPU can sleep)
            end

            // Push internal registers to outputs
            baseline_out <= baseline;
            debug_fsm    <= state;
        end
    end

endmodule
endmodule
