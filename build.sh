#!/bin/sh

set -eux

VIVADO_PREFIX=${VIVADO_PREFIX:-/opt/Xilinx/Vivado}
VIVADO_LATEST=$(ls $VIVADO_PREFIX | sort -n | tail -1)
VIVADO=${VIVADO:-$VIVADO_PREFIX/${VIVADO_LATEST:?}}

python3 -m venv --system-site-packages py

export PATH=$PATH:$PWD/py/bin:$VIVADO/bin

pip install -r requirements.txt

python -m pytest
python phaser.py

pip freeze > build/requirements.txt
tar czvf phaser.tar.gz \
	build/phaser.bit \
	build/requirements.txt \
	build/vivado.log \
	build/phaser_timing.rpt \
	build/phaser_utilization_place.rpt
