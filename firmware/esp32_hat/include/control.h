#pragma once
#include "hat_config.h"

// Hardware-independent controller; all state is owned by Arduino loop().
struct Readings {
  float temperature = 0, humidity = 0, light = 0, soil = 0;
  int16_t soilRaw = 0;
  bool shtOk = false, lightOk = false, adsOk = false;
  uint32_t shtAt = 0, lightAt = 0, adsAt = 0;
  bool shtFresh(uint32_t now) const { return shtOk && uint32_t(now-shtAt) < Config::SENSOR_STALE_MS; }
  bool lightFresh(uint32_t now) const { return lightOk && uint32_t(now-lightAt) < Config::SENSOR_STALE_MS; }
  bool adsFresh(uint32_t now) const { return adsOk && uint32_t(now-adsAt) < Config::SENSOR_STALE_MS; }
  bool soilFresh(uint32_t now) const { return Config::SOIL_CALIBRATED && adsFresh(now); }
};

struct Controller {
  bool relays[3] = {false, false, false};
  bool automatic = false, hostSeen = false, hostTimedOut = false;
  bool pumpCooling = false;
  uint32_t lastHost = 0, pumpStarted = 0, pumpStopped = 0;
  bool hostLive(uint32_t now) const {
    return hostSeen && uint32_t(now-lastHost) < Config::HOST_TIMEOUT_MS;
  }
  void ping(uint32_t now) { hostSeen = true; lastHost = now; hostTimedOut = false; }
  bool cooling(uint32_t now) const {
    return pumpCooling && uint32_t(now-pumpStopped) < Config::PUMP_COOLDOWN_MS;
  }
  bool setRelay(uint8_t index, bool state, uint32_t now) {
    // Local buttons must remain usable while the Raspberry Pi is offline.
    // UART/web commands are guarded by hostLive() before they reach here.
    if (index >= 3) return false;
    if (index == 2 && state && !relays[2] && cooling(now)) return false;
    if (relays[index] == state) return true;
    relays[index] = state;
    if (index == 2) {
      if (state) pumpStarted = now;
      else { pumpStopped = now; pumpCooling = true; }
    }
    return true;
  }
  void allOff(uint32_t now) { for (uint8_t i=0; i<3; ++i) setRelay(i, false, now); }
  void setMode(bool autoMode, uint32_t now) {
    // Entering either mode resets outputs. Repeating the current mode is a no-op.
    if (automatic != autoMode) { allOff(now); automatic = autoMode; }
  }
  void tick(uint32_t now, const Readings &s) {
    if (pumpCooling && !cooling(now)) pumpCooling = false;
    if (!hostLive(now)) {
      automatic = false;
      // Fail safe once when an active Pi connection times out. Afterwards the
      // physical buttons may control relays locally while the Pi stays offline.
      if (hostSeen && !hostTimedOut) {
        allOff(now);
        hostTimedOut = true;
      }
      return;
    }
    // This limit applies in MANUAL as well as AUTO; repeated ON never resets it.
    if (relays[2] && uint32_t(now-pumpStarted) >= Config::PUMP_MAX_ON_MS)
      setRelay(2, false, now);
    if (!automatic) return;
    if (!s.lightFresh(now)) setRelay(0, false, now);
    else if (s.light <= Config::LIGHT_ON_LUX) setRelay(0, true, now);
    else if (s.light >= Config::LIGHT_OFF_LUX) setRelay(0, false, now);
    if (!s.shtFresh(now)) setRelay(1, false, now);
    else if (s.temperature >= Config::FAN_ON_TEMP_C || s.humidity >= Config::FAN_ON_RH)
      setRelay(1, true, now);
    else if (s.temperature <= Config::FAN_OFF_TEMP_C && s.humidity <= Config::FAN_OFF_RH)
      setRelay(1, false, now);
    if (!s.soilFresh(now)) setRelay(2, false, now);
    else if (s.soil <= Config::PUMP_ON_SOIL) setRelay(2, true, now);
    else if (s.soil >= Config::PUMP_OFF_SOIL) setRelay(2, false, now);
  }
};
