"""Nhận diện bệnh từ ảnh tĩnh trên laptop và lưu toàn bộ kết quả.

Chạy không có tham số để mở hộp thoại chọn ảnh:
    python test_image.py

Hoặc truyền ảnh trực tiếp:
    python test_image.py "D:\\anh\\la-ca-chua.jpg"
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Giữ cấu hình Ultralytics trong dự án, tránh lỗi quyền truy cập AppData.
os.environ.setdefault(
    "YOLO_CONFIG_DIR",
    str(Path(__file__).resolve().parent / ".ultralytics"),
)

import cv2
from dotenv import load_dotenv
from ultralytics import YOLO

from vision.model_config import (
    CLASS_VI,
    canonical_label,
    class_names_from_model,
    resolve_model_path,
    validate_model_path,
)


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "results" / "image_detection"
DEFAULT_LAPTOP_MODEL = (
    BASE_DIR.parent
    / "yolo26n_tomato_6cls_complete"
    / "training_results"
    / "weights"
    / "best.pt"
)
SUPPORTED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def select_images() -> list[Path]:
    """Mở hộp thoại để chọn một hoặc nhiều ảnh trên laptop."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise RuntimeError(
            "Python chưa có Tkinter. Hãy truyền đường dẫn ảnh trên dòng lệnh."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askopenfilenames(
            title="Chọn ảnh lá cà chua để nhận diện",
            filetypes=[
                ("Ảnh", "*.jpg *.jpeg *.png *.bmp *.webp"),
                ("Tất cả tệp", "*.*"),
            ],
        )
    finally:
        root.destroy()
    return [Path(path) for path in selected]


