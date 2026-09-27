#include <Arduino.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <SPI.h>
#include <Adafruit_SHT31.h>
#include <BH1750.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>
#include <esp_idf_version.h>
#include <esp_task_wdt.h>
#include <freertos/FreeRTOS.h>
#include <freertos/event_groups.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>
#include <cmath>
#include <cstring>
#include "hat_config.h"
#include "control.h"

namespace {
constexpr EventBits_t TASKS_READY_BIT = BIT0;
constexpr TickType_t MUTEX_WAIT = pdMS_TO_TICKS(5);
constexpr TickType_t CONTROL_PERIOD = pdMS_TO_TICKS(10);
constexpr TickType_t UART_PERIOD = pdMS_TO_TICKS(2);
constexpr TickType_t SENSOR_PERIOD = pdMS_TO_TICKS(5);

enum class CommandKind : uint8_t { PING, RELAY, MODE, ACTION };
enum class UiPage : uint8_t { SYSTEM, MENU, RELAYS };

struct UiState {
  UiPage page = UiPage::SYSTEM;
  uint8_t menuSelection = 0;  // 0: system page, 1: relay page.
  uint8_t relayCursor = 0;    // 0..2: relays, 3: back.
};

struct ControlCommand {
  uint32_t token = 0;
  CommandKind kind = CommandKind::PING;
  uint8_t value = 0;
  bool state = false;
};

struct ControlResult {
  uint32_t token = 0;
  const char *error = nullptr;
  bool automatic = false;
  bool relays[3] = {false, false, false};
};

struct ButtonEvent { uint8_t button = 0; uint32_t uptime = 0; };

struct ControlSnapshot {
  bool automatic = false;
  bool relays[3] = {false, false, false};
  bool hostLive = false;
  bool hostTimedOut = false;
  bool pumpCooling = false;
  bool watchdogReady = false;
  uint8_t selectedRelay = 0;
  UiPage page = UiPage::SYSTEM;
  uint8_t menuSelection = 0;
  uint8_t relayCursor = 0;
};

struct ButtonState { bool raw = false, stable = false; uint32_t changedAt = 0; };

struct CachedCommand {
  char id[Config::MAX_COMMAND_ID + 1] = {};
  char signature[96] = {};
  ControlResult result;
};

HardwareSerial host(2);
Adafruit_SHT31 sht(&Wire);
BH1750 luxMeter;
Adafruit_ILI9341 tft(Config::TFT_CS, Config::TFT_DC, Config::TFT_RST);
SemaphoreHandle_t readingsMutex = nullptr, controlMutex = nullptr;
QueueHandle_t commandQueue = nullptr, resultQueue = nullptr, eventQueue = nullptr;
EventGroupHandle_t systemEvents = nullptr;
TaskHandle_t uartTaskHandle = nullptr;
Readings sharedReadings;
ControlSnapshot sharedControl;
bool watchdogInitialized = false;
const char *const relayNames[] = {"LIGHT", "FAN", "PUMP"};
const char *const buttonNames[] = {"capture", "up", "ok", "down"};

bool copyReadings(Readings &out) {
  if (xSemaphoreTake(readingsMutex, MUTEX_WAIT) != pdTRUE) return false;
  out = sharedReadings;
  xSemaphoreGive(readingsMutex);
  return true;
}

void publishReadings(const Readings &value) {
  if (xSemaphoreTake(readingsMutex, portMAX_DELAY) == pdTRUE) {
    sharedReadings = value;
    xSemaphoreGive(readingsMutex);
  }
  if (uartTaskHandle) xTaskNotifyGive(uartTaskHandle);
}

bool copyControl(ControlSnapshot &out) {
  if (xSemaphoreTake(controlMutex, MUTEX_WAIT) != pdTRUE) return false;
  out = sharedControl;
  xSemaphoreGive(controlMutex);
  return true;
}

bool sameControl(const ControlSnapshot &a, const ControlSnapshot &b) {
  return a.automatic == b.automatic && a.relays[0] == b.relays[0] &&
      a.relays[1] == b.relays[1] && a.relays[2] == b.relays[2] &&
      a.hostLive == b.hostLive && a.hostTimedOut == b.hostTimedOut &&
      a.pumpCooling == b.pumpCooling && a.watchdogReady == b.watchdogReady &&
      a.selectedRelay == b.selectedRelay && a.page == b.page &&
      a.menuSelection == b.menuSelection && a.relayCursor == b.relayCursor;
}

void publishControl(const ControlSnapshot &value) {
  bool changed = true;
  if (xSemaphoreTake(controlMutex, portMAX_DELAY) == pdTRUE) {
    changed = !sameControl(sharedControl, value);
    sharedControl = value;
    xSemaphoreGive(controlMutex);
  }
  if (changed && uartTaskHandle) xTaskNotifyGive(uartTaskHandle);
}

ControlResult resultFromSnapshot(const ControlSnapshot &state) {
  ControlResult result;
  result.automatic = state.automatic;
  for (uint8_t i = 0; i < 3; ++i) result.relays[i] = state.relays[i];
  return result;
}

void addOutputs(JsonDocument &doc, const ControlResult &state) {
  doc["mode"] = state.automatic ? "auto" : "manual";
  JsonObject relays = doc.createNestedObject("relays");
  relays["1"] = state.relays[0]; relays["2"] = state.relays[1]; relays["3"] = state.relays[2];
}

void sendJson(const JsonDocument &doc) {
  if (doc.overflowed() || measureJson(doc) > Config::MAX_LINE_BYTES) {
    Serial.println("JSON output overflow");
    return;
  }
  serializeJson(doc, host);
  host.write('\n');
}

void sendAck(const char *id, const ControlResult &result) {
  StaticJsonDocument<512> doc;
  doc["v"] = 1; doc["type"] = "ack"; doc["id"] = id; doc["ok"] = result.error == nullptr;
  if (result.error) doc["error"] = result.error;
  addOutputs(doc, result);
  sendJson(doc);
}

bool probe(uint8_t address) {
  Wire.beginTransmission(address);
  return Wire.endTransmission() == 0;
}

bool writeAds(uint8_t reg, uint16_t value) {
  Wire.beginTransmission(Config::ADS1115_ADDRESS);
  Wire.write(reg); Wire.write(uint8_t(value >> 8)); Wire.write(uint8_t(value));
  return Wire.endTransmission() == 0;
}

bool readAds(uint8_t reg, uint16_t &value) {
  Wire.beginTransmission(Config::ADS1115_ADDRESS); Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(Config::ADS1115_ADDRESS, uint8_t(2)) != 2) return false;
  value = uint16_t(Wire.read()) << 8; value |= uint8_t(Wire.read());
  return true;
}

