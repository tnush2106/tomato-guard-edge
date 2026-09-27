# TomatoGuard ESP32 HAT firmware

Firmware PlatformIO cho bo ESP32 HAT trong `Hardware_V2/PCB_HAT.pdf`. ESP32
đọc SHT31, BH1750 và ADS1115; điều khiển RL1/RL2/RL3; hiển thị ILI9341; nhận
bốn phím vật lý; giao tiếp NDJSON với Raspberry Pi qua UART2.

## Kiến trúc FreeRTOS

Firmware tạo bốn task ứng dụng độc lập; `loopTask` mặc định của Arduino được
xóa sau khi khởi tạo:

| Task | Core | Priority | Quyền sở hữu |
| --- | ---: | ---: | --- |
| `hat-control` | 1 | 4 | Controller, GPIO relay, nút bấm và task watchdog |
| `hat-uart` | 1 | 3 | UART2, parser NDJSON, ACK, telemetry và event |
| `hat-sensors` | 0 | 2 | Bus I²C, SHT31, BH1750 và ADS1115 |
| `hat-tft` | 0 | 1 | Bus SPI và màn hình ILI9341 |

UART gửi lệnh sang task điều khiển qua queue có token tương quan. Event nút
bấm đi theo queue ngược lại. Dữ liệu cảm biến và trạng thái điều khiển được
công bố dưới dạng snapshot ngắn có mutex; không task nào giữ mutex trong lúc
đọc I²C, vẽ TFT hoặc chờ UART. Vì vậy lỗi hoặc thao tác chậm ở TFT không chặn
vòng an toàn relay 10 ms.

Kích thước stack, priority, core và độ dài queue nằm trong
`include/hat_config.h`. Chỉ `hat-control` đăng ký task watchdog: nếu task này
không chạy trong 5 giây, ESP32 khởi động lại và GPIO relay trở về trạng thái
an toàn.

## Build và nạp

```bash
cd firmware/esp32_hat
pio run
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor --port /dev/ttyUSB0 --baud 115200
```

Trên Windows thay cổng upload bằng `COMx`. Cổng USB CP2102 dùng UART0 cho
nạp và debug. Giao thức ứng dụng với Pi dùng UART2 tại GPIO16/17, vì vậy log
debug không lẫn vào các gói JSON.

## Chân và ngoại vi

| Chức năng | GPIO / địa chỉ |
| --- | --- |
| UART2 RX / TX | 16 / 17, 115200 8N1 |
| I²C SDA / SCL | 21 / 22, 100 kHz |
| SHT31 / BH1750 / ADS1115 | `0x44` / `0x23` / `0x48` |
| Cảm biến đất | ADS1115 A0, gain ±4,096 V |
| RL1 đèn / RL2 quạt / RL3 bơm | 27 / 26 / 25, active HIGH |
| SW6 Capture / SW3 Up / SW4 Select / SW5 Down | 35 / 34 / 36 / 39, active LOW |
| ILI9341 CS / RST / DC | 5 / 4 / 2 |
| ILI9341 MOSI / SCK / MISO | 23 / 18 / 19 |

`hat-sensors` đọc SHT31 (nhiệt độ và độ ẩm không khí) mỗi 2 s, BH1750 mỗi 3 s
và ADS1115/cảm biến đất mỗi 4 s. Lịch BH1750 và ADS1115 được lệch pha lúc
khởi động; các lượt đọc cảm biến bắt đầu cách nhau ít nhất 200 ms khi các chu kỳ
2/3/4 s gặp nhau. Telemetry UART vẫn phát mỗi 2 s và dùng giá trị đo mới nhất.

GPIO34–39 không có pull-up nội; bo mạch phải cung cấp điện trở kéo ngoài như
sơ đồ. Kiểm tra cực tính module relay bằng tải an toàn trước khi nối đèn,
quạt hoặc bơm thật.

## Hiệu chuẩn độ ẩm đất

Firmware mặc định đặt `SOIL_CALIBRATED=false`. Khi đó telemetry vẫn có
`soil_raw`, nhưng `soil=null` và AUTO không bật bơm. Để hiệu chuẩn:

1. Giữ đầu dò trong điều kiện khô đại diện và ghi `soil_raw`.
2. Đặt đầu dò trong điều kiện ướt đại diện và ghi `soil_raw`.
3. Điền hai số vào `SOIL_DRY_RAW` và `SOIL_WET_RAW` trong
   `include/hat_config.h`, đặt `SOIL_CALIBRATED=true` rồi build lại.
4. Kiểm tra chiều phần trăm và các ngưỡng trên chính đầu dò trước khi dùng AUTO.

Hai giá trị phải khác nhau và nằm trong miền single-ended `0..32767`.

## Hành vi an toàn

- Khởi động ở MANUAL với tất cả relay tắt.
- Mất heartbeat Pi trong 10 giây sẽ tắt relay và trở về MANUAL.
- Lỗi hoặc dữ liệu cảm biến quá hạn sẽ tắt tải tương ứng trong AUTO.
- Bơm bị giới hạn 30 giây mỗi lượt và nghỉ tối thiểu 60 giây, cả trong MANUAL.
- Nếu task watchdog không khởi tạo được, firmware từ chối lệnh và không cho
  nút OK vật lý bật relay.
- Task UART không sửa relay trực tiếp; ACK chỉ được gửi sau khi task điều khiển
  xử lý lệnh và trả trạng thái đầu ra thực qua queue.
- Lệnh trùng `id` trả lại kết quả đã lưu; dùng lại cùng `id` cho nội dung khác
  bị từ chối. Raspberry Pi không tự phát lại lệnh sau timeout.

Ngưỡng, timeout, địa chỉ và cực tính nằm trong `include/hat_config.h`. Giao
thức và API phía Pi được mô tả tại [`../../HAT_INTEGRATION.md`](../../HAT_INTEGRATION.md).

## Kiểm thử

Từ thư mục `Software`:

```bash
g++ -std=c++17 -Wall -Wextra -Werror \
  -I firmware/esp32_hat/include tests/test_hat_controller.cpp \
  -o /tmp/test_hat_controller
/tmp/test_hat_controller
pio run -d firmware/esp32_hat
```

Kiểm thử host xác nhận timeout heartbeat, hysteresis, khóa tưới khi chưa hiệu
chuẩn, giới hạn thời gian bơm và cooldown. Build PlatformIO kiểm tra toàn bộ
driver trên target ESP32.
