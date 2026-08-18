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
    reg [7:0] baseline;
    reg [7:0] mad;
    reg       prev_sign;
    reg [3:0] corr_ctr;
    reg signed [4:0] tpe_ctr;
    reg [1:0] state;

    localparam STATE_FINE   = 2'b00;
    localparam STATE_HOLD   = 2'b01;
    localparam STATE_COARSE = 2'b10;

    wire [7:0] abs_diff  = (raw_in > baseline) ? (raw_in - baseline) : (baseline - raw_in);
    wire       sign_diff = (raw_in > baseline);
    
    wire [7:0] threshold = cfg_thresh_scale ? {mad[5:0], 2'b00} : {mad[6:0], 1'b0};
    wire       is_outlier = (abs_diff > threshold);

    wire tpe_sat_pos = (tpe_ctr >= 5'sd14);
    wire tpe_sat_neg = (tpe_ctr <= -5'sd15);
    wire tpe_saturated = tpe_sat_pos | tpe_sat_neg;

    always @(posedge clk) begin
        if (!rst_n) begin
            baseline      <= 8'd128;
            mad           <= 8'd4;
            prev_sign     <= 1'b0;
            corr_ctr      <= 4'd0;
            tpe_ctr       <= 5'sd0;
            state         <= STATE_FINE;
            event_code    <= 3'b000;
            debug_fsm     <= 2'b00;
            baseline_out  <= 8'd128;
        end else if (ena) begin
            
            // Block 2: Innovation Correlation Monitor
            prev_sign <= sign_diff;
            if (sign_diff == prev_sign) begin
                if (corr_ctr < 4'd15) corr_ctr <= corr_ctr + 1;
            end else begin
                if (corr_ctr > 4'd0) corr_ctr <= corr_ctr - 1;
            end

            // Block 3: Temporal Persistence Engine
            if (is_outlier) begin
                if (sign_diff && !tpe_sat_pos) tpe_ctr <= tpe_ctr + 1;
                else if (!sign_diff && !tpe_sat_neg) tpe_ctr <= tpe_ctr - 1;
            end else begin
                tpe_ctr <= (tpe_ctr >>> 1);
            end

            // Block 4 & 1: Tri-Mode FSM & Baseline Update
            if (tpe_saturated || corr_ctr > 4'd12) begin
                state <= STATE_COARSE;
                baseline <= sign_diff ? (baseline + 8'd8) : (baseline - 8'd8);
            end 
            else if (is_outlier) begin
                state <= STATE_HOLD;
            end 
            else begin
                state <= STATE_FINE;
                if (abs_diff > 8'd0) begin
                    baseline <= sign_diff ? (baseline + 8'd1) : (baseline - 8'd1);
                end
                
                if (abs_diff > mad && mad < 8'd127) mad <= mad + 1;
                else if (abs_diff < mad && mad > 8'd1) mad <= mad - 1;
            end

            // Block 5: Semantic Event Classifier
            if (mad > 8'd64) begin
                event_code <= 3'b011;
            end else if (state == STATE_COARSE) begin
                event_code <= 3'b010;
            end else if (state == STATE_HOLD) begin
                event_code <= 3'b001;
            end else begin
                event_code <= 3'b000;
            end

            baseline_out <= baseline;
            debug_fsm    <= state;
        end
    end

endmodule
