#!/bin/bash
# run_display.sh - Khởi động display mode nhanh

source venv/bin/activate
export OPENBLAS_CORETYPE=ARMV8
export OMP_NUM_THREADS=4
python camera_pi_realtime.py
