#include <Arduino.h>
#include <Wire.h>

// ESP32 NodeMCU (ESP32-WROOM-32): SDA=GPIO21, SCL=GPIO22.
// ADS1115: VDD->3V3, GND->GND, SDA->GPIO21, SCL->GPIO22, ADDR->GND.
// Soil sensor: VCC->3V3, GND->common GND, AOUT->ADS1115 A0.
// Do not connect the soil sensor's DOUT pin for this test.
// Open Serial Monitor at 115200 baud. Send d in dry soil, w in wet soil.
// This sketch is independent of the HAT firmware and uses only Wire.

constexpr uint8_t SDA_PIN = 21;
constexpr uint8_t SCL_PIN = 22;
constexpr uint32_t I2C_CLOCK_HZ = 100000;
constexpr uint32_t PRINT_INTERVAL_MS = 2000;
constexpr uint8_t ADS_ADDRESS_MIN = 0x48;
constexpr uint8_t ADS_ADDRESS_MAX = 0x4B;
constexpr uint8_t ADS_CONFIG_REGISTER = 0x01;
constexpr uint8_t ADS_CONVERSION_REGISTER = 0x00;
constexpr uint16_t ADS_A0_SINGLE_SHOT = 0xC383;
// 0xC383: start conversion, AIN0-GND, +/-4.096 V, single-shot,
// 128 samples/s, comparator disabled. One count = 4.096/32768 V.

uint8_t adsAddress = 0;
int16_t lastRaw = 0;
bool hasSample = false;
int16_t dryRaw = 0;
int16_t wetRaw = 0;
bool hasDry = false;
bool hasWet = false;
uint32_t lastPrintAt = 0;

bool writeRegister(uint8_t address, uint8_t reg, uint16_t value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  Wire.write(static_cast<uint8_t>(value >> 8));
  Wire.write(static_cast<uint8_t>(value));
  return Wire.endTransmission() == 0;
}

bool readRegister(uint8_t address, uint8_t reg, uint16_t &value) {
  Wire.beginTransmission(address);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(address, static_cast<uint8_t>(2)) != 2) return false;
  value = static_cast<uint16_t>(Wire.read()) << 8;
  value |= static_cast<uint8_t>(Wire.read());
  return true;
}

uint8_t scanBus() {
  uint8_t foundAds = 0;
  Serial.println("I2C scan:");
  for (uint8_t address = 0x08; address <= 0x77; ++address) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() != 0) continue;
    Serial.printf("  Found 0x%02X\n", address);
    if (address >= ADS_ADDRESS_MIN && address <= ADS_ADDRESS_MAX) {
      if (foundAds == 0 || address == ADS_ADDRESS_MIN) foundAds = address;
    }
  }
  if (foundAds == 0) {
    Serial.println("ADS1115 not found (expected 0x48 if ADDR is GND).");
  } else {
    Serial.printf("Using ADS1115 candidate at 0x%02X\n", foundAds);
    if (foundAds != 0x48) Serial.println("Check ADDR: HAT firmware expects 0x48.");
  }
  return foundAds;
}

bool readSoilA0(int16_t &raw) {
  if (!writeRegister(adsAddress, ADS_CONFIG_REGISTER, ADS_A0_SINGLE_SHOT)) {
    Serial.println("ADS write failed (I2C).");
    return false;
  }

  const uint32_t startedAt = millis();
  uint16_t config = 0;
  do {
    delay(2);
    if (!readRegister(adsAddress, ADS_CONFIG_REGISTER, config)) {
      Serial.println("ADS config read failed (I2C).");
      return false;
    }
    if (config & 0x8000) {
      uint16_t data = 0;
      if (!readRegister(adsAddress, ADS_CONVERSION_REGISTER, data)) {
        Serial.println("ADS conversion read failed (I2C).");
        return false;
      }
      raw = static_cast<int16_t>(data);
      return true;
    }
  } while (millis() - startedAt < 100);

  Serial.println("ADS conversion timeout.");
  return false;
}

void printSample() {
  if (adsAddress == 0) adsAddress = scanBus();
  if (adsAddress == 0) return;

  // Average several fresh conversions to make dry/wet comparisons clearer.
  int32_t sum = 0;
  uint8_t samples = 0;
  for (uint8_t i = 0; i < 8; ++i) {
    int16_t raw = 0;
    if (!readSoilA0(raw)) {
      adsAddress = 0; // Scan again next time if the module disconnects.
      hasSample = false;
      return;
    }
    sum += raw;
    ++samples;
  }
  lastRaw = static_cast<int16_t>(sum / samples);
  hasSample = true;
  const float voltage = lastRaw * (4.096f / 32768.0f);
  Serial.printf("A0 raw=%d  voltage=%.3f V", lastRaw, voltage);

  if (hasDry && hasWet && dryRaw != wetRaw) {
    float percent = 100.0f * (lastRaw - dryRaw) / (wetRaw - dryRaw);
    if (percent < 0.0f) percent = 0.0f;
    if (percent > 100.0f) percent = 100.0f;
    Serial.printf("  soil=%.1f%% (temporary calibration)", percent);
  }
  Serial.println();
  if (voltage < -0.05f || voltage > 3.35f) {
    Serial.println("Check AOUT and common GND: A0 should stay within 0..3.3 V.");
  }
}

void handleSerial() {
  while (Serial.available()) {
    const char command = static_cast<char>(Serial.read());
    if (command != 'd' && command != 'D' && command != 'w' && command != 'W') continue;
    if (!hasSample) {
      Serial.println("Wait for a valid A0 reading before setting dry/wet.");
      continue;
    }
    if (command == 'd' || command == 'D') {
      dryRaw = lastRaw;
      hasDry = true;
      Serial.printf("DRY_RAW=%d\n", dryRaw);
    } else {
      wetRaw = lastRaw;
      hasWet = true;
      Serial.printf("WET_RAW=%d\n", wetRaw);
    }
    if (hasDry && hasWet && dryRaw == wetRaw) {
      Serial.println("Dry and wet values are identical: check AOUT, sensor power, and contact with water/soil.");
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(800);
  Wire.begin(SDA_PIN, SCL_PIN, I2C_CLOCK_HZ);
  Wire.setTimeOut(50);
  Serial.println("ADS1115 + soil sensor test, ESP32 NodeMCU");
  Serial.println("Commands: d = save dry raw, w = save wet raw.");
  adsAddress = scanBus();
  lastPrintAt = millis() - PRINT_INTERVAL_MS;
}

void loop() {
  handleSerial();
  const uint32_t now = millis();
  if (now - lastPrintAt >= PRINT_INTERVAL_MS) {
    lastPrintAt = now;
    printSample();
  }
}
