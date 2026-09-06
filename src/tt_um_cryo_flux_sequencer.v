/*
 * Flux-Bias Sequencer - top-level wrapper (FINAL)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Pin mapping (per project spec):
 *   ui_in[1:0]  = comparator feedback (00=lock 01=too-low 10=too-high 11=reserved)
 *   ui_in[2]    = external start-scan trigger
 *   uo_out[0]   = SCLK
 *   uo_out[1]   = MOSI
 *   uo_out[2]   = CS (active-low, from dac_serializer's cs_n)
 *   uo_out[4:3] = current channel ID (0-3)
 *   uo_out[5]   = scan_complete pulse
 *   uo_out[6]   = current channel's lock flag
 *   uio[1:0]    = config data serial input
 *   uio[2]      = config_load enable
 */
`default_nettype none

module tt_um_cryo_flux_sequencer (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    // ------------------------------------------------------------
    // config_loader: shifts in initial codes / step size over uio[1:0],
    // gated by uio[2]. cfg_done feeds scan_fsm's preload_en.
    // ------------------------------------------------------------
    wire        cfg_done;
    wire [7:0]  cfg_init_code0, cfg_init_code1, cfg_init_code2, cfg_init_code3;
    wire [7:0]  cfg_lock_window;   // currently unused downstream, reserved for future use
    wire [7:0]  cfg_step_size;

    config_loader cfg_inst (
        .clk         (clk),
        .rst_n       (rst_n),
        .cfg_data    (uio_in[1:0]),
        .cfg_load_en (uio_in[2]),
        .cfg_done    (cfg_done),
        .init_code0  (cfg_init_code0),
        .init_code1  (cfg_init_code1),
        .init_code2  (cfg_init_code2),
        .init_code3  (cfg_init_code3),
        .lock_window (cfg_lock_window),
        .step_size   (cfg_step_size)
    );

    // ------------------------------------------------------------
    // scan_fsm: instantiates dac_serializer + dac_channel_regs internally
    // ------------------------------------------------------------
    wire [3:0] fsm_state_out;       // debug only, not routed to pins
    wire [1:0] fsm_current_channel;
    wire       fsm_scan_complete;
    wire       fsm_lock_flag;
    wire       fsm_sclk, fsm_mosi, fsm_cs_n;

    scan_fsm fsm_inst (
        .clk               (clk),
        .rst_n             (rst_n),
        .start_scan        (ui_in[2]),
        .comparator_status (ui_in[1:0]),
        .preload_en        (cfg_done),
        .init_code0        (cfg_init_code0),
        .init_code1        (cfg_init_code1),
        .init_code2        (cfg_init_code2),
        .init_code3        (cfg_init_code3),
        .step_size         (cfg_step_size),
        .state_out         (fsm_state_out),
        .current_channel   (fsm_current_channel),
        .scan_complete     (fsm_scan_complete),
        .lock_flag         (fsm_lock_flag),
        .sclk              (fsm_sclk),
        .mosi              (fsm_mosi),
        .cs_n              (fsm_cs_n)
    );

    // ------------------------------------------------------------
    // Output pin mapping
    // ------------------------------------------------------------
    assign uo_out[0]   = fsm_sclk;
    assign uo_out[1]   = fsm_mosi;
    assign uo_out[2]   = fsm_cs_n;
    assign uo_out[4:3] = fsm_current_channel;
    assign uo_out[5]   = fsm_scan_complete;
    assign uo_out[6]   = fsm_lock_flag;
    assign uo_out[7]   = 1'b0;   // unused

    // uio pins are inputs only in this design (config load bus)
    assign uio_out = 8'h00;
    assign uio_oe  = 8'h00;

    // List all unused inputs/signals to prevent warnings
    wire _unused = &{ena, ui_in[7:3], uio_in[7:3], cfg_lock_window, fsm_state_out, 1'b0};

endmodule
