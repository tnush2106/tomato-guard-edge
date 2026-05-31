#!/usr/bin/env python3
# app_pi_realtime.py
# Web Dashboard IoT - Tomato Disease Detector
# Chạy: python app_pi_realtime.py
# Truy cập: http://<pi-ip>:5000

from flask import Flask, Response, render_template, jsonify, request
import cv2
import numpy as np
import subprocess
import time
import threading
import os
import queue
from collections import deque

app = Flask(__name__)

# ── Fix ARM trước khi import ─────────────────────────────────
os.environ["OPENBLAS_CORETYPE"] = "ARMV8"
os.environ["OMP_NUM_THREADS"] = "4"

# ── Config tối ưu cho Pi 4 ───────────────────────────────────
MODEL_PATH = "model/yolo11n_tomato_best.onnx"
CONF_THRESH = 0.35
IMGSZ = 640
CAM_WIDTH = 640
CAM_HEIGHT = 480
CAM_FPS = 15
INFERENCE_FPS = 3

CLASS_NAMES = [
    "Early_blight", "Late_blight", "Leaf_Miner",
    "Magnesium_Deficiency", "Nitrogen_Deficiency",
    "Pottassium_Deficiency", "Spotted_Wilt_Virus"
]
CLASS_VI = {
    "Early_blight": "Bệnh đốm vòng",
    "Late_blight": "Bệnh mốc sương",
    "Leaf_Miner": "Sâu vẽ bùa",
    "Magnesium_Deficiency": "Thiếu Magiê",
    "Nitrogen_Deficiency": "Thiếu Nitơ",
    "Pottassium_Deficiency": "Thiếu Kali",
    "Spotted_Wilt_Virus": "Virus đốm héo",
}
DISEASE_INFO = {
    "Early_blight": {"severity": "🔴 Nghiêm trọng", "treatment": "Phun Mancozeb hoặc Chlorothalonil định kỳ 7-10 ngày, loại bỏ lá bệnh, luân canh cây trồng", "color": "#c0392b"},
    "Late_blight": {"severity": "🔴 Rất nghiêm trọng", "treatment": "Phun Metalaxyl + Mancozeb ngay, cắt bỏ toàn bộ lá nhiễm, cải thiện thông gió", "color": "#e74c3c"},
    "Leaf_Miner": {"severity": "⚠️ Trung bình", "treatment": "Phun Abamectin hoặc Cyromazine, loại bỏ lá bị hại nặng, sử dụng bẫy dính vàng", "color": "#f39c12"},
    "Magnesium_Deficiency": {"severity": "🟡 Nhẹ", "treatment": "Bón MgSO₄ (Epsom salt) qua lá hoặc gốc, bổ sung Dolomite, cân bằng pH đất 6.0-6.5", "color": "#27ae60"},
    "Nitrogen_Deficiency": {"severity": "🟡 Nhẹ", "treatment": "Bón phân đạm (Urea, NPK) kịp thời, bổ sung phân hữu cơ, tưới phân bón lá có chứa Nitơ", "color": "#2ecc71"},
    "Pottassium_Deficiency": {"severity": "⚠️ Trung bình", "treatment": "Bón KCl hoặc K₂SO₄ qua gốc, phun KNO₃ qua lá, bổ sung tro thực vật", "color": "#e67e22"},
    "Spotted_Wilt_Virus": {"severity": "🔴 Rất nghiêm trọng", "treatment": "Không có thuốc trị virus, nhổ bỏ cây bệnh tiêu hủy, diệt bọ trĩ bằng Spinosad", "color": "#c0392b"},
}
COLORS = [
    (231,76,60), (192,57,43), (243,156,18),
    (39,174,96), (46,204,113), (230,126,34), (155,89,182)
]

# ── Global state ──────────────────────────────────────────────
model = None
yolo_ok = False
yolo_error = ""
latest_detections = []
detection_lock = threading.Lock()
frame_queue = queue.Queue(maxsize=2)
start_time_global = time.time()

# ── Timing stats ──────────────────────────────────────────────
timing_stats = {
    'inference_ms': 0.0,
    'draw_ms': 0.0,
    'total_ms': 0.0,
    'fps_effective': 0.0,
}
timing_lock = threading.Lock()

# ── Chatbot Memory ────────────────────────────────────────────
CHAT_MEMORY = {}



