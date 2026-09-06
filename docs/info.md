## How it works

The Flux-Bias Sequencer is a digital control sequencer for a cryo-CMOS qubit flux-bias controller. It repeatedly cycles through 4 independent channels, serially shifting an 8-bit DAC setpoint code out to each one over a shared 3-wire serial bus (SCLK/MOSI/CS), and reads back a 2-bit comparator status to determine whether that channel's output landed within a target lock window.

The design is split into four cooperating modules:

- **dac_serializer** - shifts an 8-bit code out MSB-first over SCLK/MOSI, holding CS low for the duration of the transfer, and signals `done` once complete.
- **dac_channel_regs** - a 4-entry register file, one entry per channel, each holding an 8-bit DAC code, a 1-bit lock flag, and a 3-bit retry counter.
- **config_loader** - shifts in a 48-bit configuration payload (4 initial channel codes, a lock-window width, and a step size) over a 2-bit serial bus before the first scan begins.
- **scan_fsm** - the top-level control FSM. It instantiates the serializer and register file internally, and walks through the states `PRELOAD -> IDLE -> SELECT_CH -> LOAD_CODE -> SETTLE -> SAMPLE -> LOCK_CHECK -> {ADJUST_CODE -> LOAD_CODE | NEXT_CHANNEL} -> ... -> DONE -> IDLE`.

On `LOCK_CHECK`, a comparator status of `00` locks the channel and advances to the next one. A status of `01` (too-low) or `10` (too-high) triggers a code adjustment (up or down by the configured step size, clamped to 0x00-0xFF) and a retry, up to 4 retries per channel. If a channel never locks within the retry limit, the sequencer gives up on that channel and moves on regardless, so a single misbehaving channel cannot stall the whole scan. Once all 4 channels have been processed, `scan_complete` pulses and the FSM returns to `IDLE`, waiting for the next external trigger.

Pin mapping:

- `ui_in[1:0]`: comparator feedback (00=lock, 01=too-low, 10=too-high, 11=reserved)
- `ui_in[2]`: external start-scan trigger (pulse to begin a full 4-channel scan)
- `uo_out[0]`: SCLK
- `uo_out[1]`: MOSI
- `uo_out[2]`: CS (active-low)
- `uo_out[4:3]`: currently active channel ID (0-3)
- `uo_out[5]`: scan_complete pulse
- `uo_out[6]`: current channel's lock flag
- `uio[1:0]`: serial configuration data input
- `uio[2]`: configuration-load enable

## How to test

The design has been verified in simulation using cocotb, with tests at both the individual-module level and the fully integrated top-level chip interface.

To run the top-level test suite:

```
cd test
pip install -r requirements.txt
make
```

This runs four scenarios against the real chip pins (`ui_in`, `uo_out`, `uio_in`):

1. **Config load and full scan** - loads 4 initial codes via `uio`, triggers a scan via `ui_in[2]`, and verifies all 4 channels lock and `scan_complete` pulses with the correct final lock status on `uo_out[6]`.
2. **Scan with one retry** - forces one channel to report "too-low" once, verifying the code is adjusted by the configured step size and the channel locks on the second attempt.
3. **Never-locks does not stall** - forces one channel to always report "too-high", verifying the sequencer retries exactly 4 times before giving up on that channel and continuing the scan to completion rather than stalling.
4. **Reset mid-scan** - asserts reset partway through an active scan and verifies the FSM immediately returns to a clean `PRELOAD` state with the channel counter cleared, rather than getting stuck.

Each of the four sub-modules (`dac_serializer`, `dac_channel_regs`, `config_loader`, `scan_fsm`) also has its own standalone cocotb test suite, runnable independently from its own folder under `test/`, covering channel isolation, register reset behavior, configuration-load correctness, and FSM state-transition correctness in more detail than the top-level tests alone.
