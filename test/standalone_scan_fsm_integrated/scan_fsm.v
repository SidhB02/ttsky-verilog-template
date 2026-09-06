///////////////////////////////////////////////////////////////////////////////
// scan_fsm.v (FULLY INTEGRATED)
// Instantiates dac_serializer + dac_channel_regs internally. Handles
// channel selection, code adjustment on retry, lock detection, and an
// initial PRELOAD sequence that loads config_loader's 4 initial codes
// into the register file before the first scan.
///////////////////////////////////////////////////////////////////////////////

module scan_fsm (
    input        clk,
    input        rst_n,

    input        start_scan,
    input  [1:0] comparator_status,   // 00=lock 01=too-low 10=too-high 11=reserved

    // config, from config_loader (top-level instantiates config_loader)
    input        preload_en,          // pulse: begin loading initial codes (= cfg_done)
    input  [7:0] init_code0,
    input  [7:0] init_code1,
    input  [7:0] init_code2,
    input  [7:0] init_code3,
    input  [7:0] step_size,

    // status / debug outputs
    output wire [3:0] state_out,
    output wire [1:0] current_channel,
    output reg         scan_complete,
    output wire        lock_flag,     // current channel's lock flag

    // serial DAC bus (from internal dac_serializer)
    output wire sclk,
    output wire mosi,
    output wire cs_n
);

    localparam PRELOAD      = 4'd9;
    localparam IDLE         = 4'd0;
    localparam SELECT_CH    = 4'd1;
    localparam LOAD_CODE    = 4'd2;
    localparam SETTLE       = 4'd3;
    localparam SAMPLE       = 4'd4;
    localparam LOCK_CHECK   = 4'd5;
    localparam ADJUST_CODE  = 4'd6;
    localparam NEXT_CHANNEL = 4'd7;
    localparam DONE         = 4'd8;

    reg [3:0] state, next_state;
    reg [1:0] ch_count;
    reg [1:0] preload_count;
    reg       preloading;   // latched: true from the pulse until all 4 channels written

    localparam SETTLE_CYCLES = 4;
    reg [3:0] settle_count;

    wire last_channel = (ch_count == 2'd3);
    assign current_channel = ch_count;
    assign state_out = state;

    // ------------------------------------------------------------
    // dac_channel_regs instance
    // ------------------------------------------------------------
    wire [7:0] reg_code_out;
    wire       reg_lock_out;
    wire [2:0] reg_retry_out;

    reg  [1:0] ch_sel_mux;
    reg        code_wr_en;
    reg  [7:0] code_wr_data;
    reg        lock_wr_en;
    reg        retry_inc;
    reg        retry_rst;

    assign lock_flag = reg_lock_out;

    dac_channel_regs regs_inst (
        .clk        (clk),
        .rst_n      (rst_n),
        .ch_sel     (ch_sel_mux),
        .code_wr_en (code_wr_en),
        .code_in    (code_wr_data),
        .lock_wr_en (lock_wr_en),
        .lock_in    (1'b1),
        .retry_inc  (retry_inc),
        .retry_rst  (retry_rst),
        .code_out   (reg_code_out),
        .lock_out   (reg_lock_out),
        .retry_out  (reg_retry_out)
    );

    wire retry_limit_reached = (reg_retry_out >= 3'd4);

    // ------------------------------------------------------------
    // dac_serializer instance
    // ------------------------------------------------------------
    wire ser_ready, ser_done;
    wire ser_start;

    dac_serializer ser_inst (
        .clk      (clk),
        .rst_n    (rst_n),
        .data_in  (reg_code_out),
        .start    (ser_start),
        .ready    (ser_ready),
        .done     (ser_done),
        .sclk     (sclk),
        .mosi     (mosi),
        .cs_n     (cs_n)
    );

    // ------------------------------------------------------------
    // ch_sel mux: PRELOAD uses preload_count, normal scan uses ch_count
    // ------------------------------------------------------------
    always @(*) begin
        ch_sel_mux = (state == PRELOAD) ? preload_count : ch_count;
    end

    // ------------------------------------------------------------
    // Adjusted code compute (combinational)
    // ------------------------------------------------------------
    reg [7:0] adjusted_code;
    always @(*) begin
        if (comparator_status == 2'b01) begin   // too-low -> increase
            adjusted_code = (reg_code_out > (8'hFF - step_size)) ? 8'hFF : (reg_code_out + step_size);
        end
        else begin                              // too-high -> decrease
            adjusted_code = (reg_code_out < step_size) ? 8'h00 : (reg_code_out - step_size);
        end
    end

    // ------------------------------------------------------------
    // Preload init-code mux
    // ------------------------------------------------------------
    reg [7:0] preload_code;
    always @(*) begin
        case (preload_count)
            2'd0: preload_code = init_code0;
            2'd1: preload_code = init_code1;
            2'd2: preload_code = init_code2;
            default: preload_code = init_code3;
        endcase
    end

    // ------------------------------------------------------------
    // State register
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n)
            state <= PRELOAD;
        else
            state <= next_state;
    end

    // ------------------------------------------------------------
    // Next-state logic
    // ------------------------------------------------------------
    wire entering_lock   = (state == LOCK_CHECK) && (comparator_status == 2'b00);
    wire entering_adjust = (state == LOCK_CHECK) && (comparator_status != 2'b00) && (~retry_limit_reached);
    wire entering_giveup = (state == LOCK_CHECK) && (comparator_status != 2'b00) && retry_limit_reached;

    always @(*) begin
        next_state = state;

        case (state)
            PRELOAD: begin
                if (preloading && preload_count == 2'd3)
                    next_state = IDLE;
            end

            IDLE: begin
                if (start_scan)
                    next_state = SELECT_CH;
            end

            SELECT_CH: begin
                next_state = LOAD_CODE;
            end

            LOAD_CODE: begin
                if (ser_done)
                    next_state = SETTLE;
            end

            SETTLE: begin
                if (settle_count == SETTLE_CYCLES - 1)
                    next_state = SAMPLE;
            end

            SAMPLE: begin
                next_state = LOCK_CHECK;
            end

            LOCK_CHECK: begin
                if (entering_lock)
                    next_state = NEXT_CHANNEL;
                else if (entering_giveup)
                    next_state = NEXT_CHANNEL;
                else
                    next_state = ADJUST_CODE;
            end

            ADJUST_CODE: begin
                next_state = LOAD_CODE;
            end

            NEXT_CHANNEL: begin
                if (last_channel)
                    next_state = DONE;
                else
                    next_state = SELECT_CH;
            end

            DONE: begin
                next_state = IDLE;
            end

            default: next_state = IDLE;
        endcase
    end

    // ------------------------------------------------------------
    // Preload counter
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            preload_count <= 2'd0;
            preloading    <= 1'b0;
        end
        else if (state == PRELOAD) begin
            if (preload_en && !preloading) begin
                // latch the pulse, this cycle writes channel 0
                preloading    <= 1'b1;
            end
            else if (preloading && preload_count != 2'd3) begin
                preload_count <= preload_count + 1'b1;
            end
        end
        else begin
            // leaving PRELOAD (state == IDLE now): clear for next time
            preloading    <= 1'b0;
            preload_count <= 2'd0;
        end
    end

    // ------------------------------------------------------------
    // Channel counter
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n)
            ch_count <= 2'd0;
        else if (state == NEXT_CHANNEL && next_state == SELECT_CH)
            ch_count <= ch_count + 1'b1;
        else if (state == DONE)
            ch_count <= 2'd0;
    end

    // ------------------------------------------------------------
    // Settle counter
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n)
            settle_count <= 4'd0;
        else if (state == SETTLE)
            settle_count <= settle_count + 1'b1;
        else
            settle_count <= 4'd0;
    end

    // ------------------------------------------------------------
    // Register-file write control
    // ------------------------------------------------------------
    always @(*) begin
        code_wr_en   = 1'b0;
        code_wr_data = 8'h00;
        lock_wr_en   = 1'b0;
        retry_inc    = 1'b0;
        retry_rst    = 1'b0;

        if (state == PRELOAD && preloading) begin
            code_wr_en   = 1'b1;
            code_wr_data = preload_code;
        end
        else if (state == SELECT_CH) begin
            retry_rst = 1'b1;
        end
        else if (entering_lock) begin
            lock_wr_en = 1'b1;
        end
        else if (entering_adjust) begin
            code_wr_en   = 1'b1;
            code_wr_data = adjusted_code;
            retry_inc    = 1'b1;
        end
    end

    // ------------------------------------------------------------
    // Serializer start pulse: fires once, on entry into LOAD_CODE
    // ------------------------------------------------------------
    reg prev_state_ss;
    assign ser_start = (state == LOAD_CODE) && (prev_state_ss != LOAD_CODE);

    always @(posedge clk or negedge rst_n) begin
        if (~rst_n)
            prev_state_ss <= PRELOAD;
        else
            prev_state_ss <= state;
    end

    // ------------------------------------------------------------
    // scan_complete pulse
    // ------------------------------------------------------------
    reg [3:0] prev_state;
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            prev_state    <= PRELOAD;
            scan_complete <= 1'b0;
        end
        else begin
            prev_state    <= state;
            scan_complete <= (state == DONE) && (prev_state != DONE);
        end
    end

endmodule // scan_fsm