void sensorTask(void *) {
  Wire.begin(Config::I2C_SDA, Config::I2C_SCL, Config::I2C_HZ);
  Wire.setTimeOut(Config::I2C_TIMEOUT_MS);
  Readings readings;
  bool shtStarted = false, lightStarted = false, adsPending = false;
  const uint32_t startedAt = millis();
  uint32_t nextShtAt = startedAt + Config::SHT_SAMPLE_MS;
  uint32_t nextLightAt = startedAt + Config::LIGHT_SAMPLE_MS + Config::LIGHT_START_OFFSET_MS;
  uint32_t nextAdsAt = startedAt + Config::SOIL_SAMPLE_MS + Config::SOIL_START_OFFSET_MS;
  uint32_t lastSensorAt = startedAt - Config::SENSOR_READ_GAP_MS;
  uint32_t retryAt = startedAt - Config::SENSOR_RETRY_MS;
  uint32_t adsStartedAt = 0, adsPolledAt = 0, lightStartedAt = 0;

  for (;;) {
    uint32_t now = millis();
    if (!adsPending && uint32_t(now - lastSensorAt) >= Config::SENSOR_READ_GAP_MS &&
        uint32_t(now - retryAt) >= Config::SENSOR_RETRY_MS) {
      bool attemptedProbe = false;
      if (!shtStarted) {
        attemptedProbe = true;
        if (probe(Config::SHT31_ADDRESS)) shtStarted = sht.begin(Config::SHT31_ADDRESS);
      }
      if (!lightStarted) {
        attemptedProbe = true;
        if (probe(Config::BH1750_ADDRESS)) {
          lightStarted = luxMeter.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, Config::BH1750_ADDRESS, &Wire);
          lightStartedAt = now;
        }
      }
      retryAt = now;
      if (attemptedProbe) now = lastSensorAt = millis();
    }
    // The fixed phase offsets avoid periodic 2/3/4-second collisions; the
    // gap also separates reads if task scheduling or a retry shifts a slot.
    if (!adsPending && uint32_t(now - lastSensorAt) >= Config::SENSOR_READ_GAP_MS &&
        int32_t(now - nextShtAt) >= 0) {
      nextShtAt += Config::SHT_SAMPLE_MS;
      if (int32_t(now - nextShtAt) >= 0) nextShtAt = now + Config::SHT_SAMPLE_MS;
      float temperature = NAN, humidity = NAN;
      readings.shtOk = shtStarted && sht.readBoth(&temperature, &humidity) &&
          std::isfinite(temperature) && std::isfinite(humidity) &&
          temperature >= -40 && temperature <= 125 && humidity >= 0 && humidity <= 100;
      if (readings.shtOk) {
        readings.temperature = temperature; readings.humidity = humidity; readings.shtAt = millis();
      } else shtStarted = false;
      lastSensorAt = millis();
      publishReadings(readings);
    } else if (!adsPending && uint32_t(now - lastSensorAt) >= Config::SENSOR_READ_GAP_MS &&
               int32_t(now - nextLightAt) >= 0) {
      nextLightAt += Config::LIGHT_SAMPLE_MS;
      if (int32_t(now - nextLightAt) >= 0) nextLightAt = now + Config::LIGHT_SAMPLE_MS;
      if (lightStarted && uint32_t(now - lightStartedAt) >= 180) {
        const float lux = luxMeter.readLightLevel();
        readings.lightOk = std::isfinite(lux) && lux >= 0 && lux <= 100000;
        if (readings.lightOk) { readings.light = lux; readings.lightAt = millis(); }
        else lightStarted = false;
      } else readings.lightOk = false;
      lastSensorAt = millis();
      publishReadings(readings);
    } else if (!adsPending && uint32_t(now - lastSensorAt) >= Config::SENSOR_READ_GAP_MS &&
               int32_t(now - nextAdsAt) >= 0) {
      nextAdsAt += Config::SOIL_SAMPLE_MS;
      if (int32_t(now - nextAdsAt) >= 0) nextAdsAt = now + Config::SOIL_SAMPLE_MS;
      const uint16_t config = 0x8000 | uint16_t(4 + Config::SOIL_ADC_CHANNEL) << 12 |
                              0x0200 | 0x0100 | 0x0080 | 0x0003;
      adsPending = writeAds(1, config);
      adsStartedAt = millis(); adsPolledAt = adsStartedAt;
      lastSensorAt = adsStartedAt;
      if (!adsPending) readings.adsOk = false;
      publishReadings(readings);
    }
    const uint32_t pollNow = millis();
    if (adsPending && uint32_t(pollNow - adsPolledAt) >= 10) {
      adsPolledAt = pollNow;
      uint16_t config = 0, raw = 0;
      if (!readAds(1, config) || uint32_t(pollNow - adsStartedAt) >= 150) {
        readings.adsOk = false; adsPending = false;
      } else if (config & 0x8000) {
        readings.adsOk = readAds(0, raw) && (raw & 0x8000u) == 0;
        adsPending = false;
        if (readings.adsOk) {
          readings.soilRaw = int16_t(raw); readings.adsAt = pollNow;
          if (Config::SOIL_CALIBRATED) {
            const float span = float(Config::SOIL_WET_RAW) - Config::SOIL_DRY_RAW;
            readings.soil = fmaxf(0.0f, fminf(100.0f,
                100.0f * (readings.soilRaw - Config::SOIL_DRY_RAW) / span));
          }
        }
      }
      publishReadings(readings);
    }
    vTaskDelay(SENSOR_PERIOD);
  }
}

