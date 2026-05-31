#!/bin/bash
# run_web.sh - Khởi động web app nhanh

source venv/bin/activate
export OPENBLAS_CORETYPE=ARMV8
export OMP_NUM_THREADS=4
python app_pi_realtime.py
