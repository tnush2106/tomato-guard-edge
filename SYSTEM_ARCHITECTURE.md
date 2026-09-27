# Flowchart kiến trúc tổng thể TomatoGuard Edge

```mermaid
flowchart TB
    USER["Người dùng<br/>Điện thoại hoặc máy tính"]

    subgraph ACCESS["Lớp truy cập"]
        LOCAL["Mạng LAN<br/>http://IP-Pi:5000"]
        DOMAIN["Tên miền tvhuynh.click<br/>HTTPS"]
        CF["Cloudflare DNS và Tunnel"]
        DOMAIN --> CF
    end

    USER --> LOCAL
    USER --> DOMAIN

    subgraph PI["Raspberry Pi 4B - Edge Host"]
        WEB["Flask Web API và Dashboard<br/>app_pi_realtime.py"]
        CAMSVC["Dịch vụ Camera AI"]
        YOLO["YOLO NCNN<br/>Nhận diện bệnh cây"]
        CHAT["Trợ lý AI nông học<br/>Router và các Agent"]
        RAG["RAG / FAISS<br/>Kho tri thức bệnh học"]
        LLM["OpenRouter hoặc OpenAI hoặc Gemini"]
        SEARCH["Tavily Web Search"]
        HATSVC["HAT Service<br/>Heartbeat, telemetry, command"]
        SERIAL["UART Pi /dev/serial0<br/>115200 baud, 3.3 V"]
        STORAGE["Thẻ nhớ Pi<br/>Model, ảnh chụp, nhật ký"]

        WEB <--> CAMSVC
        WEB <--> CHAT
        WEB <--> HATSVC
        CAMSVC --> YOLO
        YOLO --> WEB
        CAMSVC --> STORAGE
        CHAT <--> RAG
        CHAT <--> LLM
        CHAT <--> SEARCH
        HATSVC <--> SERIAL
        WEB --> STORAGE
    end

    LOCAL <--> WEB
    CF <--> WEB

    CAMERA["Raspberry Pi Camera"] --> CAMSVC

    subgraph ESP["ESP32 HAT - Bộ điều khiển thời gian thực"]
        UART2["UART2 Task<br/>GPIO16 RX, GPIO17 TX"]
        CONTROL["Control Task<br/>MANUAL / AUTO"]
        SENSOR_TASK["Sensor Task<br/>I2C GPIO21/22"]
        DISPLAY["TFT Task<br/>SPI ILI9341"]

        UART2 <--> CONTROL
        SENSOR_TASK --> CONTROL
        CONTROL --> DISPLAY
    end

    SERIAL <-->|"JSON mỗi dòng<br/>Telemetry, ACK, command, heartbeat"| UART2

    subgraph INPUTS["Cảm biến và đầu vào"]
        SHT31["SHT31<br/>Nhiệt độ và độ ẩm không khí"]
        BH1750["BH1750<br/>Cường độ ánh sáng"]
        ADS["ADS1115<br/>ADC 16 bit"]
        SOIL["Cảm biến độ ẩm đất<br/>Analog OUT"]
        BUTTONS["SW3 / SW4 / SW5 / SW6<br/>Điều hướng, chọn, chụp ảnh"]

        SOIL -->|"A0"| ADS
    end

    SHT31 -->|"I2C"| SENSOR_TASK
    BH1750 -->|"I2C"| SENSOR_TASK
    ADS -->|"I2C"| SENSOR_TASK
    BUTTONS -->|"GPIO active LOW"| CONTROL

    subgraph OUTPUTS["Hiển thị và cơ cấu chấp hành"]
        TFT["TFT ILI9341 3.2 inch<br/>Thông số, menu, relay"]
        DRIVER["Mạch transistor và relay"]
        RL1["RL1 - Đèn"]
        RL2["RL2 - Quạt"]
        RL3["RL3 - Bơm"]

        DRIVER --> RL1
        DRIVER --> RL2
        DRIVER --> RL3
    end

    DISPLAY -->|"SPI"| TFT
    CONTROL -->|"GPIO27 / GPIO26 / GPIO25"| DRIVER
    BUTTONS -. "Sự kiện Capture" .-> UART2
    UART2 -. "Yêu cầu chụp ảnh" .-> HATSVC
    HATSVC -.-> CAMSVC

    classDef user fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e;
    classDef pi fill:#ecfdf5,stroke:#059669,color:#064e3b;
    classDef esp fill:#fff7ed,stroke:#ea580c,color:#7c2d12;
    classDef io fill:#f8fafc,stroke:#64748b,color:#0f172a;
    classDef cloud fill:#f5f3ff,stroke:#7c3aed,color:#4c1d95;

    class USER user;
    class WEB,CAMSVC,YOLO,CHAT,RAG,HATSVC,SERIAL,STORAGE pi;
    class UART2,CONTROL,SENSOR_TASK,DISPLAY esp;
    class SHT31,BH1750,ADS,SOIL,BUTTONS,TFT,DRIVER,RL1,RL2,RL3,CAMERA io;
    class DOMAIN,CF,LLM,SEARCH cloud;
```

## Luồng hoạt động chính

1. ESP32 đọc cảm biến qua I2C, xử lý nút nhấn, điều khiển relay và cập nhật TFT.
2. ESP32 và Raspberry Pi trao đổi JSON qua UART 115200 baud; Pi gửi heartbeat và lệnh, ESP32 gửi telemetry và ACK.
3. Raspberry Pi xử lý hình ảnh camera bằng model YOLO NCNN, lưu ảnh và kết quả trên thẻ nhớ.
4. Flask cung cấp dashboard và API trong mạng LAN hoặc qua tên miền Cloudflare.
5. Chatbot kết hợp dữ liệu trạm, kho tri thức FAISS, LLM và Tavily để tư vấn nông học.
6. Khi nhấn Capture, sự kiện đi từ ESP32 sang Pi; Pi chụp ảnh camera và lưu vào thẻ nhớ.