def unique_run_dir(output_root: Path, image_path: Path) -> Path:
    """Tạo thư mục riêng cho từng ảnh và từng lần chạy."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_stem = "".join(
        char if char.isalnum() or char in ("-", "_") else "_"
        for char in image_path.stem
    ).strip("_") or "image"
    run_dir = output_root / f"{timestamp}_{safe_stem}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def resolve_laptop_model(cli_model: Path | None) -> Path:
    """Ưu tiên model PT cho laptop, vẫn cho phép cấu hình/ghi đè đường dẫn."""
    if cli_model is not None:
        return cli_model.expanduser().resolve()

    configured = os.getenv("LAPTOP_MODEL_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return (path if path.is_absolute() else BASE_DIR / path).resolve()

    if DEFAULT_LAPTOP_MODEL.is_file():
        return DEFAULT_LAPTOP_MODEL.resolve()
    return resolve_model_path(BASE_DIR)


def serialize_detections(result, names: dict[int, str]) -> list[dict]:
    detections = []
    if result.boxes is None:
        return detections

    for box in result.boxes:
        class_id = int(box.cls[0])
        class_name = canonical_label(names.get(class_id, str(class_id)))
        detections.append(
            {
                "class_id": class_id,
                "class_name": class_name,
                "class_name_vi": CLASS_VI.get(class_name, class_name),
                "confidence": round(float(box.conf[0]), 6),
                "box_xyxy": [round(float(value), 2) for value in box.xyxy[0].tolist()],
            }
        )
    return detections


def detect_image(
    model: YOLO,
    model_path: Path,
    image_path: Path,
    output_root: Path,
    confidence: float,
    image_size: int,
    show: bool = False,
) -> Path:
    if not image_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy ảnh: {image_path}")
    if image_path.suffix.lower() not in SUPPORTED_IMAGE_TYPES:
        raise ValueError(f"Định dạng ảnh không được hỗ trợ: {image_path.suffix}")

    run_dir = unique_run_dir(output_root, image_path)
    original_path = run_dir / f"original{image_path.suffix.lower()}"
    annotated_path = run_dir / "detected.jpg"
    json_path = run_dir / "detections.json"

    try:
        shutil.copy2(image_path, original_path)
        results = model.predict(
            source=str(image_path),
            conf=confidence,
            imgsz=image_size,
            verbose=False,
        )
        result = results[0]
        names = class_names_from_model(model)
        detections = serialize_detections(result, names)

        annotated = result.plot()
        if not cv2.imwrite(str(annotated_path), annotated):
            raise RuntimeError(f"Không thể lưu ảnh kết quả: {annotated_path}")

        summary = {
            "created_at": datetime.now().astimezone().isoformat(),
            "source_image": str(image_path.resolve()),
            "model": str(model_path),
            "confidence_threshold": confidence,
            "image_size": image_size,
            "detection_count": len(detections),
            "detections": detections,
            "speed_ms": {
                key: round(float(value), 3)
                for key, value in (result.speed or {}).items()
            },
            "files": {
                "original": original_path.name,
                "annotated": annotated_path.name,
            },
        }
        json_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"\nẢnh: {image_path.name}")
        if detections:
            for item in detections:
                print(
                    f"  - {item['class_name_vi']} ({item['class_name']}): "
                    f"{item['confidence']:.1%}"
                )
        else:
            print("  - Không phát hiện đối tượng vượt ngưỡng.")
        print(f"  Kết quả: {run_dir.resolve()}")

        if show:
            cv2.imshow("TomatoGuard - Ket qua nhan dien", annotated)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        return run_dir
    except Exception:
        # Không giữ lại một thư mục kết quả dở dang nếu suy luận/lưu tệp lỗi.
        shutil.rmtree(run_dir, ignore_errors=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chọn ảnh lá cà chua, chạy YOLO và lưu kết quả trên laptop."
    )
    parser.add_argument("images", nargs="*", type=Path, help="Đường dẫn ảnh cần nhận diện")
    parser.add_argument("--model", type=Path, help="Đường dẫn model .pt/.onnx hoặc thư mục NCNN")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Thư mục gốc lưu kết quả")
    parser.add_argument("--conf", type=float, default=None, help="Ngưỡng tin cậy, mặc định lấy MODEL_CONFIDENCE")
    parser.add_argument("--imgsz", type=int, default=None, help="Kích thước suy luận, mặc định lấy MODEL_IMGSZ")
    parser.add_argument("--show", action="store_true", help="Mở ảnh kết quả sau khi nhận diện")
    return parser.parse_args()


def main() -> int:
    load_dotenv(BASE_DIR / ".env")
    args = parse_args()
    used_file_picker = not args.images
    images = args.images or select_images()
    if not images:
        print("Bạn chưa chọn ảnh nào.")
        return 0

    model_path = resolve_laptop_model(args.model)
    model_format = validate_model_path(model_path)
    confidence = args.conf if args.conf is not None else float(os.getenv("MODEL_CONFIDENCE", "0.35"))
    image_size = args.imgsz if args.imgsz is not None else int(os.getenv("MODEL_IMGSZ", "640"))
    if not 0 < confidence <= 1:
        raise ValueError("--conf phải lớn hơn 0 và không vượt quá 1")
    if image_size <= 0:
        raise ValueError("--imgsz phải là số nguyên dương")

    output_root = args.output.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    print(f"Đang tải model {model_format.upper()}: {model_path}")
    model = YOLO(str(model_path))

    completed = 0
    for image_path in images:
        try:
            detect_image(
                model=model,
                model_path=model_path,
                image_path=image_path.expanduser().resolve(),
                output_root=output_root,
                confidence=confidence,
                image_size=image_size,
                show=args.show,
            )
            completed += 1
        except Exception as exc:
            print(f"Lỗi với ảnh {image_path}: {exc}", file=sys.stderr)

    print(f"\nHoàn tất {completed}/{len(images)} ảnh. Thư mục kết quả: {output_root}")
    if used_file_picker and completed and hasattr(os, "startfile"):
        try:
            os.startfile(str(output_root))
        except OSError:
            pass
    return 0 if completed == len(images) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        raise SystemExit(1)