void writeRelays(const Controller &controller) {
  for (uint8_t i = 0; i < 3; ++i) {
    const bool level = controller.relays[i] == Config::RELAY_ACTIVE_HIGH;
    digitalWrite(Config::RELAY_PINS[i], level ? HIGH : LOW);
  }
}

ControlSnapshot makeSnapshot(const Controller &controller, const UiState &ui,
                             uint8_t selectedRelay,
                             bool watchdogReady, uint32_t now) {
  ControlSnapshot value;
  value.automatic = controller.automatic;
  for (uint8_t i = 0; i < 3; ++i) value.relays[i] = controller.relays[i];
  value.hostLive = controller.hostLive(now); value.hostTimedOut = controller.hostTimedOut;
  value.pumpCooling = controller.cooling(now); value.watchdogReady = watchdogReady;
  value.selectedRelay = selectedRelay;
  value.page = ui.page;
  value.menuSelection = ui.menuSelection;
  value.relayCursor = ui.relayCursor;
  return value;
}

const char *applyButton(Controller &controller, UiState &ui, uint8_t &selectedRelay,
                        uint8_t button, uint32_t now, bool watchdogReady) {
  bool nextRelayState = false;
  const bool togglesRelay = button == 2 && ui.page == UiPage::RELAYS && ui.relayCursor < 3;
  if (togglesRelay) {
    if (!watchdogReady) return "watchdog_unavailable";
    if (controller.automatic) return "manual_mode_required";
    nextRelayState = !controller.relays[ui.relayCursor];
    if (ui.relayCursor == 2 && nextRelayState && controller.cooling(now)) return "pump_cooldown";
  }
  ButtonEvent event;
  event.button = button;
  event.uptime = now;
  if (xQueueSend(eventQueue, &event, 0) != pdTRUE) return "event_queue_full";
  if (button == 1) {
    if (ui.page == UiPage::MENU) ui.menuSelection = (ui.menuSelection + 1) % 2;
    else if (ui.page == UiPage::RELAYS) {
      ui.relayCursor = (ui.relayCursor + 3) % 4;
      if (ui.relayCursor < 3) selectedRelay = ui.relayCursor;
    }
  } else if (button == 3) {
    if (ui.page == UiPage::MENU) ui.menuSelection = (ui.menuSelection + 1) % 2;
    else if (ui.page == UiPage::RELAYS) {
      ui.relayCursor = (ui.relayCursor + 1) % 4;
      if (ui.relayCursor < 3) selectedRelay = ui.relayCursor;
    }
  } else if (button == 2) {
    if (ui.page == UiPage::SYSTEM) ui.page = UiPage::MENU;
    else if (ui.page == UiPage::MENU) {
      ui.page = ui.menuSelection == 0 ? UiPage::SYSTEM : UiPage::RELAYS;
      if (ui.page == UiPage::RELAYS) ui.relayCursor = selectedRelay;
    } else if (ui.relayCursor == 3) ui.page = UiPage::MENU;
    else if (!controller.setRelay(ui.relayCursor, nextRelayState, now)) return "pump_cooldown";
  }
  return nullptr;
}