class PiCamera:
    """Camera Module 3 với rpicam-vid - tối ưu cho real-time."""
    
    def __init__(self, width=640, height=480, fps=15):
        self.width = width
        self.height = height
        self.process = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        
        cmd = [
            'rpicam-vid', '-t', '0',
            '--width', str(width), '--height', str(height),
            '--framerate', str(fps),
            '--codec', 'mjpeg', '--inline', '-o', '-', '-n',
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=width * height * 3
            )
            self.running = True
            self.thread = threading.Thread(target=self._read_frames, daemon=True)
            self.thread.start()
            time.sleep(1.5)
            print("✅ Camera sẵn sàng")
        except Exception as e:
            print(f"❌ Camera lỗi: {e}")
    
    def _read_frames(self):
        buf = b''
        while self.running:
            try:
                chunk = self.process.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > 5 * 1024 * 1024:
                    buf = b''
                while True:
                    start = buf.find(b'\xff\xd8')
                    if start == -1:
                        buf = b''
                        break
                    end = buf.find(b'\xff\xd9', start + 2)
                    if end == -1:
                        buf = buf[start:]
                        break
                    jpg_data = buf[start:end + 2]
                    buf = buf[end + 2:]
                    frame = cv2.imdecode(
                        np.frombuffer(jpg_data, dtype=np.uint8),
                        cv2.IMREAD_COLOR
                    )
                    if frame is not None:
                        with self.lock:
                            self.frame = frame
            except Exception as e:
                time.sleep(0.1)
    
    def get_frame(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None
    
    def stop(self):
        self.running = False
        if self.process:
            self.process.terminate()
            self.process.wait()


def inference_worker():
    """Thread riêng cho YOLO inference."""
    global model, yolo_ok, yolo_error, latest_detections
    
    try:
        print("⏳ Đang load YOLO model ONNX...")
        from ultralytics import YOLO
        model = YOLO(MODEL_PATH)
        test_img = np.zeros((IMGSZ, IMGSZ, 3), dtype=np.uint8)
        model.predict(test_img, conf=0.5, imgsz=IMGSZ, verbose=False)
        yolo_ok = True
        print("✅ YOLO model sẵn sàng!")
    except Exception as e:
        yolo_ok = False
        yolo_error = str(e)
        print(f"⚠️  YOLO không hoạt động: {e}")
        return
    
    inference_interval = 1.0 / INFERENCE_FPS
    last_inference_time = 0
    
    while True:
        try:
            if not yolo_ok:
                time.sleep(1)
                continue
            current_time = time.time()
            if current_time - last_inference_time < inference_interval:
                time.sleep(0.05)
                continue
            if frame_queue.empty():
                time.sleep(0.05)
                continue
            
            frame = frame_queue.get()
            last_inference_time = current_time
            
            # ⏱ Đo thời gian inference
            t_inf_start = time.perf_counter()
            results = model.predict(
                frame, conf=CONF_THRESH, iou=0.45,
                imgsz=IMGSZ, verbose=False, stream=True
            )
            
            detections = []
            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls)
                    if cls_id >= len(CLASS_NAMES):
                        continue
                    conf = float(box.conf)
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    name = CLASS_NAMES[cls_id]
                    detections.append({
                        'cls_id': cls_id,
                        'conf': conf,
                        'box': (x1, y1, x2, y2),
                        'name': name,
                        'name_vi': CLASS_VI.get(name, name),
                        'color': COLORS[cls_id % len(COLORS)]
                    })
            t_inf_end = time.perf_counter()
            inference_ms = (t_inf_end - t_inf_start) * 1000
            
            with detection_lock:
                latest_detections = detections
            
            # Log ra terminal
            n_det = len(detections)
            print(f"⏱ Inference: {inference_ms:.1f}ms | Detections: {n_det}")
            
            # Cập nhật timing stats (draw_ms sẽ được cập nhật ở gen_frames)
            with timing_lock:
                timing_stats['inference_ms'] = round(inference_ms, 1)
                
        except Exception as e:
            print(f"⚠️  Inference error: {e}")
            time.sleep(0.5)


def draw_detections(frame, detections):
    for det in detections:
        x1, y1, x2, y2 = det['box']
        color = det['color']
        label = f"{det['name']} {det['conf']:.0%}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    return frame


