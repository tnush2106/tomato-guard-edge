#!/usr/bin/env python3
# camera_pi_realtime.py
# Hiển thị real-time trên màn hình (HDMI/VNC) - tối ưu cho Pi 4
# Chạy: python camera_pi_realtime.py

import cv2
import numpy as np
import subprocess
import threading
import time
import os
import queue
from collections import deque
from PIL import ImageFont, ImageDraw, Image

# ── Fix ARM ───────────────────────────────────────────────────
os.environ["OPENBLAS_CORETYPE"] = "ARMV8"
os.environ["OMP_NUM_THREADS"] = "4"

# ── Config ────────────────────────────────────────────────────
MODEL_PATH = "model/yolo11n_tomato_best_ncnn_model"
CONF_THRESH = 0.35
IMGSZ = 320  # Giảm để tăng tốc độ
CAM_WIDTH = 640
CAM_HEIGHT = 480
CAM_FPS = 15
INFERENCE_FPS = 3  # Chỉ chạy inference 3 FPS

CLASS_NAMES = [
    "Late_blight", "Leaf_Mold", "Septoria_leaf_spot",
    "Spider_mites", "Target_Spot", "Tomato_Yellow_Leaf_Curl_Virus"
]
CLASS_VI = {
    "Late_blight": "Mốc sương",
    "Leaf_Mold": "Mốc lá",
    "Septoria_leaf_spot": "Đốm lá Septoria",
    "Spider_mites": "Nhện đỏ",
    "Target_Spot": "Đốm bia",
    "Tomato_Yellow_Leaf_Curl_Virus": "Virus xoăn vàng lá",
}
COLORS = [
    (231,76,60), (26,188,156), (243,156,18),
    (52,152,219), (155,89,182), (22,160,133)
]
DISEASE_INFO = {
    "Late_blight": "Xử lý: Cắt bỏ lá, phun Metalaxyl",
    "Leaf_Mold": "Xử lý: Tăng thông gió, phun Chlorothalonil",
    "Septoria_leaf_spot": "Xử lý: Phun Mancozeb, loại bỏ lá già",
    "Spider_mites": "Xử lý: Phun Abamectin hoặc dầu Neem",
    "Target_Spot": "Xử lý: Phun Chlorothalonil, luân canh cây trồng",
    "Tomato_Yellow_Leaf_Curl_Virus": "Xử lý: Diệt bọ phấn, nhổ bỏ cây bệnh",
}

# ── Global state ──────────────────────────────────────────────
model = None
yolo_ok = False
latest_detections = []
detection_lock = threading.Lock()
frame_queue = queue.Queue(maxsize=2)

# ── Font Unicode cho tiếng Việt ───────────────────────────────
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]
font_label = None
font_info = None
font_small = None
for fp in FONT_PATHS:
    if os.path.exists(fp):
        font_label = ImageFont.truetype(fp, 18)
        font_info = ImageFont.truetype(fp, 15)
        font_small = ImageFont.truetype(fp, 13)
        print(f"✅ Font Unicode: {fp}")
        break
if font_label is None:
    font_label = ImageFont.load_default()
    font_info = font_label
    font_small = font_label
    print("⚠️  Không tìm thấy font TTF, dùng font mặc định")


def put_text_vi(frame, text, pos, font=None, color=(255, 255, 255)):
    """Vẽ chữ tiếng Việt lên frame OpenCV bằng PIL."""
    if font is None:
        font = font_label
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    draw.text(pos, text, font=font, fill=(color[2], color[1], color[0]))
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)



class PiCamera:
    """Camera Module 3 với rpicam-vid."""
    
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
        
        print(f"Khởi động camera: {' '.join(cmd)}")
        self.process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=width * height * 3
        )
        self.running = True
        self.thread = threading.Thread(target=self._read_frames, daemon=True)
        self.thread.start()
        time.sleep(1.5)
        print(f"✅ Camera sẵn sàng! {width}x{height} @ {fps}fps")
    
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





# ── Custom Architecture Module (CBAM) ─────────────────────────
import torch
import torch.nn as nn
import ultralytics.nn.modules.conv as u_conv
import ultralytics.nn.tasks as u_tasks

