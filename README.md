![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Flux-Bias Sequencer

A digital control sequencer for a cryo-CMOS qubit flux-bias controller, built for [Tiny Tapeout](https://tinytapeout.com).

- [Read the full documentation for this project](docs/info.md)

## What it does

The Flux-Bias Sequencer cycles through 4 independent channels, serially shifting an 8-bit DAC setpoint code out to each one over a shared 3-wire bus (SCLK/MOSI/CS), and reads back a 2-bit comparator status to check whether that channel's output landed within a target lock window. If not, the code is adjusted up or down by a configurable step size and retried, up to 4 times per channel, before the sequencer gives up on that channel and moves on so a single misbehaving channel can never stall the whole scan.

The design is built from four cooperating modules:

- **dac_serializer** - shifts an 8-bit code out MSB-first over SCLK/MOSI/CS
- **dac_channel_regs** - a 4-entry register file holding each channel's code, lock flag, and retry count
- **config_loader** - loads the 4 initial codes and step size in serially before the first scan
- **scan_fsm** - the top-level control FSM tying the above together

See [docs/info.md](docs/info.md) for the full pin mapping, state machine diagram description, and verification details.

## How to test

```
cd test
pip install -r requirements.txt
make
```

This runs the full top-level cocotb test suite against the real chip pins, covering config load, a full 4-channel scan, a retry scenario, a channel that never locks (confirming the sequencer doesn't stall), and reset mid-scan. Each of the four sub-modules also has its own standalone test suite under `test/`.

## Authors

Siddharth Bhat and Soham Bhattacharya

## What is Tiny Tapeout?

Tiny Tapeout is an educational project that aims to make it easier and cheaper than ever to get your digital and analog designs manufactured on a real chip.

To learn more and get started, visit https://tinytapeout.com.

## Resources

- [FAQ](https://tinytapeout.com/faq/)
- [Digital design lessons](https://tinytapeout.com/digital_design/)
- [Learn how semiconductors work](https://tinytapeout.com/siliwiz/)
- [Join the community](https://tinytapeout.com/discord)
- [Build your design locally](https://www.tinytapeout.com/guides/local-hardening/)

## Submission

This project is being submitted to the [Tiny Tapeout shuttle](https://app.tinytapeout.com/).