def gen_frames():
    fps_deque = deque(maxlen=30)
    draw_log_counter = [0]  # mutable counter cho log
    while True:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        t0 = time.time()
        if frame_queue.full():
            try: frame_queue.get_nowait()
            except: pass
        try: frame_queue.put_nowait(frame.copy())
        except: pass
        
        with detection_lock:
            dets_copy = list(latest_detections)
        
        if dets_copy:
            # ⏱ Đo thời gian vẽ bounding box
            t_draw_start = time.perf_counter()
            frame = draw_detections(frame, dets_copy)
            t_draw_end = time.perf_counter()
            draw_ms = (t_draw_end - t_draw_start) * 1000
            
            with timing_lock:
                timing_stats['draw_ms'] = round(draw_ms, 2)
                timing_stats['total_ms'] = round(
                    timing_stats['inference_ms'] + draw_ms, 1
                )
                timing_stats['fps_effective'] = round(
                    1000.0 / timing_stats['total_ms'], 1
                ) if timing_stats['total_ms'] > 0 else 0
            
            # Log mỗi 30 frame (tránh spam terminal)
            draw_log_counter[0] += 1
            if draw_log_counter[0] % 30 == 0:
                with timing_lock:
                    s = timing_stats
                print(
                    f"🎨 Draw: {s['draw_ms']:.2f}ms | "
                    f"Inference: {s['inference_ms']:.1f}ms | "
                    f"Total: {s['total_ms']:.1f}ms | "
                    f"~{s['fps_effective']:.1f} FPS"
                )
        
        fps_deque.append(time.time() - t0)
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n")


# ── HTML Template ──────────────────────────────────────────────
# Dashboard được tách ra file templates/dashboard.html
# Thiết kế mới: Tailwind CSS + Chart.js + Disease Encyclopedia + Demo Mode


# ── Flask routes ──────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/video")
def video():
    return Response(gen_frames(),
                   mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/api/detections")
def api_detections():
    with detection_lock:
        dets = [
            {"name": d["name"], "name_vi": d["name_vi"], "conf": round(d["conf"], 3),
             "box": d["box"]}
            for d in latest_detections
        ]
    with timing_lock:
        t_stats = dict(timing_stats)
    return jsonify({
        "count": len(dets),
        "detections": dets,
        "yolo_ok": yolo_ok,
        "yolo_error": yolo_error,
        "camera_ok": camera.frame is not None if 'camera' in globals() else False,
        "uptime": round(time.time() - start_time_global, 1),
        "timing": t_stats,
    })


@app.route("/status")
def status():
    with detection_lock:
        det_count = len(latest_detections)
    return jsonify({
        "yolo_ok": yolo_ok,
        "yolo_error": yolo_error,
        "detections": det_count,
        "camera_ok": camera.frame is not None,
    })


@app.route("/api/chat", methods=["POST"])
def api_chat():
    try:
        from core.run_graph import run_graph
        import json
        
        req = request.json
        session_id = req.get("session_id", "default")
        message = req.get("message", "")
        detected_disease = req.get("detected_disease", None)
        report = req.get("report", {})
        is_first_message = req.get("is_first_message", False)

        if session_id not in CHAT_MEMORY:
            CHAT_MEMORY[session_id] = {
                "messages": [],
                "detected_disease": None,
                "report": None,
            }
        
        session_data = CHAT_MEMORY[session_id]
        messages = session_data["messages"]
        
        if detected_disease and detected_disease != session_data.get("detected_disease"):
            session_data["messages"] = []
            session_data["detected_disease"] = detected_disease
            session_data["report"] = report
            messages = session_data["messages"]
        elif detected_disease:
            session_data["detected_disease"] = detected_disease
            if report:
                session_data["report"] = report

        system_context = None
        user_question = message

        if is_first_message and session_data.get("detected_disease"):
            disease = session_data["detected_disease"]
            report_blob = session_data.get("report") or {}
            system_context = (
                f"The plant disease detected is {disease}. "
                f"You are an agricultural assistant. Give accurate, safe, and practical advice. "
                f"Use this detection report to ground your answer: {json.dumps(report_blob)}"
            )
            if not user_question.strip():
                user_question = f"What is the treatment for {disease}?"

        answer, new_messages = run_graph(
            user_input=user_question,
            messages=messages,
            system_context=system_context
        )
        
        CHAT_MEMORY[session_id]["messages"] = new_messages
        
        return jsonify({
            "answer": answer,
            "detected_disease": session_data["detected_disease"],
            "session_id": session_id
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": "Lỗi khi gọi AI: Vui lòng kiểm tra API Key trong file .env hoặc kết nối mạng.",
            "details": str(e)
        }), 500



# ── Main ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  🍅 Tomato AI Dashboard - IoT Web Server")
    print("=" * 60)
    
    print("Khởi tạo camera...")
    camera = PiCamera(width=CAM_WIDTH, height=CAM_HEIGHT, fps=CAM_FPS)
    
    inference_thread = threading.Thread(target=inference_worker, daemon=True)
    inference_thread.start()
    
    print(f"Model: {MODEL_PATH}")
    print(f"Inference FPS: {INFERENCE_FPS}")
    print(f"Camera FPS: {CAM_FPS}")
    print(f"🌐 Web UI: http://0.0.0.0:5000")
    print("=" * 60)
    
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
    finally:
        camera.stop()
