"""NCNN model discovery and label normalization shared by both Pi entry points."""

import os
from pathlib import Path


DEFAULT_MODEL_RELATIVE = Path("model/tomato_6cls_ncnn_model")
DEFAULT_CLASS_NAMES = {
    0: "Late_Blight",
    1: "Leaf_Miner",
    2: "Magnesium_Deficiency",
    3: "Nitrogen_Deficiency",
    4: "Potassium_Deficiency",
    5: "Spotted_Wilt_Virus",
}

CLASS_VI = {
    "Late_Blight": "Bệnh mốc sương",
    "Leaf_Miner": "Sâu vẽ bùa",
    "Magnesium_Deficiency": "Thiếu Magiê",
    "Nitrogen_Deficiency": "Thiếu Nitơ",
    "Potassium_Deficiency": "Thiếu Kali",
    "Spotted_Wilt_Virus": "Virus đốm héo",
}

COLORS = [
    (192, 57, 43), (243, 156, 18), (39, 174, 96),
    (46, 204, 113), (230, 126, 34), (155, 89, 182),
]

_ALIASES = {
    "late blight": "Late_Blight",
    "leaf miner": "Leaf_Miner",
    "magnesium deficiency": "Magnesium_Deficiency",
    "nitrogen deficiency": "Nitrogen_Deficiency",
    "potassium deficiency": "Potassium_Deficiency",
    "pottassium deficiency": "Potassium_Deficiency",
    "spotted wilt virus": "Spotted_Wilt_Virus",
}


def canonical_label(value):
    text = str(value).strip()
    key = " ".join(text.replace("_", " ").replace("-", " ").lower().split())
    return _ALIASES.get(key, text.replace(" ", "_"))


def resolve_model_path(base_dir):
    configured = Path(os.getenv("MODEL_PATH", str(DEFAULT_MODEL_RELATIVE))).expanduser()
    if not configured.is_absolute():
        configured = Path(base_dir) / configured
    return configured.resolve()


def validate_model_path(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy model: {path}")
    if path.is_dir():
        params = sorted(path.glob("*.param"))
        if not params:
            raise FileNotFoundError(f"Thư mục NCNN không có file .param: {path}")
        if not any(param.with_suffix(".bin").is_file() for param in params):
            raise FileNotFoundError(f"Thư mục NCNN thiếu cặp .param/.bin: {path}")
        return "ncnn"
    if path.suffix.lower() in {".onnx", ".pt", ".torchscript"}:
        return path.suffix.lower().lstrip(".")
    raise ValueError(f"Định dạng model không được hỗ trợ: {path}")


def class_names_from_model(model):
    raw_names = getattr(model, "names", None)
    if isinstance(raw_names, (list, tuple)):
        raw_names = dict(enumerate(raw_names))
    if not isinstance(raw_names, dict) or not raw_names:
        raise ValueError("Model không cung cấp metadata tên lớp")
    names = {}
    for key, value in raw_names.items():
        try:
            names[int(key)] = canonical_label(value)
        except (TypeError, ValueError):
            continue
    if not names:
        raise ValueError("Metadata tên lớp của model không hợp lệ")
    return names


def validate_class_schema(names):
    names = dict(names)
    if names != DEFAULT_CLASS_NAMES:
        expected = ", ".join(f"{index}:{name}" for index, name in DEFAULT_CLASS_NAMES.items())
        actual = ", ".join(f"{index}:{name}" for index, name in sorted(names.items()))
        raise ValueError(
            "Schema lớp của model không khớp tomato_6cls.yaml. "
            f"Cần [{expected}], nhận [{actual}]"
        )
    return names
