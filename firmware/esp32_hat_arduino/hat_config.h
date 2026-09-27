#pragma once
#include <stdint.h>
#include <stddef.h>

// Pinout: Hardware_V2/PCB_HAT.pdf, export 16 September 2026.
namespace Config {
constexpr uint32_t UART_BAUD = 115200;
constexpr uint8_t UART_RX = 16, UART_TX = 17;
constexpr uint8_t I2C_SDA = 21, I2C_SCL = 22;
constexpr uint32_t I2C_HZ = 100000;
constexpr uint16_t I2C_TIMEOUT_MS = 25;
constexpr uint8_t SHT31_ADDRESS = 0x44; // Change to 0x45 if ADDR is high.
constexpr uint8_t BH1750_ADDRESS = 0x23; // Change to 0x5C if ADDR is high.
constexpr uint8_t ADS1115_ADDRESS = 0x48;
constexpr uint8_t SOIL_ADC_CHANNEL = 0; // ADS1115 A0, gain +/-4.096 V.
constexpr uint8_t RELAY_PINS[] = {27, 26, 25}; // RL1 light, RL2 fan, RL3 pump.
constexpr bool RELAY_ACTIVE_HIGH = true;
// Logical order used by firmware: Capture, Up, Select, Down.
// PCB switches: SW6, SW3, SW4, SW5.
constexpr uint8_t BUTTON_PINS[] = {35, 34, 36, 39};
constexpr uint8_t TFT_CS = 5, TFT_RST = 4, TFT_DC = 2;
constexpr uint8_t TFT_MOSI = 23, TFT_SCK = 18, TFT_MISO = 19;
constexpr bool TFT_ENABLED = true;
constexpr uint32_t SHT_SAMPLE_MS = 2000, LIGHT_SAMPLE_MS = 3000, SOIL_SAMPLE_MS = 4000;
constexpr uint32_t LIGHT_START_OFFSET_MS = 350, SOIL_START_OFFSET_MS = 700;
constexpr uint32_t SENSOR_READ_GAP_MS = 200, TELEMETRY_MS = 2000;
constexpr uint32_t SENSOR_STALE_MS = 6000, SENSOR_RETRY_MS = 10000;
constexpr uint32_t HOST_TIMEOUT_MS = 10000;
  constexpr uint32_t BUTTON_DEBOUNCE_MS = 35, DISPLAY_MS = 200;
constexpr uint32_t WATCHDOG_SECONDS = 5;
constexpr size_t MAX_LINE_BYTES = 1024, RX_BYTES_PER_LOOP = 256;
constexpr size_t MAX_COMMAND_ID = 63, COMMAND_CACHE_SIZE = 16;
constexpr uint32_t CONTROL_COMMAND_TIMEOUT_MS = 500;
constexpr uint8_t COMMAND_QUEUE_LENGTH = 4, RESULT_QUEUE_LENGTH = 4, EVENT_QUEUE_LENGTH = 16;
constexpr uint32_t CONTROL_TASK_STACK = 4096, SENSOR_TASK_STACK = 4096;
constexpr uint32_t UART_TASK_STACK = 12288, TFT_TASK_STACK = 4096;
constexpr uint8_t CONTROL_TASK_PRIORITY = 4, UART_TASK_PRIORITY = 3;
constexpr uint8_t SENSOR_TASK_PRIORITY = 2, TFT_TASK_PRIORITY = 1;
constexpr int8_t CONTROL_TASK_CORE = 1, UART_TASK_CORE = 1;
constexpr int8_t SENSOR_TASK_CORE = 0, TFT_TASK_CORE = 0;

// MUST calibrate using soil_raw from telemetry before enabling automatic watering.
constexpr bool SOIL_CALIBRATED = false;
constexpr int16_t SOIL_DRY_RAW = 0; // Replace with actual measured dry reading.
constexpr int16_t SOIL_WET_RAW = 0; // Replace with actual measured wet reading.
constexpr float LIGHT_ON_LUX = 8000.0f, LIGHT_OFF_LUX = 15000.0f;
constexpr float FAN_ON_TEMP_C = 32.0f, FAN_OFF_TEMP_C = 29.0f;
constexpr float FAN_ON_RH = 85.0f, FAN_OFF_RH = 78.0f;
constexpr float PUMP_ON_SOIL = 30.0f, PUMP_OFF_SOIL = 45.0f;
constexpr uint32_t PUMP_MAX_ON_MS = 30000, PUMP_COOLDOWN_MS = 60000;
static_assert(SOIL_ADC_CHANNEL < 4, "ADS1115 channel must be 0..3");
static_assert(!SOIL_CALIBRATED || (SOIL_DRY_RAW != SOIL_WET_RAW &&
              SOIL_DRY_RAW > 0 && SOIL_WET_RAW > 0), "Set distinct positive soil calibration readings");
static_assert(LIGHT_ON_LUX < LIGHT_OFF_LUX && FAN_OFF_TEMP_C < FAN_ON_TEMP_C &&
              FAN_OFF_RH < FAN_ON_RH && PUMP_ON_SOIL < PUMP_OFF_SOIL,
              "Hysteresis thresholds have incorrect order");
}
