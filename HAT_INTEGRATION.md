# Kết nối Raspberry Pi với ESP32 HAT

Phần này dùng dashboard `templates/TomatoGuard_Pro_Dashboard.html` và sơ đồ
`Hardware_V2/PCB_HAT.pdf` xuất ngày 16/09/2026. Bản `Sheet2.pdf` cũ có một số
GPIO khác. Firmware nằm trong `firmware/esp32_hat/`; hướng dẫn biên dịch và
hiệu chuẩn chi tiết nằm trong README của thư mục đó.

## Kết nối và chức năng

| Tín hiệu | Raspberry Pi / ngoại vi | ESP32 |
| --- | --- | --- |
| UART Pi → HAT | GPIO14, chân vật lý 8 (TX) | GPIO16 (RX2), qua R26 |
| UART HAT → Pi | GPIO15, chân vật lý 10 (RX) | GPIO17 (TX2), qua R27 |
| GND | GND chung qua header | GND |
| I²C | SHT31, BH1750, ADS1115 | SDA21, SCL22 |
| RL1 | Đèn | GPIO27, active HIGH |
| RL2 | Quạt | GPIO26, active HIGH |
| RL3 | Bơm | GPIO25, active HIGH |
| Phím | SW6 Capture / SW3 Up / SW4 Select / SW5 Down | GPIO35 / 34 / 36 / 39, active LOW |
| TFT ILI9341 | CS / RESET / DC / MOSI / SCK / MISO | GPIO5 / 4 / 2 / 23 / 18 / 19 |

UART dùng mức logic **3,3 V**, 115200 baud, 8N1. Header Pi không cấp nguồn
cho HAT trong sơ đồ này: Pi và HAT có nguồn riêng, GND chung. USB CP2102
trên HAT dùng UART0 để nạp/debug; giao thức ứng dụng ở UART2 (GPIO16/17).
Để thử từ máy tính, cần bộ USB–UART 3,3 V nối vào UART2; chỉ đổi sang COM
của CP2102 trên bo sẽ không nhận được telemetry UART2.

## Chạy trên Raspberry Pi