ControlResult executeCommand(Controller &controller, UiState &ui, uint8_t &selectedRelay,
                             const ControlCommand &command, bool watchdogReady, uint32_t now) {
  ControlResult result;
  result.token = command.token;
  if (command.kind == CommandKind::PING) controller.ping(now);
  else if (!watchdogReady) result.error = "watchdog_unavailable";
  else if (!controller.hostLive(now)) result.error = "host_offline";
  else if (command.kind == CommandKind::RELAY) {
    if (controller.automatic) result.error = "manual_mode_required";
    else if (!controller.setRelay(command.value, command.state, now)) result.error = "pump_cooldown";
  } else if (command.kind == CommandKind::MODE) controller.setMode(command.state, now);
  else result.error = applyButton(controller, ui, selectedRelay, command.value, now, watchdogReady);
  result.automatic = controller.automatic;
  for (uint8_t i = 0; i < 3; ++i) result.relays[i] = controller.relays[i];
  return result;
}

void controlTask(void *) {
  Controller controller;
  ButtonState buttons[4];
  UiState ui;
  uint8_t selectedRelay = 0;
  const bool watchdogReady = watchdogInitialized && esp_task_wdt_add(nullptr) == ESP_OK;
  TickType_t wakeAt = xTaskGetTickCount();
  for (const auto pin : Config::BUTTON_PINS) pinMode(pin, INPUT);
  publishControl(makeSnapshot(controller, ui, selectedRelay, watchdogReady, millis()));

  for (;;) {
    const uint32_t now = millis();
    if ((xEventGroupGetBits(systemEvents) & TASKS_READY_BIT) == 0) {
      controller.setMode(false, now); controller.allOff(now);
    }
    ControlCommand command;
    while (xQueueReceive(commandQueue, &command, 0) == pdTRUE) {
      ControlResult result = executeCommand(controller, ui, selectedRelay, command, watchdogReady, millis());
      Readings commandReadings;
      copyReadings(commandReadings);
      controller.tick(millis(), commandReadings);
      writeRelays(controller);
      result.automatic = controller.automatic;
      for (uint8_t i = 0; i < 3; ++i) result.relays[i] = controller.relays[i];
      xQueueSend(resultQueue, &result, 0);
    }
    for (uint8_t i = 0; i < 4; ++i) {
      const bool pressed = digitalRead(Config::BUTTON_PINS[i]) == LOW;
      ButtonState &button = buttons[i];
      if (pressed != button.raw) { button.raw = pressed; button.changedAt = now; }
      if (button.stable != button.raw && uint32_t(now - button.changedAt) >= Config::BUTTON_DEBOUNCE_MS) {
        button.stable = button.raw;
        if (button.stable) {
          const char *error = applyButton(controller, ui, selectedRelay, i, now, watchdogReady);
          if (error) Serial.println(error);
        }
      }
    }
    Readings readings;
    copyReadings(readings);
    controller.tick(now, readings);
    writeRelays(controller);
    publishControl(makeSnapshot(controller, ui, selectedRelay, watchdogReady, now));
    if (watchdogReady) esp_task_wdt_reset();
    vTaskDelayUntil(&wakeAt, CONTROL_PERIOD);
  }
}

bool validId(const char *id) {
  if (!id) return false;
  const size_t length = strlen(id);
  if (!length || length > Config::MAX_COMMAND_ID) return false;
  for (size_t i = 0; i < length; ++i) if (id[i] < 33 || id[i] > 126) return false;
  return true;
}

ControlResult currentResult(const char *error = nullptr) {
  ControlSnapshot snapshot;
  copyControl(snapshot);
  ControlResult result = resultFromSnapshot(snapshot);
  result.error = error;
  return result;
}

ControlResult dispatchCommand(const ControlCommand &command) {
  if (xQueueSend(commandQueue, &command, pdMS_TO_TICKS(20)) != pdTRUE)
    return currentResult("control_busy");
  const TickType_t started = xTaskGetTickCount();
  ControlResult result;
  for (;;) {
    const TickType_t elapsed = xTaskGetTickCount() - started;
    if (elapsed >= pdMS_TO_TICKS(Config::CONTROL_COMMAND_TIMEOUT_MS))
      return currentResult("control_timeout");
    const TickType_t remaining = pdMS_TO_TICKS(Config::CONTROL_COMMAND_TIMEOUT_MS) - elapsed;
    if (xQueueReceive(resultQueue, &result, remaining) != pdTRUE)
      return currentResult("control_timeout");
    if (result.token == command.token) return result;
  }
}