class ChannelAttention(nn.Module):
    def __init__(self, in_planes, ratio=16):
        super(ChannelAttention, self).__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.max_pool = nn.AdaptiveMaxPool2d(1)
        self.fc = nn.Sequential(
            nn.Conv2d(in_planes, in_planes // ratio, 1, bias=False),
            nn.ReLU(),
            nn.Conv2d(in_planes // ratio, in_planes, 1, bias=False)
        )
        self.sigmoid = nn.Sigmoid()
    def forward(self, x):
        return self.sigmoid(self.fc(self.avg_pool(x)) + self.fc(self.max_pool(x)))

class SpatialAttention(nn.Module):
    def __init__(self, kernel_size=7):
        super(SpatialAttention, self).__init__()
        self.conv1 = nn.Conv2d(2, 1, kernel_size, padding=(3 if kernel_size == 7 else 1), bias=False)
        self.sigmoid = nn.Sigmoid()
    def forward(self, x):
        return self.sigmoid(self.conv1(torch.cat([torch.mean(x, dim=1, keepdim=True), torch.max(x, dim=1, keepdim=True)[0]], dim=1)))

class CBAM(nn.Module):
    def __init__(self, c1, c2=None, ratio=16, kernel_size=7):
        super(CBAM, self).__init__()
        self.ca = ChannelAttention(c1, ratio)
        self.sa = SpatialAttention(kernel_size)
    def forward(self, x):
        return x * self.ca(x) * self.sa(x)

# Monkey-patching Ultralytics
u_conv.CBAM = CBAM
setattr(u_tasks, 'CBAM', CBAM)
original_parse_model = u_tasks.parse_model
def custom_parse_model(d, ch, verbose=True):
    globals()['CBAM'] = CBAM
    return original_parse_model(d, ch, verbose)
u_tasks.parse_model = custom_parse_model


def inference_worker():
    """Thread riêng cho YOLO inference."""
    global model, yolo_ok, latest_detections
    
    try:
        print("⏳ Đang load YOLO model custom CBAM...")
        from ultralytics import YOLO
        model = YOLO(MODEL_PATH)
        test_img = np.zeros((64, 64, 3), dtype=np.uint8)
        model.predict(test_img, conf=0.5, imgsz=64, verbose=False)
        yolo_ok = True
        print(f"✅ YOLO sẵn sàng! Classes: {len(CLASS_NAMES)}")
    except Exception as e:
        print(f"⚠️  YOLO không hoạt động: {e}")
        print("Camera vẫn chạy (không có detection)")
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
            
            # Inference with stream=True
            results = model.predict(
                frame, conf=CONF_THRESH, iou=0.45,
                imgsz=IMGSZ, verbose=False, stream=True
            )
            
            # Lưu kết quả
            detections = []
            for r in results:
                for box in r.boxes:
                    cls_id = int(box.cls)
                    conf = float(box.conf)
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    name = CLASS_NAMES[cls_id]
                    detections.append({
                        'cls_id': cls_id, 'conf': conf,
                        'box': (x1, y1, x2, y2), 'name': name,
                        'name_vi': CLASS_VI.get(name, name),
                        'color': COLORS[cls_id % len(COLORS)]
                    })
            
            with detection_lock:
                latest_detections = detections
                
        except Exception as e:
            print(f"⚠️  Inference error: {e}")
            time.sleep(0.5)


# ── Main ──────────────────────────────────────────────────────
print("=" * 60)
print("  Tomato Disease Detector - Real-time Optimized")
print("=" * 60)

# Khởi tạo camera
camera = PiCamera(width=CAM_WIDTH, height=CAM_HEIGHT, fps=CAM_FPS)

# Khởi động inference worker
inference_thread = threading.Thread(target=inference_worker, daemon=True)
inference_thread.start()
print(f"Inference FPS: {INFERENCE_FPS} (giảm tải CPU)")

print("Nhấn 'Q' để thoát, 'S' để chụp ảnh")
print("=" * 60)

# Main loop
fps_deque = deque(maxlen=30)

try:
    while True:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        
        start_time = time.time()
        
        # Gửi frame cho inference worker
        if yolo_ok:
            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except:
                    pass
            try:
                frame_queue.put_nowait(frame.copy())
            except:
                pass
        
        # Vẽ detections từ cache
        with detection_lock:
            current_detections = latest_detections.copy()
        
        for det in current_detections:
            x1, y1, x2, y2 = det['box']
            color = det['color']
            label = f"{det['name_vi']} {det['conf']:.0%}"
            
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            # Vẽ nền cho nhãn
            bbox = font_label.getbbox(label)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            cv2.rectangle(frame, (x1, y1 - th - 10), (x1 + tw + 6, y1), color, -1)
            frame = put_text_vi(frame, label, (x1 + 2, y1 - th - 8), font_label, (255, 255, 255))
        
        # Tính FPS
        fps_deque.append(time.time() - start_time)
        fps = len(fps_deque) / sum(fps_deque) if fps_deque else 0
        
        # Panel thông tin
        panel_w = 320
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (panel_w, 280), (20, 20, 20), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        
        # FPS và status
        mode = "LIVE + AI" if yolo_ok else "LIVE (camera only)"
        frame = put_text_vi(frame, f"FPS: {fps:.1f} | {mode}", (10, 5), font_label, (0, 255, 0))
        frame = put_text_vi(frame, f"Phát hiện: {len(current_detections)} bệnh", (10, 30), font_info, (255, 255, 255))
        
        # Danh sách bệnh
        y_pos = 60
        if current_detections:
            frame = put_text_vi(frame, "KẾT QUẢ:", (10, y_pos), font_label, (0, 200, 255))
            y_pos += 25
            
            seen = {}
            for det in current_detections:
                name = det['name']
                if name not in seen:
                    seen[name] = []
                seen[name].append(det['conf'])
            
            for name, confs in list(seen.items())[:3]:
                name_vi = CLASS_VI.get(name, name)
                avg_conf = sum(confs) / len(confs)
                frame = put_text_vi(frame, f"  {name_vi} ({avg_conf:.0%})", (10, y_pos), font_info, (255, 200, 0))
                y_pos += 20
                info = DISEASE_INFO.get(name, "")
                frame = put_text_vi(frame, f"  > {info[:35]}", (10, y_pos), font_small, (180, 180, 180))
                y_pos += 22
        elif not yolo_ok:
            frame = put_text_vi(frame, "  AI model không hoạt động", (10, y_pos), font_info, (0, 165, 255))
        else:
            frame = put_text_vi(frame, "  Không phát hiện bệnh", (10, y_pos), font_info, (0, 255, 0))
        
        # Hướng dẫn
        h = frame.shape[0]
        frame = put_text_vi(frame, "Q: Thoát | S: Chụp ảnh", (10, h - 25), font_small, (150, 150, 150))
        
        cv2.imshow("Tomato Disease Detector - Real-time", frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("s"):
            fname = f"capture_{int(time.time())}.jpg"
            cv2.imwrite(fname, frame)
            print(f"✅ Đã lưu: {fname}")

finally:
    camera.stop()
    cv2.destroyAllWindows()
    print("Đã thoát!")
