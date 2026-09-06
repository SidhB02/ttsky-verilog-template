///////////////////////////////////////////////////////////////////////////////
// scan_fsm.v  (adding internal channel counter)
// Main scan FSM: cycles through 4 channels, drives serial load per channel,
// waits a settle period, samples comparator feedback, locks or retries.
// last_channel is now derived internally from a channel counter instead of
// being an external test input. Other datapath signals (serializer_done,
// comparator_status, retry_limit_reached) are still placeholders, wired
// for real in a later step.
///////////////////////////////////////////////////////////////////////////////

module scan_fsm (
    input        clk,
    input        rst_n,

    input        start_scan,          // external trigger: begin a 4-ch scan

    // --- placeholder datapath signals (real wiring added later) ---
    input        serializer_done,     // dac_serializer finished shifting
    input  [1:0] comparator_status,   // 00=lock 01=too-low 10=too-high 11=reserved
    input        retry_limit_reached, // current channel hit max retries

    // --- outputs for observation / driving datapath later ---
    output wire [3:0] state_out,        // current state, exposed for test/debug
    output wire [1:0] current_channel,  // which of the 4 channels is active now
    output reg        scan_complete,    // pulses in DONE
    output reg        load_code_pulse,  // pulses once per entry into LOAD_CODE (start serializer)
    output reg        adjust_pulse,     // pulses once per entry into ADJUST_CODE
    output reg        advance_channel   // pulses once per entry into NEXT_CHANNEL
);

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

    localparam SETTLE_CYCLES = 4;   // fixed settle wait, placeholder value
    reg [3:0] settle_count;

    reg [1:0] ch_count;     // 0..3, tracks which channel we're on
    wire      last_channel; // derived: are we on channel 3?

    assign last_channel   = (ch_count == 2'd3);
    assign current_channel = ch_count;

    // ------------------------------------------------------------
    // State register
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n)
            state <= IDLE;
        else
            state <= next_state;
    end

    // ------------------------------------------------------------
    // Next-state logic (combinational)
    // ------------------------------------------------------------
    always @(*) begin
        next_state = state;   // default: stay put

        case (state)
            IDLE: begin
                if (start_scan)
                    next_state = SELECT_CH;
            end

            SELECT_CH: begin
                next_state = LOAD_CODE;
            end

            LOAD_CODE: begin
                if (serializer_done)
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
                if (comparator_status == 2'b00) begin
                    // locked -> move to next channel
                    next_state = NEXT_CHANNEL;
                end
                else begin
                    // too-low or too-high
                    if (retry_limit_reached)
                        next_state = NEXT_CHANNEL;   // give up, move on anyway
                    else
                        next_state = ADJUST_CODE;
                end
            end

            ADJUST_CODE: begin
                next_state = LOAD_CODE;   // retry with adjusted code
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
    // Channel counter: increments on entry into NEXT_CHANNEL,
    // resets to 0 on entry into DONE (ready for the next external trigger)
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
    // Settle counter (only counts while in SETTLE)
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
    // Output pulses (Moore-style: derived from state, one cycle wide
    // by comparing current state vs previous state transition edges)
    // ------------------------------------------------------------
    reg [3:0] prev_state;

    always @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            prev_state      <= IDLE;
            scan_complete   <= 1'b0;
            load_code_pulse <= 1'b0;
            adjust_pulse    <= 1'b0;
            advance_channel <= 1'b0;
        end
        else begin
            prev_state <= state;

            // pulse = 1 cycle wide, fires on the cycle we *enter* the state
            scan_complete   <= (state == DONE)         && (prev_state != DONE);
            load_code_pulse <= (state == LOAD_CODE)    && (prev_state != LOAD_CODE);
            adjust_pulse    <= (state == ADJUST_CODE)  && (prev_state != ADJUST_CODE);
            advance_channel <= (state == NEXT_CHANNEL) && (prev_state != NEXT_CHANNEL);
        end
    end

    assign state_out = state;

endmodule // scan_fsm
