import tempfile
import types
import unittest
from pathlib import Path

from vision.model_config import (
    canonical_label, class_names_from_model, validate_class_schema, validate_model_path,
)


class ModelConfigTests(unittest.TestCase):
    def test_ncnn_directory_requires_matching_param_and_bin(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            (model_dir / "model.ncnn.param").write_text("7767517\n", encoding="ascii")
            with self.assertRaises(FileNotFoundError):
                validate_model_path(model_dir)
            (model_dir / "model.ncnn.bin").write_bytes(b"ncnn")
            self.assertEqual(validate_model_path(model_dir), "ncnn")

    def test_six_class_training_order_is_preserved_and_validated(self):
        model = types.SimpleNamespace(names={
            0: "Late blight", 1: "Leaf miner", 2: "Magnesium deficiency",
            3: "Nitrogen deficiency", 4: "Potassium deficiency",
            5: "Spotted wilt virus",
        })
        names = validate_class_schema(class_names_from_model(model))
        self.assertEqual(names[0], "Late_Blight")
        self.assertEqual(names[1], "Leaf_Miner")
        self.assertEqual(names[4], "Potassium_Deficiency")

    def test_old_or_reordered_model_is_rejected(self):
        old_model = types.SimpleNamespace(names={0: "Early blight", 1: "Healthy"})
        with self.assertRaisesRegex(ValueError, "tomato_6cls.yaml"):
            validate_class_schema(class_names_from_model(old_model))

    def test_label_aliases_accept_spaces_underscores_and_training_typo(self):
        self.assertEqual(canonical_label("Late_blight"), "Late_Blight")
        self.assertEqual(canonical_label("Pottassium Deficiency"), "Potassium_Deficiency")


if __name__ == "__main__":
    unittest.main()
