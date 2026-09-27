#!/bin/bash
# setup_realtime.sh
# Script cài đặt môi trường cho real-time detection trên Raspberry Pi 4

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "  Setup Real-time Detection - Pi 4"
echo "=========================================="

# Kiểm tra quyền root
if [ "$EUID" -eq 0 ]; then 
    echo "❌ Không chạy script này với sudo!"
    echo "   Chạy: bash setup_realtime.sh"
    exit 1
fi

# 1. Cài đặt system packages
echo ""
echo "📦 Bước 1: Cài đặt system packages..."
sudo apt update
sudo apt install -y \
    python3-opencv \
    python3-numpy \
    python3-pip \
    python3-venv \
    rpicam-apps \
    libopenblas-dev

echo "✅ System packages đã cài xong"

# 2. Tạo virtual environment
echo ""
echo "🐍 Bước 2: Tạo virtual environment..."
if [ -d "venv" ]; then
    echo "⚠️  venv đã tồn tại, xóa và tạo lại..."
    rm -rf venv
fi

python3 -m venv --system-site-packages venv
source venv/bin/activate

echo "✅ Virtual environment đã tạo"

# 3. Set biến môi trường
echo ""
echo "🔧 Bước 3: Set biến môi trường..."
export OMP_NUM_THREADS=4

# Thêm vào ~/.bashrc nếu chưa có
if ! grep -q "OMP_NUM_THREADS" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "# Gioi han so luong luong CPU cho ung dung" >> ~/.bashrc
    echo "export OMP_NUM_THREADS=4" >> ~/.bashrc
    echo "✅ Đã thêm biến môi trường vào ~/.bashrc"
else
    echo "✅ Biến môi trường đã có trong ~/.bashrc"
fi

# 4. Cài Python packages
echo ""
echo "📚 Bước 4: Cài Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Python packages đã cài xong"

# 5. Test YOLO
echo ""
echo "🧪 Bước 5: Test YOLO model..."
python3 << 'EOF'
import os
os.environ["OMP_NUM_THREADS"] = "4"

try:
    from ultralytics import YOLO
    import numpy as np
    from pathlib import Path
    import os
    from dotenv import load_dotenv

    load_dotenv()
    
    model_path = Path(os.getenv("MODEL_PATH", "model/tomato_6cls_ncnn_model"))
    imgsz = int(os.getenv("MODEL_IMGSZ", "640"))
    print(f"  Loading model: {model_path}...")
    model = YOLO(str(model_path))
    
    print("  Testing inference...")
    test_img = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
    model.predict(test_img, conf=0.5, imgsz=imgsz, verbose=False)
    
    print("✅ YOLO model hoạt động tốt!")
except Exception as e:
    print(f"⚠️  YOLO test failed: {e}")
    print("   Camera vẫn có thể chạy (không có detection)")
EOF

# 6. Test camera
echo ""
echo "📷 Bước 6: Test camera..."
if command -v rpicam-hello &> /dev/null; then
    echo "  Kiểm tra camera (2 giây)..."
    timeout 3 rpicam-hello --timeout 2000 || true
    echo "✅ Camera command có sẵn"
else
    echo "⚠️  rpicam-hello không tìm thấy"
fi

# 7. Tạo script khởi động nhanh
echo ""
echo "🚀 Bước 7: Tạo script khởi động nhanh..."

cat > run_web.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source venv/bin/activate
export OMP_NUM_THREADS=4
python app_pi_realtime.py
EOF
chmod +x run_web.sh

cat > run_display.sh << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source venv/bin/activate
export OMP_NUM_THREADS=4
python camera_pi_realtime.py
EOF
chmod +x run_display.sh

echo "✅ Đã tạo run_web.sh và run_display.sh"

# Hoàn thành
echo ""
echo "=========================================="
echo "  ✅ CÀI ĐẶT HOÀN TẤT!"
echo "=========================================="
echo ""
echo "Cách chạy:"
echo ""
echo "1. Web App (truy cập qua trình duyệt):"
echo "   ./run_web.sh"
echo "   Truy cập: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "2. Hiển thị trực tiếp (HDMI/VNC):"
echo "   ./run_display.sh"
echo ""
echo "=========================================="