void processCommand(char *line, size_t length, CachedCommand *cache,
                    size_t &cacheNext, uint32_t &commandToken, uint32_t &malformedCount) {
  StaticJsonDocument<1536> doc;
  const auto parseError = deserializeJson(doc, line, length, DeserializationOption::NestingLimit(4));
  if (parseError || !doc.is<JsonObject>()) { ++malformedCount; return; }
  JsonObject object = doc.as<JsonObject>();
  const char *id = object["id"].is<const char *>() ? object["id"].as<const char *>() : nullptr;
  if (!validId(id)) { ++malformedCount; return; }
  if (!object["v"].is<int>() || object["v"].as<int>() != 1 ||
      !object["type"].is<const char *>() || strcmp(object["type"], "command") ||
      !object["command"].is<const char *>()) {
    sendAck(id, currentResult("invalid_command")); return;
  }
  const char *name = object["command"];
  ControlCommand command;
  command.token = ++commandToken;
  char signature[96] = {};
  bool cacheable = true;
  if (!strcmp(name, "ping")) {
    command.kind = CommandKind::PING; cacheable = false;
  } else if (!strcmp(name, "set_relay")) {
    if (!object["relay"].is<int>() || object["relay"].as<int>() < 1 ||
        object["relay"].as<int>() > 3 || !object["state"].is<bool>()) {
      sendAck(id, currentResult("invalid_relay")); return;
    }
    command.kind = CommandKind::RELAY;
    command.value = object["relay"].as<uint8_t>() - 1;
    command.state = object["state"].as<bool>();
    snprintf(signature, sizeof(signature), "relay:%u:%u", command.value, command.state);
  } else if (!strcmp(name, "set_mode")) {
    const char *mode = object["mode"].is<const char *>() ? object["mode"].as<const char *>() : "";
    if (strcmp(mode, "manual") && strcmp(mode, "auto")) {
      sendAck(id, currentResult("invalid_mode")); return;
    }
    command.kind = CommandKind::MODE; command.state = !strcmp(mode, "auto");
    snprintf(signature, sizeof(signature), "mode:%u", command.state);
  } else if (!strcmp(name, "action")) {
    const char *action = object["action"].is<const char *>() ? object["action"].as<const char *>() : "";
    uint8_t index = 0;
    for (; index < 4 && strcmp(action, buttonNames[index]); ++index) {}
    if (index >= 4) { sendAck(id, currentResult("invalid_action")); return; }
    command.kind = CommandKind::ACTION; command.value = index;
    snprintf(signature, sizeof(signature), "action:%u", index);
  } else {
    sendAck(id, currentResult("unknown_command")); return;
  }
  if (cacheable) {
    for (size_t i = 0; i < Config::COMMAND_CACHE_SIZE; ++i) {
      if (!strcmp(cache[i].id, id)) {
        sendAck(id, strcmp(cache[i].signature, signature) ? currentResult("id_reused") : cache[i].result);
        return;
      }
    }
  }
  ControlResult result = dispatchCommand(command);
  sendAck(id, result);
  if (cacheable) {
    CachedCommand &entry = cache[cacheNext];
    strncpy(entry.id, id, sizeof(entry.id) - 1); entry.id[sizeof(entry.id) - 1] = 0;
    strncpy(entry.signature, signature, sizeof(entry.signature) - 1);
    entry.signature[sizeof(entry.signature) - 1] = 0;
    entry.result = result;
    cacheNext = (cacheNext + 1) % Config::COMMAND_CACHE_SIZE;
  }
}

void sendButtonEvent(const ButtonEvent &event, uint32_t &sequence) {
  StaticJsonDocument<256> doc;
  doc["v"] = 1; doc["type"] = "event"; doc["seq"] = ++sequence;
  doc["uptime_ms"] = event.uptime; doc["event"] = "button";
  doc["button"] = buttonNames[event.button];
  sendJson(doc);
}

