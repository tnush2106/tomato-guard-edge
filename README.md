# 🍅 Tomato Disease Detection — Raspberry Pi 4

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![YOLO](https://img.shields.io/badge/YOLO11-Ultralytics-00FFFF?logo=yolo&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi%204-8GB-C51A4A?logo=raspberrypi&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Web%20Server-000000?logo=flask&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

Hệ thống **nhận diện bệnh trên lá cà chua theo thời gian thực** sử dụng YOLO11 trên Raspberry Pi 4 với Camera Module 3. Hỗ trợ giao diện web dashboard và chatbot AI tư vấn điều trị.

---

## 📋 Mục lục

- [Tính năng](#-tính-năng)
- [Các loại bệnh nhận diện](#-các-loại-bệnh-nhận-diện)
- [Kiến trúc hệ thống](#-kiến-trúc-hệ-thống)
- [Yêu cầu phần cứng](#-yêu-cầu-phần-cứng)
- [Cài đặt](#-cài-đặt)
- [Sử dụng](#-sử-dụng)
- [Cấu trúc project](#-cấu-trúc-project)
- [API Endpoints](#-api-endpoints)
- [Training Model](#-training-model)
- [License](#-license)

---

## ✨ Tính năng

- 🎥 **Real-time Detection** — Nhận diện bệnh trực tiếp từ camera với YOLO11 ONNX
- 🌐 **Web Dashboard** — Giao diện web đẹp, truy cập từ mọi thiết bị trong LAN
- 🤖 **AI Chatbot** — Tư vấn điều trị bệnh sử dụng LangGraph + OpenAI
- 📊 **Thống kê thời gian thực** — Đo inference time, draw time, FPS
- 📷 **Chụp ảnh** — Lưu ảnh phát hiện bệnh với timestamp
- 📱 **Responsive** — Hoạt động trên PC, tablet, và điện thoại

---

## 🦠 Các loại bệnh nhận diện

| # | Tên bệnh (EN) | Tên bệnh (VI) | Mức độ |
|---|----------------|----------------|--------|
| 1 | Early Blight | Bệnh đốm vòng | 🔴 Nghiêm trọng |
| 2 | Late Blight | Bệnh mốc sương | 🔴 Rất nghiêm trọng |
| 3 | Leaf Miner | Sâu vẽ bùa | ⚠️ Trung bình |
| 4 | Magnesium Deficiency | Thiếu Magiê | 🟡 Nhẹ |
| 5 | Nitrogen Deficiency | Thiếu Nitơ | 🟡 Nhẹ |
| 6 | Potassium Deficiency | Thiếu Kali | ⚠️ Trung bình |
| 7 | Spotted Wilt Virus | Virus đốm héo | 🔴 Rất nghiêm trọng |

---

## 🏗 Kiến trúc hệ thống

```
┌─────────────────┐     MJPEG Stream     ┌──────────────────┐
│  Camera Module 3 │ ──────────────────▶  │  Raspberry Pi 4  │
│  (rpicam-vid)    │                      │                  │
└─────────────────┘                      │  ┌────────────┐  │
                                          │  │  YOLO11    │  │
                                          │  │  (ONNX)    │  │
                                          │  └──────┬─────┘  │
                                          │         │        │
                                          │  ┌──────▼─────┐  │
                                          │  │  Flask Web  │  │
                                          │  │  Server     │  │
                                          │  └──────┬─────┘  │
                                          └─────────┼────────┘
                                                    │ :5000
                                          ┌─────────▼────────┐
                                          │   Web Dashboard   │
                                          │   (Browser)       │
                                          └──────────────────┘
```

---

## 🔧 Yêu cầu phần cứng

| Thành phần | Chi tiết |
|------------|----------|
| **Board** | Raspberry Pi 4 Model B (4GB/8GB RAM) |
| **Camera** | Raspberry Pi Camera Module 3 |
| **Storage** | MicroSD 32GB+ (Class 10) |
| **OS** | Raspberry Pi OS (64-bit, Bookworm) |
| **Nguồn** | 5V/3A USB-C |

---

## 🚀 Cài đặt

### 1. Clone repository

```bash
git clone https://github.com/<your-username>/tomato_camera.git
cd tomato_camera
```

### 2. Cài đặt tự động (khuyến nghị)

```bash
bash setup_realtime.sh
```

Script sẽ tự động:
- Cài system packages (`python3-opencv`, `rpicam-apps`, ...)
- Tạo virtual environment
- Cài Python dependencies
- Test camera và YOLO model

### 3. Cài đặt thủ công

```bash
# Cài system packages
sudo apt update
sudo apt install -y python3-opencv python3-numpy python3-pip python3-venv rpicam-apps libopenblas-dev

# Tạo venv
python3 -m venv --system-site-packages venv
source venv/bin/activate

# Cài dependencies
pip install -r requirements.txt
```

### 4. Cấu hình API keys (cho chatbot AI)

```bash
cp .env.example .env
# Sửa .env và điền API keys của bạn
nano .env
```

### 5. Download model ONNX

Tải model ONNX và đặt vào thư mục `model/`:

```
model/
├── yolo11n_tomato_best.onnx   (10MB  - Nano, nhanh nhất)
├── yolo11s_tomato_best.onnx   (38MB  - Small)
├── yolo11m_tomato_best.onnx   (80MB  - Medium)
├── yolo11l_tomato_best.onnx   (102MB - Large)
└── yolo11x_tomato_best.onnx   (228MB - Extra Large, chính xác nhất)
```

> **Lưu ý**: Model files không được đưa lên GitHub do kích thước lớn. Liên hệ tác giả để nhận link download.

---

## 💻 Sử dụng

### Web Dashboard (truy cập qua trình duyệt)

```bash
bash run_web.sh
```

Truy cập: `http://<raspberry-pi-ip>:5000`

### Display Mode (hiển thị trực tiếp HDMI/VNC)

```bash
bash run_display.sh
```

### Chọn model

Sửa `MODEL_PATH` trong `app_pi_realtime.py`:

```python
# Chọn 1 trong các model:
MODEL_PATH = "model/yolo11n_tomato_best.onnx"   # Nano  — ~10 FPS
MODEL_PATH = "model/yolo11s_tomato_best.onnx"   # Small — ~5 FPS
MODEL_PATH = "model/yolo11m_tomato_best.onnx"   # Medium — ~3 FPS
```

---

## 📁 Cấu trúc project

```
tomato_camera/
├── app_pi_realtime.py       # 🌐 App chính — Web Dashboard mode
├── camera_pi_realtime.py    # 🖥  App phụ — Display mode (HDMI)
├── test_image.py            # 🧪 Test nhận diện trên ảnh tĩnh
│
├── core/                    # 🤖 Chatbot AI logic (LangGraph)
│   ├── build_graph.py       #    Xây dựng LangGraph workflow
│   ├── run_graph.py         #    Chạy chatbot pipeline
│   ├── faiss_setup.py       #    Setup FAISS vector store
│   └── llm.py               #    LLM configuration
│
├── agents/                  # 🧠 LangGraph Agents
│   ├── chat_agent.py        #    Agent chat chính
│   ├── router_agent.py      #    Router phân loại câu hỏi
│   ├── retriever_agent.py   #    Agent truy xuất tài liệu
│   ├── grader_answer_agent.py  # Agent đánh giá câu trả lời
│   ├── web_agent.py         #    Agent tìm kiếm web
│   └── state.py             #    State management
│
├── tools/                   # 🔧 LangGraph Tools
│   ├── retriever_tool.py    #    FAISS retriever
│   └── tavily_search_tool.py #   Tavily web search
│
├── templates/               # 🎨 Flask HTML templates
│   └── dashboard.html       #    Web Dashboard UI
│
├── model/                   # 📦 YOLO11 ONNX models (.gitignore)
├── faiss_db/                # 📚 FAISS vector database
├── dataset/                 # 📊 Training dataset (.gitignore)
├── train_result/            # 📈 Training results (.gitignore)
│
├── requirements.txt         # 📋 Python dependencies
├── setup_realtime.sh        # ⚙️  Script cài đặt tự động
├── run_web.sh               # 🚀 Chạy web app
├── run_display.sh           # 🖥  Chạy display mode
├── .env.example             # 🔑 Template API keys
├── .gitignore               # 🚫 Git ignore rules
└── LICENSE                  # 📄 MIT License
```

---

## 🔌 API Endpoints

| Method | Endpoint | Mô tả |
|--------|----------|--------|
| `GET` | `/` | Web Dashboard |
| `GET` | `/video` | MJPEG video stream |
| `GET` | `/api/detections` | Kết quả nhận diện (JSON) |
| `GET` | `/status` | Trạng thái hệ thống |
| `POST` | `/api/chat` | Chatbot AI tư vấn |

### Ví dụ response `/api/detections`:

```json
{
  "count": 2,
  "detections": [
    {
      "name": "Late_blight",
      "name_vi": "Bệnh mốc sương",
      "conf": 0.892,
      "box": [120, 85, 340, 290]
    }
  ],
  "yolo_ok": true,
  "timing": {
    "inference_ms": 245.3,
    "draw_ms": 0.85,
    "total_ms": 246.2,
    "fps_effective": 4.1
  },
  "uptime": 3600.5
}
```

---

## 🏋️ Training Model

### Yêu cầu
- Kaggle Notebook (GPU T4 x2) hoặc Google Colab (GPU T4)
- Dataset: 7 classes, YOLO format

### Training trên Kaggle

```python
# Upload dataset lên Kaggle Datasets
# Sử dụng script training phù hợp
# Model tự động lưu checkpoint mỗi 5 epochs
# Hỗ trợ resume training khi hết 12h session
```

### Export sang ONNX

```python
from ultralytics import YOLO
model = YOLO("best.pt")
model.export(format="onnx", imgsz=640, opset=12)
```

---

## 📝 License

Dự án này được phân phối dưới [MIT License](LICENSE).

---

## 👥 Tác giả

- Đồ án chuyên ngành — Nhận diện bệnh trên lá cà chua bằng YOLO11
- Platform: Raspberry Pi 4 + Camera Module 3

---

<p align="center">
  <b>🍅 YOLO11 · Raspberry Pi 4 · Real-time Detection</b>
</p>
