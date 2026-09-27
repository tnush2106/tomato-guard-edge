# Đưa TomatoGuard lên `tvhuynh.click` bằng Raspberry Pi

> Cập nhật 26/09/2026: `tvhuynh.click` đã dùng nameserver Cloudflare
> (`casey.ns.cloudflare.com`, `sydney.ns.cloudflare.com`). Không cần thêm lại
> tên miền hoặc đổi nameserver. Tạo Cloudflare Tunnel và route đến web trên Pi.
> Trong giao diện hiện tại, vào **Networking > Tunnels**; route web nằm ở
> **Routes > Add route > Published application**. Bảo vệ dashboard bằng
> **Zero Trust > Access controls > Applications** trước khi chia sẻ công khai.

## Kiến trúc khuyến nghị

```text
Trình duyệt
    │ HTTPS + đăng nhập Cloudflare Access
    ▼
tvhuynh.click / Cloudflare
    │ Cloudflare Tunnel (kết nối đi ra từ Pi)
    ▼
127.0.0.1:5000 / Flask trên Raspberry Pi
    ├── Camera + YOLO NCNN
    └── UART / ESP32 HAT
```

Cách này không cần IP tĩnh, không cần NAT port forwarding và vẫn dùng được khi
đường truyền nằm sau CGNAT. Không công khai trực tiếp cổng 5000.

## 1. Chuẩn bị ứng dụng trên Pi

Nếu dashboard đã mở được ở `http://<IP-Pi>:5000`, chỉ cần chạy lệnh `curl` để
xác nhận rồi cài dịch vụ; không chạy lại `setup_realtime.sh` và không ghi đè
`.env` đang chứa cấu hình/API key của bạn.

Trong thư mục dự án:

```bash
cd ~/DATN/Software  # Đổi lại nếu bạn đặt dự án ở thư mục khác
bash setup_realtime.sh  # Chỉ dùng khi Pi chưa được cài ứng dụng
test -f .env || cp .env.example .env
nano .env                 # Chỉ chỉnh những giá trị còn thiếu
```

Điền API key và kiểm tra `MODEL_PATH`, `HAT_SERIAL_PORT`. Không đưa tệp `.env`
lên Git.

Thiết lập tài khoản đăng nhập lần đầu trên Pi (mật khẩu được nhập ẩn và chỉ lưu
bản băm trong `.env`):

```bash
./venv/bin/python deploy/set_dashboard_password.py
```

Nếu cần tài khoản khởi tạo đúng `admin / admin` để thử trước, chạy
`./venv/bin/python deploy/set_dashboard_password.py --demo-default`. Đổi mật
khẩu bằng lệnh không có `--demo-default` ngay sau khi kiểm tra đăng nhập,
đặc biệt trước khi chia sẻ tên miền.

Mỗi lần đổi mật khẩu, chạy lại lệnh trên rồi `sudo systemctl restart tomatoguard`.
Cookie đăng nhập mặc định chỉ hoạt động qua HTTPS tại tên miền. Nếu cần thử
trực tiếp qua `http://IP-Pi:5000` trong LAN, đặt `DASHBOARD_COOKIE_SECURE=0`
trong `.env` rồi khởi động lại ứng dụng; đặt lại `1` trước khi dùng tên miền.

Chạy thử:

```bash
./run_web.sh
```

Từ một terminal khác trên Pi:

```bash
curl http://127.0.0.1:5000/healthz
```

Nếu có phản hồi JSON, dừng tiến trình thử bằng `Ctrl+C` rồi cài dịch vụ:

```bash
bash deploy/install_pi_service.sh
sudo systemctl status tomatoguard --no-pager
```

## 2. Kiểm tra DNS của tên miền

`tvhuynh.click` đã dùng nameserver Cloudflare. Trong Cloudflare Dashboard, kiểm
tra zone báo **Active**. Chỉ cần thực hiện các bước đổi nameserver bên dưới nếu
zone không còn Active hoặc bạn triển khai một tên miền khác.

1. Tạo tài khoản Cloudflare và chọn **Add a domain**.
2. Nhập `tvhuynh.click`, chọn gói Free.
3. Cloudflare cấp hai nameserver. Vào trang quản lý nơi đã mua tên miền và thay
   nameserver hiện tại bằng đúng hai nameserver này.
4. Nếu DNSSEC đang bật ở nhà đăng ký, tắt trước khi đổi nameserver. Sau khi tên
   miền báo **Active**, có thể bật lại DNSSEC trong Cloudflare.

