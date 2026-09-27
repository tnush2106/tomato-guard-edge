"""Exercise the real Flask app without loading camera/ML packages or API clients."""

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash


class AppHatIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_file = Path(__file__).resolve().parents[1] / "app_pi_realtime.py"
        spec = importlib.util.spec_from_file_location("app_under_test", app_file)
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"cv2": types.ModuleType("cv2"), "numpy": types.ModuleType("numpy")}), \
                patch.dict(os.environ, {"HAT_ENABLED": "0", "HAT_OFFLINE_SIMULATION": "0",
                                     "DASHBOARD_USERNAME": "tester",
                                     "DASHBOARD_PASSWORD_HASH": generate_password_hash("a-test-password-123"),
                                     "FLASK_SECRET_KEY": "test-only-secret-key-" * 3,
                                     "DASHBOARD_COOKIE_SECURE": "0"}):
            spec.loader.exec_module(cls.module)
        cls.http = cls.module.app.test_client()
        cls.http.get("/login")
        with cls.http.session_transaction() as session:
            login_token = session["csrf_token"]
        result = cls.http.post("/login", data={"username": "tester", "password": "a-test-password-123",
                                                "csrf_token": login_token})
        assert result.status_code == 302
        with cls.http.session_transaction() as session:
            cls.csrf_token = session["csrf_token"]

    def test_login_guards_dashboard_api_and_mutations(self):
        anonymous = self.module.app.test_client()
        self.assertEqual(anonymous.get("/").status_code, 302)
        self.assertEqual(anonymous.get("/api/detections").status_code, 401)
        self.assertEqual(anonymous.get("/video").status_code, 302)
        self.assertEqual(anonymous.get("/healthz").json, {"ok": True})
        self.assertEqual(self.http.post("/api/relay", json={"relay": 1, "state": True}).status_code, 403)

        anonymous.get("/login")
        with anonymous.session_transaction() as login_session:
            token = login_session["csrf_token"]
        wrong = anonymous.post("/login", data={"username": "tester", "password": "wrong",
                                               "csrf_token": token})
        self.assertEqual(wrong.status_code, 401)
        correct = anonymous.post("/login", data={"username": "tester", "password": "a-test-password-123",
                                                 "csrf_token": token})
        self.assertEqual(correct.status_code, 302)
        self.assertEqual(anonymous.get("/api/detections").status_code, 200)
        with anonymous.session_transaction() as logged_in:
            logout_token = logged_in["csrf_token"]
        self.assertEqual(anonymous.post("/logout", data={"csrf_token": logout_token}).status_code, 302)
        self.assertEqual(anonymous.get("/api/detections").status_code, 401)

    def test_new_dashboard_is_served(self):
        response = self.http.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"TomatoGuard", response.data)
        self.assertIn(b"/api/relay", response.data)

    def test_detection_endpoint_merges_unavailable_hat_without_mock_values(self):
        response = self.http.get("/api/detections")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["hat"]["connected"])
        self.assertFalse(response.json["camera_ok"])
        self.assertTrue(all(value is None for value in response.json["sensors"].values()))
        self.assertIn("timing", response.json)
        self.assertEqual(response.json["camera_width"], 640)
        self.assertEqual(response.json["model_name"], "tomato_6cls_ncnn_model")
        self.assertIn("model_format", response.json)
        self.assertEqual(response.json["model_classes"][0], "Late_Blight")
        self.assertEqual(len(response.json["model_classes"]), 6)

    def test_unavailable_hardware_does_not_return_success(self):
        response = self.http.post("/api/relay", json={"relay": 1, "state": True},
                                  headers={"X-CSRF-Token": self.csrf_token})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json["ok"])

    def test_chat_uses_server_hardware_observations_not_forged_browser_readings(self):
        graph = types.ModuleType("core.run_graph")
        calls = []

        def run_graph(**kwargs):
            calls.append(kwargs)
            return "test response", []

        graph.run_graph = run_graph
        with patch.dict(sys.modules, {"core.run_graph": graph}):
            response = self.http.post("/api/chat", json={
                "session_id": "hat-test", "message": "Độ ẩm hiện tại?",
                "sensors": {"humidity": 99},
                "report": {"hardware": {"sensors": {"humidity": 99}}},
            }, headers={"X-CSRF-Token": self.csrf_token})
        self.assertEqual(response.status_code, 200)
        self.assertIn('"humidity": null', calls[0]["system_context"])
        self.assertNotIn('"humidity": 99', calls[0]["system_context"])
        self.assertIn("cannot actuate", calls[0]["system_context"])


if __name__ == "__main__":
    unittest.main()
