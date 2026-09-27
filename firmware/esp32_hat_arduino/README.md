# Arduino IDE upload sketch

Open `esp32_hat_arduino.ino` in Arduino IDE. The IDE will compile `main.cpp`
and the two local headers from the same sketch directory.

## Board configuration

- Boards Manager package: **esp32 by Espressif Systems 2.0.17 or newer**
- Board: **ESP32 Dev Module**
- Port: **COM7**
- Upload Speed: **115200**
- Flash Mode: **DIO**
- Flash Frequency: **40 MHz**
- Partition Scheme: **Default 4MB with spiffs**

## Libraries

Install these with Library Manager:

- ArduinoJson 6.21.5
- Adafruit SHT31 Library 2.2.2
- BH1750 1.3.0
- Adafruit GFX Library 1.11.11
- Adafruit ILI9341 1.6.2
- Adafruit BusIO 1.16.2

`Wire`, `SPI`, and FreeRTOS are supplied by the ESP32 board package.

## CH340 wiring

Use 3.3 V UART logic and power the ESP32 separately:

```text
CH340 TXD -> ESP32 GPIO3 / RX0
CH340 RXD <- ESP32 GPIO1 / TX0
CH340 GND -- ESP32 GND
CH340 VCC -- not connected
```

To enter the ROM bootloader, hold BOOT, press and release EN, then keep BOOT
held until Arduino IDE changes from `Connecting...` to `Writing at...`.

After upload, release BOOT and press EN once. At 115200 baud, UART0 prints:

```text
HAT ready: four FreeRTOS tasks, UART2 115200, MANUAL, relays OFF
```

Application communication with Raspberry Pi remains on UART2 GPIO16/17.

## Sensor timing

SHT31 updates temperature and air humidity every 2 seconds; BH1750 updates
light every 3 seconds; ADS1115 samples soil moisture every 4 seconds. Startup
offsets and a 200 ms gap between sensor reads keep them separate. UART telemetry
still sends the latest available values every 2 seconds.

## TFT controls

- Page 1 shows Pi status, mode, uptime, temperature, humidity, light and soil.
- Select `BACK` with SW4 to open the page menu.
- SW3 moves up, SW5 moves down, and SW4 selects a page or toggles the
  highlighted relay on Page 2.
- SW6 always sends a camera capture event to Raspberry Pi. The Pi application
  stores the latest camera frame under `Software/captures/` on Pi storage.