Không tự tạo bản ghi A trỏ đến IP nhà khi sử dụng Tunnel. Tunnel sẽ tạo bản ghi
DNS phù hợp khi cấu hình public hostname.

## 3. Tạo Cloudflare Tunnel

Trong Cloudflare Dashboard, mở **Networking > Tunnels**:

1. Chọn **Create a tunnel**, đặt tên `tomatoguard-pi`.
2. Chọn connector `cloudflared`.
3. Chọn hệ điều hành Debian, kiến trúc ARM64 nếu Pi chạy Raspberry Pi OS 64-bit.
4. Sao chép nguyên lệnh cài đặt có token do dashboard cung cấp và chạy trên Pi.
   Lệnh có dạng:

   ```bash
   sudo cloudflared service install <TUNNEL_TOKEN>
   ```

   Tunnel token là bí mật. Không chụp/gửi ảnh chứa nguyên lệnh có token.
   Nếu token đã lộ: vào tunnel > **Rotate token**, dừng mọi lệnh `tunnel run`
   thủ công, rồi cài lại dịch vụ trên Pi bằng token mới theo
   [hướng dẫn Cloudflare](https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/).
   Khi đã cài dịch vụ, không cần chạy thêm `cloudflared tunnel run --token ...`.

5. Trước khi thêm route, tạo Cloudflare Access Application ở mục 4 để bảo vệ
   các API điều khiển relay. Khi connector đã kết nối, mở tunnel >
   **Routes > Add route > Published application** và nhập:

   - Subdomain: để trống
   - Domain: `tvhuynh.click`
   - Type: `HTTP`
   - Service URL: `http://localhost:5000`

6. Lưu route và kiểm tra connector có trạng thái **Healthy**. Nếu Cloudflare báo
   hostname đã có DNS record, kiểm tra DNS record cũ trước khi tạo route mới;
   không tạo hai bản ghi trùng tên `tvhuynh.click`.

Hướng dẫn chính thức: [tạo Tunnel bằng dashboard](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/).

Có thể thêm hostname `www.tvhuynh.click` trỏ đến cùng dịch vụ nếu muốn dùng
cả địa chỉ `www`.

## 4. Bắt buộc bảo vệ trang điều khiển

Dashboard có endpoint bật/tắt đèn, quạt và bơm. Trước khi chia sẻ tên miền, tạo
Cloudflare Access Application:

1. Mở **Zero Trust > Access controls > Applications > Create new application**.
2. Chọn **Self-hosted and private > Add public hostname** và dùng
   `tvhuynh.click`.
3. Tạo policy **Allow**, chỉ cho phép email của chủ hệ thống.
4. Chọn đăng nhập bằng mã dùng một lần qua email hoặc nhà cung cấp danh tính.
5. Không tạo policy `Bypass` cho toàn bộ hostname.

Cookie Access hoạt động cùng nguồn với dashboard, nên các request `/video` và
`/api/...` từ trang web vẫn hoạt động sau khi người dùng đăng nhập.

Hướng dẫn chính thức: [ứng dụng Access self-hosted](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/).

## 5. Kiểm tra vận hành

```bash
systemctl is-active tomatoguard
systemctl is-active cloudflared
curl http://127.0.0.1:5000/healthz
journalctl -u tomatoguard -n 100 --no-pager
journalctl -u cloudflared -n 100 --no-pager
```

Sau đó mở `https://tvhuynh.click` bằng mạng 4G/5G để kiểm tra từ bên ngoài.
HTTPS được Cloudflare cấp ở phía tên miền; không cần cài Certbot trên Pi khi dùng
Tunnel.

## Nếu muốn trỏ DNS trực tiếp về Pi

Chỉ dùng phương án này khi router có IPv4 công cộng thật. So sánh WAN IP trên
router với kết quả `curl -4 ifconfig.me`; nếu khác nhau thì nhiều khả năng đang
dùng CGNAT và không thể port forward trực tiếp.

Khi có IPv4 công cộng, cần đồng thời:

1. Tạo bản ghi `A` cho `@` trỏ đến public IP.
2. Cấu hình DDNS nếu public IP thay đổi.
3. Forward TCP 80 và 443 từ router đến Pi.
4. Dùng Nginx reverse proxy đến `127.0.0.1:5000` và cấp TLS bằng Certbot.
5. Thêm xác thực trước toàn bộ dashboard và API điều khiển.

Không forward cổng 5000 và không công khai SSH cổng 22 ra Internet.
