#include <cassert>
#include "control.h"

int main() {
  constexpr uint32_t now = 1000;
  Readings readings;
  readings.shtOk = readings.lightOk = readings.adsOk = true;
  readings.shtAt = readings.lightAt = readings.adsAt = now;
  readings.temperature = Config::FAN_ON_TEMP_C;
  readings.humidity = 50.0f;
  readings.light = Config::LIGHT_ON_LUX;
  readings.soil = 0.0f;

  Controller automatic;
  automatic.ping(now);
  automatic.setMode(true, now);
  automatic.tick(now, readings);
  assert(automatic.relays[0]);
  assert(automatic.relays[1]);
  assert(!automatic.relays[2]);  // Soil calibration is deliberately disabled.

  readings.temperature = (Config::FAN_ON_TEMP_C + Config::FAN_OFF_TEMP_C) / 2.0f;
  readings.light = (Config::LIGHT_ON_LUX + Config::LIGHT_OFF_LUX) / 2.0f;
  automatic.tick(now + 1, readings);
  assert(automatic.relays[0] && automatic.relays[1]);  // Hysteresis retains state.

  readings.temperature = Config::FAN_OFF_TEMP_C;
  readings.humidity = Config::FAN_OFF_RH;
  readings.light = Config::LIGHT_OFF_LUX;
  automatic.tick(now + 2, readings);
  assert(!automatic.relays[0] && !automatic.relays[1]);

  automatic.setRelay(0, true, now + 3);
  automatic.tick(now + Config::HOST_TIMEOUT_MS, readings);
  assert(!automatic.relays[0] && !automatic.automatic && automatic.hostTimedOut);

  Controller pump;
  pump.ping(now);
  assert(pump.setRelay(2, true, now));
  pump.tick(now + Config::PUMP_MAX_ON_MS, readings);
  assert(!pump.relays[2] && pump.cooling(now + Config::PUMP_MAX_ON_MS));
  assert(!pump.setRelay(2, true, now + Config::PUMP_MAX_ON_MS + 1));
  pump.ping(now + Config::PUMP_MAX_ON_MS + Config::PUMP_COOLDOWN_MS);
  assert(pump.setRelay(2, true, now + Config::PUMP_MAX_ON_MS + Config::PUMP_COOLDOWN_MS));
}