1. Nạp firmware ESP32 theo `firmware/esp32_hat/README.md`.
2. Chạy `sudo raspi-config`, chọn **Interface Options → Serial Port**:
   tắt login shell qua serial, bật phần cứng serial, rồi khởi động lại.
   `/dev/serial0` là alias UART chính trên Pi 4. Xem
   [hướng dẫn UART chính thức của Raspberry Pi](https://www.raspberrypi.com/documentation/computers/configuration.html#configure-uarts).
3. Trong thư mục `Software`, kích hoạt môi trường của dự án và cài pyserial:

   ```bash
   source venv/bin/activate
   pip install 'pyserial>=3.5,<4'
   ```

   Cài mới toàn bộ dự án vẫn dùng `pip install -r requirements.txt` như trước.
4. Thêm các dòng sau vào `.env` hiện có, giữ nguyên các API key của bạn:

   ```dotenv
   HAT_ENABLED=1
   HAT_SERIAL_PORT=/dev/serial0
   HAT_BAUDRATE=115200
   HAT_STALE_SECONDS=6
   HAT_COMMAND_TIMEOUT=2.5
   ```

5. Chạy `bash run_web.sh`, mở `http://<ip-cua-pi>:5000`. Nếu báo permission
   denied với serial, thêm tài khoản chạy ứng dụng vào nhóm `dialout` rồi
   đăng xuất/đăng nhập lại. Chỉ một tiến trình được mở UART này.

Web mode khởi tạo camera, inference, UART và worker Capture. Import ứng dụng
bằng WSGI không tự mở các thiết bị; sử dụng entry point trên để chạy trạm.
`camera_pi_realtime.py` vẫn là chương trình hiển thị camera độc lập.

Model YOLO mặc định của ứng dụng vẫn là cấu hình hiện có. Cần cung cấp model
đúng đường dẫn và nhãn để nhận diện hoạt động; lỗi model không ngăn API HAT
thu thập telemetry hoặc điều khiển relay.

## Vận hành

- ESP32 khởi động **MANUAL**, cả ba relay tắt. Dashboard không gửi lệnh AUTO
  khi tải trang. Chuyển chế độ là lệnh thực gửi xuống ESP32.
- Firmware dùng bốn FreeRTOS task riêng cho UART, cảm biến I²C, TFT SPI và
  điều khiển relay/nút bấm. Task điều khiển là nơi duy nhất ghi GPIO relay;
  các task trao đổi bằng queue và snapshot có mutex.
- MANUAL cho phép thao tác từng relay. AUTO dùng ngưỡng/hysteresis cấu hình
  trong firmware; lệnh bật/tắt relay riêng bị từ chối trong AUTO.
- Ngưỡng mặc định phục vụ thử nghiệm: đèn bật dưới 8.000 lux/tắt trên 15.000;
  quạt bật khi nhiệt độ ≥32 °C hoặc RH ≥85%, tắt khi nhiệt độ ≤29 °C và
  RH ≤78%; bơm bật ở độ ẩm đất ≤30%, tắt khi ≥45%. Hiệu chỉnh theo hệ thống
  trồng thực tế. Đây không phải quyết định điều khiển từ chatbot hoặc YOLO.
- Độ ẩm đất phải hiệu chuẩn giá trị ADS1115 khi khô/ướt trong cấu hình
  firmware. Trước đó `soil=null`, không hiển thị phần trăm giả và không tưới
  tự động. Số ADC thô vẫn được truyền nếu ADS1115 hoạt động.
- Firmware giới hạn thời gian bơm liên tục và thời gian nghỉ theo cấu hình;
  lỗi cảm biến tắt tải phụ thuộc cảm biến trong AUTO. Chi tiết ở README firmware.
- Pi gửi heartbeat mỗi 2 giây. ESP32 mất heartbeat 10 giây sẽ tắt relay và
  về MANUAL; kết nối lại không tự bật lại tải. Khi telemetry mất quá 6 giây,
  Pi trả các số đo/trạng thái relay là `null`, chặn lệnh mới và ngừng heartbeat
  cho đến khi có telemetry trở lại. Đóng web app cũng ngừng heartbeat.
- Nút Capture trên HAT hoặc nút tương ứng trong dashboard phát sự kiện về Pi.
  Pi lưu ảnh camera mới nhất vào `Software/captures/`; metadata và URL ảnh
  xuất hiện ở `last_capture`. Không có camera thì báo `last_capture_error`.
  ACK Capture xác nhận ESP32 nhận thao tác, không khẳng định ảnh đã lưu xong.
- TFT có trang thông số hệ thống, menu chọn trang và trang điều khiển ba relay.
  SW3/SW5 di chuyển lên/xuống, SW4 chọn hoặc đảo trạng thái relay trong MANUAL,
  SW6 gửi yêu cầu chụp ảnh. Các nút trên dashboard gọi cùng đường xử lý.
- Chatbot nhận số đo từ máy chủ ở từng lượt hỏi; không có công cụ bật/tắt tải.

## HTTP API

| API | Payload / kết quả |
| --- | --- |
| `GET /api/hat` | `sensors`, `relays`, `control_mode`, `hat`, `last_capture`, `last_capture_error` |
| `GET /api/detections` | Dữ liệu nhận diện trước đây cộng trạng thái HAT ở trên |
| `POST /api/relay` | `{"relay":1,"state":true}` — chỉ MANUAL |
| `POST /api/hat/mode` | `{"mode":"manual"}` hoặc `{"mode":"auto"}` |
| `POST /api/hat/action` | `{"action":"capture"}`; cũng hỗ trợ `up`, `ok`, `down` |
| `GET /captures/<filename>` | Ảnh do nút Capture HAT tạo |

Lệnh thành công trả `ok:true`, `ack_id` và snapshot đã được xác nhận. Lỗi:
400 sai JSON/tham số, 409 ESP32 từ chối hoặc sai mode, 503 chưa kết nối,
504 không nhận ACK. **Timeout nghĩa là chưa biết lệnh có được thực thi hay
không**; xem telemetry trước khi thao tác tiếp. Pi không tự gửi lại lệnh.
Trong lúc chờ telemetry xác nhận lại, `hat.outputs_uncertain=true`, relay và
mode trả `null`, và lệnh mới bị chặn; số đo cảm biến còn mới vẫn được hiển thị.

## UART protocol v1

Mỗi JSON UTF-8 trên một dòng, kết thúc `\n`, tối đa 1.024 byte nội dung.
Firmware không ghi debug log vào UART2. Parser giữ fragment qua nhiều lần
đọc, bỏ gói lỗi/quá dài đến hết newline, và kiểm tra kiểu/giá trị dữ liệu.
Transport dùng timeout đọc/ghi hữu hạn theo
[API pySerial](https://pyserial.readthedocs.io/en/stable/pyserial_api.html).

Pi gửi:

```json
{"v":1,"type":"command","id":"unique-id","command":"set_relay","relay":1,"state":true}
{"v":1,"type":"command","id":"unique-mode-id","command":"set_mode","mode":"manual"}
{"v":1,"type":"command","id":"unique-action-id","command":"action","action":"capture"}
{"v":1,"type":"command","id":"ping-id","command":"ping"}
```

ESP32 trả ACK có cùng `id`; chỉ dùng ACK đúng ID của lệnh còn chờ:

```json
{"v":1,"type":"ack","id":"unique-id","ok":true,"mode":"manual","relays":{"1":true,"2":false,"3":false}}
```

Telemetry mỗi 2 giây và sau thay đổi trạng thái:

```json
{"v":1,"type":"telemetry","seq":1,"uptime_ms":2000,"selected_relay":1,"mode":"manual","sensors":{"temp":27.5,"humidity":71.0,"light":5000,"soil":null,"soil_raw":15000},"sensor_ok":{"sht31":true,"bh1750":true,"ads1115":true,"soil_calibrated":false},"relays":{"1":false,"2":false,"3":false},"errors":[]}
```

Sự kiện Capture/Up/OK/Down:

```json
{"v":1,"type":"event","seq":2,"uptime_ms":2500,"event":"button","button":"capture"}
```

## Kiểm thử không cần bo mạch

```bash
python -m unittest discover -s tests -v
node tests/test_dashboard.cjs
```

Các kiểm thử Python dùng cổng UART giả, không mở cổng thật và không gọi LLM.
Kiểm thử Flask dùng chính các route ứng dụng, thay camera/YOLO bằng module
giả. Để xác nhận trên thiết bị, cần kiểm tra thêm số đo, cực tính relay,
hiệu chuẩn ADC, UART và TFT bằng bo mạch thực.
