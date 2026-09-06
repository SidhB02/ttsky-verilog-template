///////////////////////////////////////////////////////////////////////////////
// dac_channel_regs.v
// Register file for 4 DAC channels. Each channel holds:
//   - 8-bit DAC setpoint code
//   - 1-bit lock-status flag
//   - 3-bit retry counter (max value 4, per spec's retry limit)
// Access is single-port: one channel selected at a time via ch_sel.
// Separate write-enables per field, so the FSM can update code, lock,
// and retry count independently at different points in the scan.
///////////////////////////////////////////////////////////////////////////////

module dac_channel_regs (
    input        clk,
    input        rst_n,

    input  [1:0] ch_sel,      // which channel (0-3) is being accessed

    // Write: DAC code
    input        code_wr_en,
    input  [7:0] code_in,

    // Write: lock flag
    input        lock_wr_en,
    input        lock_in,

    // Write: retry counter (increment or reset, selected channel)
    input        retry_inc,
    input        retry_rst,

    // Read: selected channel's current state (combinational)
    output [7:0] code_out,
    output       lock_out,
    output [2:0] retry_out
);

    reg [7:0] code_mem  [0:3];
    reg       lock_mem  [0:3];
    reg [2:0] retry_mem [0:3];

    integer i;

    // ------------------------------------------------------------
    // Writes: code, lock, retry - all gated on ch_sel, independent enables
    // ------------------------------------------------------------
    always @(posedge clk or negedge rst_n) begin
        if (~rst_n) begin
            for (i = 0; i < 4; i = i + 1) begin
                code_mem[i]  <= 8'h00;
                lock_mem[i]  <= 1'b0;
                retry_mem[i] <= 3'd0;
            end
        end
        else begin
            if (code_wr_en)
                code_mem[ch_sel] <= code_in;

            if (lock_wr_en)
                lock_mem[ch_sel] <= lock_in;

            // retry_inc and retry_rst should not both be asserted at once;
            // if they are, reset takes priority.
            if (retry_rst)
                retry_mem[ch_sel] <= 3'd0;
            else if (retry_inc)
                retry_mem[ch_sel] <= retry_mem[ch_sel] + 1'b1;
        end
    end

    // ------------------------------------------------------------
    // Reads: combinational, always reflects the currently selected channel
    // ------------------------------------------------------------
    assign code_out  = code_mem[ch_sel];
    assign lock_out  = lock_mem[ch_sel];
    assign retry_out = retry_mem[ch_sel];

endmodule // dac_channel_regs