void sendTelemetry(uint32_t now, uint32_t &sequence, uint32_t malformedCount) {
  Readings readings;
  ControlSnapshot control;
  copyReadings(readings); copyControl(control);
  StaticJsonDocument<1536> doc;
  doc["v"] = 1; doc["type"] = "telemetry"; doc["seq"] = ++sequence;
  doc["uptime_ms"] = now; doc["selected_relay"] = control.selectedRelay + 1;
  doc["ui_page"] = control.page == UiPage::SYSTEM ? "system" :
                   control.page == UiPage::MENU ? "menu" : "relays";
  addOutputs(doc, resultFromSnapshot(control));
  JsonObject sensors = doc.createNestedObject("sensors");
  sensors["temp"] = nullptr; sensors["humidity"] = nullptr; sensors["light"] = nullptr;
  sensors["soil"] = nullptr; sensors["soil_raw"] = nullptr;
  if (readings.shtFresh(now)) { sensors["temp"] = readings.temperature; sensors["humidity"] = readings.humidity; }
  if (readings.lightFresh(now)) sensors["light"] = readings.light;
  if (readings.adsFresh(now)) sensors["soil_raw"] = readings.soilRaw;
  if (readings.soilFresh(now)) sensors["soil"] = readings.soil;
  JsonObject ok = doc.createNestedObject("sensor_ok");
  ok["sht31"] = readings.shtFresh(now); ok["bh1750"] = readings.lightFresh(now);
  ok["ads1115"] = readings.adsFresh(now); ok["soil_calibrated"] = Config::SOIL_CALIBRATED;
  JsonArray errors = doc.createNestedArray("errors");
  if (!readings.shtFresh(now)) errors.add("sht31_unavailable");
  if (!readings.lightFresh(now)) errors.add("bh1750_unavailable");
  if (!readings.adsFresh(now)) errors.add("ads1115_unavailable");
  if (!Config::SOIL_CALIBRATED) errors.add("soil_not_calibrated");
  if (!control.hostLive) errors.add("host_offline");
  if (control.pumpCooling) errors.add("pump_cooldown");
  if (!control.watchdogReady) errors.add("watchdog_unavailable");
  if (malformedCount) errors.add("uart_invalid_frames");
  doc["uart_invalid_frames"] = malformedCount;
  sendJson(doc);
}

