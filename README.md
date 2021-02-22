[![QUARTIQ Matrix Chat](https://img.shields.io/matrix/quartiq:matrix.org)](https://matrix.to/#/#quartiq:matrix.org)

# Phaser gateware

This repository contains the gateware for the Phaser 4 channel 1 GS/s DAC arbitrary waveform generator.

Funded by [Oxford](https://github.com/OxfordIonTrapGroup), [Oregon](https://github.com/OregonIons), [MITLL](https://www.ll.mit.edu/biographies/jeremy-m-sage), [QUARTIQ](https://github.com/quartiq).

This software is licenses under the GNU General Public License version 3 (GPL-3) or
later.

## Hardware

The hardware design repository is over at [Sinara](https://github.com/sinara-hw/Phaser).

## DSP designs

[NBViewer link](https://nbviewer.jupyter.org/github/quartiq/phaser/tree/master/)

* [filter](https://nbviewer.jupyter.org/github/quartiq/phaser/blob/master/filter.ipynb):
  ideas and sketches for a 1/10 (samples per clock cycle) to 2/1 interpolator
  cascade, analysis of other interpolator approaches, comparison of
  CIC/HBF/FIR, CIC droop compensation filter
* [cic](https://nbviewer.jupyter.org/github/quartiq/phaser/blob/master/cic.ipynb): ideas for CIC implementations and tests of interpolation modes

## Getting started

### Loading bitstreams

Precompiled bitstreams are available under [releases](https://github.com/quartiq/phaser/releases).

With vivado and a vivado-compatible JTAG dongle, to load (volatile) a bitstream onto the FPGA, use:

`vivado -mode batch -source load.tcl -tclargs build/phaser.bit`

To flash it, use:

`vivado -mode batch -source flash.tcl -tclargs build/phaser.bit`

With openocd and a JTAG dongle that fits the connector and has openocd support it
should also be possible to load and flash using the `xc7a` support and the `jtagspi` proxy bitstreams.
