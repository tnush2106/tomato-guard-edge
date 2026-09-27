#!/usr/bin/env python3
"""Export a trained Ultralytics .pt checkpoint to an NCNN model directory."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Export YOLO checkpoint to NCNN")
    parser.add_argument("checkpoint", type=Path, help="Path to the trained best.pt")
    parser.add_argument("--imgsz", type=int, default=640, help="Fixed inference size")
    parser.add_argument("--fp32", action="store_true",
                        help="Keep FP32 weights instead of the Pi-friendly FP16 export")
    args = parser.parse_args()
    if not args.checkpoint.is_file():
        parser.error(f"checkpoint does not exist: {args.checkpoint}")
    if args.imgsz <= 0 or args.imgsz % 32:
        parser.error("--imgsz must be a positive multiple of 32")

    from ultralytics import YOLO

    export_args = {"format": "ncnn", "imgsz": args.imgsz, "batch": 1, "device": "cpu"}
    if not args.fp32:
        export_args["quantize"] = 16
    output = YOLO(str(args.checkpoint)).export(**export_args)
    print(f"NCNN model exported to: {output}")


if __name__ == "__main__":
    main()