void uartTask(void *) {
  host.setRxBufferSize(2048);
  host.begin(Config::UART_BAUD, SERIAL_8N1, Config::UART_RX, Config::UART_TX);
  char rxLine[Config::MAX_LINE_BYTES + 1] = {};
  size_t rxUsed = 0, cacheNext = 0;
  bool droppingLine = false, telemetryDirty = true;
  CachedCommand cache[Config::COMMAND_CACHE_SIZE];
  uint32_t commandToken = 0, sequence = 0, malformedCount = 0, telemetryAt = 0;
  xEventGroupWaitBits(systemEvents, TASKS_READY_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
  for (;;) {
    size_t budget = Config::RX_BYTES_PER_LOOP;
    while (budget-- && host.available()) {
      const char value = char(host.read());
      if (value == '\n') {
        if (!droppingLine && rxUsed) {
          rxLine[rxUsed] = 0;
          processCommand(rxLine, rxUsed, cache, cacheNext, commandToken, malformedCount);
        }
        rxUsed = 0; droppingLine = false; break;
      }
      if (droppingLine || value == '\r') continue;
      if (value == 0 || rxUsed >= Config::MAX_LINE_BYTES) {
        droppingLine = true; rxUsed = 0; ++malformedCount;
      } else rxLine[rxUsed++] = value;
    }
    ButtonEvent event;
    while (xQueueReceive(eventQueue, &event, 0) == pdTRUE) sendButtonEvent(event, sequence);
    if (ulTaskNotifyTake(pdTRUE, 0) > 0) telemetryDirty = true;
    const uint32_t now = millis();
    if ((telemetryDirty && uint32_t(now - telemetryAt) >= 100) ||
        uint32_t(now - telemetryAt) >= Config::TELEMETRY_MS) {
      sendTelemetry(now, sequence, malformedCount);
      telemetryAt = now; telemetryDirty = false;
    }
    vTaskDelay(UART_PERIOD);
  }
}

void tftTask(void *) {
  pinMode(Config::TFT_RST, OUTPUT);
  digitalWrite(Config::TFT_RST, LOW);
  vTaskDelay(pdMS_TO_TICKS(20));
  digitalWrite(Config::TFT_RST, HIGH);
  vTaskDelay(pdMS_TO_TICKS(150));
  SPI.begin(Config::TFT_SCK, Config::TFT_MISO, Config::TFT_MOSI, Config::TFT_CS);
  tft.begin(10000000); tft.setRotation(1); tft.fillScreen(ILI9341_BLACK);
  UiPage drawnPage = static_cast<UiPage>(0xFF);
  bool hostDrawn = false, drawnHostLive = false;
  uint32_t drawnSystemSecond = UINT32_MAX;
  uint8_t drawnMenuSelection = 0xFF, drawnRelayCursor = 0xFF;
  bool relayStatesDrawn = false;
  bool drawnRelayStates[3] = {};
  TickType_t wakeAt = xTaskGetTickCount();
  for (;;) {
    const uint32_t now = millis();
    Readings readings;
    ControlSnapshot control;
    copyReadings(readings); copyControl(control);
    const bool pageChanged = control.page != drawnPage;
    if (pageChanged) {
      drawnPage = control.page;
      tft.fillScreen(ILI9341_BLACK);
      tft.fillRect(0, 0, 320, 27, ILI9341_DARKCYAN);
      tft.setTextSize(2); tft.setTextColor(ILI9341_WHITE, ILI9341_DARKCYAN);
      tft.setCursor(7, 6); tft.print("TOMATOGUARD");
      hostDrawn = false;
      drawnSystemSecond = UINT32_MAX;
      drawnMenuSelection = 0xFF;
      drawnRelayCursor = 0xFF;
      relayStatesDrawn = false;
    }
    if (!hostDrawn || drawnHostLive != control.hostLive) {
      tft.fillRect(240, 0, 80, 27, ILI9341_DARKCYAN);
      tft.setTextSize(1); tft.setTextColor(ILI9341_WHITE, ILI9341_DARKCYAN);
      tft.setCursor(246, 9);
      tft.print(control.hostLive ? "PI ONLINE " : "PI OFFLINE");
      drawnHostLive = control.hostLive;
      hostDrawn = true;
    }

    if (control.page == UiPage::SYSTEM) {
      if (pageChanged) {
        tft.setTextSize(2); tft.setTextColor(ILI9341_CYAN, ILI9341_BLACK);
        tft.setCursor(8, 34); tft.print("PAGE 1 - SYSTEM");
        tft.drawRoundRect(85, 188, 150, 38, 6, ILI9341_YELLOW);
        tft.setTextColor(ILI9341_YELLOW, ILI9341_BLACK);
        tft.setCursor(112, 199); tft.print("< BACK [SW4]");
      }
      const uint32_t systemSecond = now / 1000;
      if (drawnSystemSecond != systemSecond) {
        drawnSystemSecond = systemSecond;
        tft.fillRect(0, 55, 320, 115, ILI9341_BLACK);
        tft.setTextSize(2); tft.setTextColor(ILI9341_WHITE, ILI9341_BLACK);
        tft.setCursor(8, 61);
        if (readings.shtFresh(now)) tft.printf("TEMP: %.1f C", readings.temperature);
        else tft.print("TEMP: -- C");
        tft.setCursor(168, 61);
        if (readings.shtFresh(now)) tft.printf("RH: %.1f%%", readings.humidity);
        else tft.print("RH: --%%");
        tft.setCursor(8, 88);
        if (readings.lightFresh(now)) tft.printf("LIGHT: %.0f lux", readings.light);
        else tft.print("LIGHT: -- lux");
        tft.setCursor(8, 115);
        if (readings.soilFresh(now)) tft.printf("SOIL: %.1f%%", readings.soil);
        else if (readings.adsFresh(now)) tft.printf("SOIL RAW: %d", readings.soilRaw);
        else tft.print("SOIL: --");
        tft.setCursor(8, 142); tft.printf("MODE: %s", control.automatic ? "AUTO" : "MANUAL");
        tft.setCursor(168, 142); tft.printf("UP: %lus", static_cast<unsigned long>(systemSecond));
      }
    } else if (control.page == UiPage::MENU) {
      if (pageChanged) {
        tft.setTextSize(2); tft.setTextColor(ILI9341_CYAN, ILI9341_BLACK);
        tft.setCursor(8, 36); tft.print("SELECT PAGE");
        tft.setTextSize(1); tft.setTextColor(ILI9341_CYAN, ILI9341_BLACK);
        tft.setCursor(43, 190); tft.print("SW3 UP   SW5 DOWN   SW4 SELECT");
        tft.setCursor(75, 211); tft.print("SW6 CAPTURE CAMERA");
      }
      if (drawnMenuSelection != control.menuSelection) {
        const char *items[] = {"PAGE 1  SYSTEM", "PAGE 2  RELAYS"};
        for (uint8_t i = 0; i < 2; ++i) {
          const int16_t y = 67 + i * 55;
          const uint16_t color = i == control.menuSelection ? ILI9341_YELLOW : ILI9341_WHITE;
          tft.fillRoundRect(22, y - 2, 276, 44, 6, ILI9341_BLACK);
          tft.drawRoundRect(24, y, 272, 40, 6, color);
          tft.setTextSize(2); tft.setTextColor(color, ILI9341_BLACK);
          tft.setCursor(40, y + 11);
          tft.printf("%c %s", i == control.menuSelection ? '>' : ' ', items[i]);
        }
        drawnMenuSelection = control.menuSelection;
      }
    } else {
      if (pageChanged) {
        tft.setTextSize(2); tft.setTextColor(ILI9341_CYAN, ILI9341_BLACK);
        tft.setCursor(8, 33); tft.print("PAGE 2 - RELAYS");
        tft.setTextSize(1); tft.setTextColor(ILI9341_CYAN, ILI9341_BLACK);
        tft.setCursor(35, 225); tft.print("SW3 UP  SW5 DOWN  SW4 ON/OFF  SW6 CAP");
      }
      bool relayDirty = !relayStatesDrawn || drawnRelayCursor != control.relayCursor;
      for (uint8_t i = 0; i < 3; ++i) relayDirty |= drawnRelayStates[i] != control.relays[i];
      if (relayDirty) {
        for (uint8_t i = 0; i < 3; ++i) {
          const bool selected = control.relayCursor == i;
          const uint16_t color = selected ? ILI9341_YELLOW : ILI9341_WHITE;
          const int16_t y = 58 + i * 40;
          tft.fillRoundRect(12, y - 2, 296, 36, 5, ILI9341_BLACK);
          tft.drawRoundRect(14, y, 292, 32, 5, color);
          tft.setTextSize(2); tft.setTextColor(color, ILI9341_BLACK);
          tft.setCursor(24, y + 8);
          tft.printf("%c RL%u %-5s", selected ? '>' : ' ', i + 1, relayNames[i]);
          tft.setTextColor(control.relays[i] ? ILI9341_GREEN : ILI9341_RED, ILI9341_BLACK);
          tft.setCursor(242, y + 8); tft.print(control.relays[i] ? "ON " : "OFF");
          drawnRelayStates[i] = control.relays[i];
        }
        const bool backSelected = control.relayCursor == 3;
        const uint16_t backColor = backSelected ? ILI9341_YELLOW : ILI9341_WHITE;
        tft.fillRoundRect(83, 182, 154, 35, 5, ILI9341_BLACK);
        tft.drawRoundRect(85, 184, 150, 31, 5, backColor);
        tft.setTextSize(2); tft.setTextColor(backColor, ILI9341_BLACK);
        tft.setCursor(111, 192); tft.printf("%c BACK", backSelected ? '>' : ' ');
        drawnRelayCursor = control.relayCursor;
        relayStatesDrawn = true;
      }
    }
    vTaskDelayUntil(&wakeAt, pdMS_TO_TICKS(Config::DISPLAY_MS));
  }
}

bool createTasks() {
  bool ok = xTaskCreatePinnedToCore(controlTask, "hat-control", Config::CONTROL_TASK_STACK,
      nullptr, Config::CONTROL_TASK_PRIORITY, nullptr, Config::CONTROL_TASK_CORE) == pdPASS;
  ok = ok && xTaskCreatePinnedToCore(sensorTask, "hat-sensors", Config::SENSOR_TASK_STACK,
      nullptr, Config::SENSOR_TASK_PRIORITY, nullptr, Config::SENSOR_TASK_CORE) == pdPASS;
  ok = ok && xTaskCreatePinnedToCore(uartTask, "hat-uart", Config::UART_TASK_STACK,
      nullptr, Config::UART_TASK_PRIORITY, &uartTaskHandle, Config::UART_TASK_CORE) == pdPASS;
  if (Config::TFT_ENABLED)
    ok = ok && xTaskCreatePinnedToCore(tftTask, "hat-tft", Config::TFT_TASK_STACK,
        nullptr, Config::TFT_TASK_PRIORITY, nullptr, Config::TFT_TASK_CORE) == pdPASS;
  return ok;
}
}  // namespace

