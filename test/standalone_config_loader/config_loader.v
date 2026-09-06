///////////////////////////////////////////////////////////////////////////////
// config_loader.v
// Serially loads configuration before the first scan: 4 initial DAC codes
// (8 bits each), a lock-window width (8 bits), and a step size (8 bits).
// Total payload = 48 bits, shifted in 2 bits per clock cycle (24 cycles)
// over cfg_data[1:0], while cfg_load_en is held high.
///////////////////////////////////////////////////////////////////////////////

module config_loader (
    input        clk,
    input        rst_n,

    input  [1:0] cfg_data,     // 2-bit serial config input
    input        cfg_load_en,  // hold high while shifting in config

    output reg   cfg_done,     // 1-cycle pulse when all 48 bits loaded

    output [7:0] init_code0,
    output [7:0] init_code1,
    output [7:0] init_code2,
    output [7:0] init_code3,
    output [7:0] lock_window,
    output [7:0] step_size
);

    localparam TOTAL_BITS  = 48;
    localparam TOTAL_STEPS = TOTAL_BITS / 2;   // 24 cycles at 2 bits/cycle

    reg [47:0] shift_reg;
    reg [4:0]  step_count;      // counts 0..24
    reg        loading;

    // ------------------------------------------------------------
    // Shift-in logic: MSB-first, 2 bits per cycle while cfg_load_en high
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            shift_reg  <= 48'h0;
            step_count <= 5'd0;
            loading    <= 1'b0;
            cfg_done   <= 1'b0;
        end
        else begin
            cfg_done <= 1'b0;

            if (cfg_load_en && !loading && step_count == 0) begin
                // first cycle of a load: capture first 2 bits, start counting
                loading   <= 1'b1;
                shift_reg <= {shift_reg[45:0], cfg_data};
                step_count <= step_count + 1'b1;
            end
            else if (loading && cfg_load_en) begin
                shift_reg  <= {shift_reg[45:0], cfg_data};
                step_count <= step_count + 1'b1;

                if (step_count == TOTAL_STEPS - 1) begin
                    // this cycle shifts in the final 2 bits
                    loading    <= 1'b0;
                    step_count <= 5'd0;
                    cfg_done   <= 1'b1;
                end
            end
            else if (loading && !cfg_load_en) begin
                // load aborted early; reset state, don't pulse done
                loading    <= 1'b0;
                step_count <= 5'd0;
            end
        end
    end

    // ------------------------------------------------------------
    // Field extraction: fixed positions within the 48-bit payload.
    // Load order (first shifted = most-significant / first field):
    //   [47:40]=init_code0 [39:32]=init_code1 [31:24]=init_code2
    //   [23:16]=init_code3 [15:8]=lock_window  [7:0]=step_size
    // ------------------------------------------------------------
    assign init_code0  = shift_reg[47:40];
    assign init_code1  = shift_reg[39:32];
    assign init_code2  = shift_reg[31:24];
    assign init_code3  = shift_reg[23:16];
    assign lock_window = shift_reg[15:8];
    assign step_size   = shift_reg[7:0];

endmodule // config_loader
