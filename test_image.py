import sys
import os
import tkinter as tk
from tkinter import filedialog
from ultralytics import YOLO

MODEL_PATH = r"d:\DACN\tomato_camera\model\best.pt"

def select_image():
    """Mở hộp thoại để người dùng chọn ảnh"""
    # Khởi tạo và ẩn cửa sổ chính của tkinter
    root = tk.Tk()
    root.withdraw()
    
    # Luôn hiển thị hộp thoại lên trên cùng
    root.attributes('-topmost', True)
    
    # Mở hộp thoại chọn file
    file_path = filedialog.askopenfilename(
        title="Chọn ảnh lá cà chua để test",
        filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp"), ("All files", "*.*")]
    )
    return file_path

def test_image(image_path):
    if not os.path.exists(MODEL_PATH):
        print(f"❌ Lỗi: Không tìm thấy model tại {MODEL_PATH}")
        return

    if not os.path.exists(image_path):
        print(f"❌ Lỗi: Không tìm thấy ảnh tại {image_path}")
        return

    print(f"⏳ Đang tải model từ {MODEL_PATH}...")
    model = YOLO(MODEL_PATH)

    print(f"🔍 Đang chạy nhận diện cho ảnh: {image_path}...")
    # Gọi hàm predict của YOLO: 
    # Tắt save=True mặc định để tự lưu vào thư mục riêng theo class
    # show=True sẽ mở popup hiển thị ảnh kết quả
    results = model.predict(source=image_path, save=False, show=True)
    
    result = results[0]
    
    print("\n" + "="*45)
    print("📊 KẾT QUẢ NHẬN DIỆN CHI TIẾT:")
    
    # Nơi lưu trữ ảnh phân loại
    base_save_dir = r"d:\DACN\tomato_camera\runs\detect\yolo11n_basic"
    
    if len(result.boxes) == 0:
        print("Không phát hiện thấy bệnh nào trên lá!")
        target_folder = os.path.join(base_save_dir, "No_Detection")
    else:
        # Tìm bệnh có độ tin cậy cao nhất để làm tên thư mục lưu
        best_box = max(result.boxes, key=lambda b: float(b.conf[0]))
        best_class_id = int(best_box.cls[0])
        best_class_name = model.names[best_class_id]
        
        target_folder = os.path.join(base_save_dir, best_class_name)
        
        for box in result.boxes:
            class_id = int(box.cls[0])
            class_name = model.names[class_id]
            conf = float(box.conf[0])
            print(f" - Phát hiện: {class_name} (Độ tin cậy: {conf:.2%})")
            
    print("="*45 + "\n")
    
    # Tạo thư mục nếu chưa tồn tại
    os.makedirs(target_folder, exist_ok=True)
    
    # Xử lý tên file không bị ghi đè
    base_name = os.path.basename(image_path)
    save_path = os.path.join(target_folder, base_name)
    
    counter = 1
    name_only, ext = os.path.splitext(base_name)
    while os.path.exists(save_path):
        save_path = os.path.join(target_folder, f"{name_only}_{counter}{ext}")
        counter += 1
        
    # Lưu ảnh kết quả có vẽ sẵn khung (bounding box)
    result.save(filename=save_path)
    
    print("💡 Lưu ý:")
    print(f" - Ảnh kết quả đã được tự động phân loại và lưu tại:\n   📁 {save_path}")
    print(" - Một cửa sổ hiển thị ảnh vừa được mở lên. Bạn có thể xem, sau đó nhấn phím bất kỳ trên cửa sổ đó để đóng nó lại.")

if __name__ == "__main__":
    img_path = None
    
    # Nếu chạy bằng lệnh có truyền đường dẫn (ví dụ: python test_image.py anh.jpg)
    if len(sys.argv) >= 2:
        img_path = sys.argv[1].strip('"').strip("'")
    else:
        # Nếu không truyền đường dẫn, sẽ tự động mở hộp thoại chọn file
        print("Đang mở hộp thoại chọn file ảnh...")
        img_path = select_image()
        
    if img_path:
        test_image(img_path)
    else:
        print("⚠️ Bạn chưa chọn ảnh nào hoặc đã hủy bỏ.")
