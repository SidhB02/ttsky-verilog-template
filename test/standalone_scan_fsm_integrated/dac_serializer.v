///////////////////////////////////////////////////////////////////////////////
// dac_serializer.v
// Shifts an 8-bit DAC code out serially (MSB-first) with SCLK/MOSI/CS.
// Rewritten to use a real shift register (fixes an off-by-one bit-skip bug
// found in the counter-indexed version during cocotb testing).
///////////////////////////////////////////////////////////////////////////////

module dac_serializer (
    input        clk,
    input        rst_n,       // active-low reset

    input  [7:0] data_in,     // 8-bit DAC code to shift out
    input        start,       // pulse: begin shifting out data_in
    output reg   ready,       // high when idle, ready for next code
    output reg   done,        // 1-cycle pulse when byte finished

    output reg   sclk,
    output       mosi,        // always = shift_reg[7], no extra pipeline delay
    output reg   cs_n         // active-low chip select
);

    localparam IDLE     = 1'b0;
    localparam TRANSFER = 1'b1;

    reg       sm_cs;
    reg [4:0] clk_edges_left;
    reg       trailing_edge;
    reg [7:0] shift_reg;

    assign mosi = shift_reg[7];   // MSB always visible on the wire

    // ------------------------------------------------------------
    // CS control state machine
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            sm_cs <= IDLE;
            cs_n  <= 1'b1;
        end
        else begin
            case (sm_cs)
                IDLE: begin
                    if (start && ready) begin
                        cs_n  <= 1'b0;
                        sm_cs <= TRANSFER;
                    end
                end
                TRANSFER: begin
                    if (done) begin
                        cs_n  <= 1'b1;
                        sm_cs <= IDLE;
                    end
                end
                default: begin
                    cs_n  <= 1'b1;
                    sm_cs <= IDLE;
                end
            endcase
        end
    end

    // ------------------------------------------------------------
    // SCLK generation, edge pulses, and done (from edge counter directly)
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            ready          <= 1'b1;
            clk_edges_left <= 5'd0;
            trailing_edge  <= 1'b0;
            sclk           <= 1'b0;
            done           <= 1'b0;
        end
        else begin
            trailing_edge <= 1'b0;
            done          <= 1'b0;

            if (start && ready) begin
                ready          <= 1'b0;
                shift_reg      <= data_in;
                clk_edges_left <= 5'd16;   // 8 bits x 2 edges/bit
            end
            else if (clk_edges_left > 0) begin
                sclk <= ~sclk;

                if (sclk == 1'b1)
                    trailing_edge <= 1'b1;   // about to go 1 -> 0

                if (clk_edges_left == 5'd1) begin
                    ready <= 1'b1;
                    done  <= 1'b1;   // last edge processed, pulse done
                end

                clk_edges_left <= clk_edges_left - 1'b1;
            end
        end
    end

    // ------------------------------------------------------------
    // Shift out MOSI: shift left on every trailing edge
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            shift_reg <= 8'h00;
        end
        else if (trailing_edge) begin
            shift_reg <= {shift_reg[6:0], 1'b0};
        end
    end

endmodule // dac_serializer