void setup() {
  for (const auto pin : Config::RELAY_PINS) {
    digitalWrite(pin, Config::RELAY_ACTIVE_HIGH ? LOW : HIGH);
    pinMode(pin, OUTPUT);
  }
  Serial.begin(115200);
  readingsMutex = xSemaphoreCreateMutex(); controlMutex = xSemaphoreCreateMutex();
  commandQueue = xQueueCreate(Config::COMMAND_QUEUE_LENGTH, sizeof(ControlCommand));
  resultQueue = xQueueCreate(Config::RESULT_QUEUE_LENGTH, sizeof(ControlResult));
  eventQueue = xQueueCreate(Config::EVENT_QUEUE_LENGTH, sizeof(ButtonEvent));
  systemEvents = xEventGroupCreate();
#if ESP_IDF_VERSION_MAJOR >= 5
  esp_task_wdt_config_t watchdogConfig = {};
  watchdogConfig.timeout_ms = Config::WATCHDOG_SECONDS * 1000U;
  watchdogConfig.idle_core_mask = 0;
  watchdogConfig.trigger_panic = true;
  const esp_err_t watchdogStatus = esp_task_wdt_init(&watchdogConfig);
#else
  const esp_err_t watchdogStatus = esp_task_wdt_init(Config::WATCHDOG_SECONDS, true);
#endif
  // Arduino/ESP-IDF builds may initialize TWDT before setup(). In that case
  // subscribing hat-control is still valid and uses the configured 5 s timeout.
  watchdogInitialized = watchdogStatus == ESP_OK || watchdogStatus == ESP_ERR_INVALID_STATE;
  const bool resourcesReady = readingsMutex && controlMutex && commandQueue &&
      resultQueue && eventQueue && systemEvents;
  if (!resourcesReady || !createTasks()) {
    Serial.println("FATAL: cannot create HAT FreeRTOS resources");
    delay(2000); ESP.restart(); return;
  }
  xEventGroupSetBits(systemEvents, TASKS_READY_BIT);
  Serial.println("HAT ready: four FreeRTOS tasks, UART2 115200, MANUAL, relays OFF");
}

void loop() {
  vTaskDelete(nullptr);
}
