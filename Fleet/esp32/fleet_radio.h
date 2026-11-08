// fleet_radio.h - WiFi or Bluetooth: one radio at a time, so an ESP32 robot has the RAM for it.
//
// The master copy is RIFT/Fleet/esp32/fleet_radio.h; every ESP32 robot carries it byte for byte (like
// fleet_bt.h). WiFi, Bluedroid's Classic Bluetooth (fleet_bt.h) and its Bluetooth LE (fleet_near_ble.h)
// all at once don't fit in an ESP32's heap: NORA had 3.7 KB left after them and rebooted forever
// (176 KB at start, WiFi took 52, BLE 89, Classic 22). So it's one or the other, chosen on RIFT:
//
//   WiFi (the default)  WiFi only, no Bluetooth at all; ESP-NOW says who's near (fleet_near.h)
//   Bluetooth           no WiFi at all: the web API over Classic Bluetooth (fleet_bt.h), and the BLE
//                       beacon says who's near instead of ESP-NOW (fleet_near_ble.h). The lesser
//                       robots (MILA, NIKA: ESP8266s, WiFi only) are out of the fleet then.
//
// RIFT puts the whole fleet back on WiFi every time it starts.
//
//   GET /radio                               {"radio":"wifi"|"bluetooth"}  (anyone may look)
//   GET /radio?mode=bluetooth&pw=<PIN>       saves it and restarts on Bluetooth (over WiFi)
//   GET /radio?mode=wifi&pw=<PIN>            saves it and restarts on WiFi (sent over Bluetooth:
//                                            fleet_bt replays it to this same web server)
//
// The choice is kept in NVS ("radio"/"bt"), so a restart keeps it. In setup():
//
//     fleetRadioBegin();                     // first thing: on WiFi it hands Bluetooth's RAM back
//     if (fleetRadioWifi()) setupWiFi();     // the robot's own WiFi start (and fleetNearBegin)
//     else fleetRadioNoWifi();               // the network stack with no radio: fleet_bt asks 127.0.0.1
//     ...
//     fleetRadioRoutes(server, CONTROL_PIN); // with the robot's other routes
//     if (fleetRadioBluetooth()) { fleetBtBegin("NAME", port); fleetNearBleBegin("NAME"); }
//
// and in loop() fleetNearLoop() on WiFi, fleetNearBleLoop() on Bluetooth; anything else that needs
// WiFi (registering with RIFT, a fleet list) only on WiFi.
#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_bt.h>

namespace fleetradio {
bool bt = false;
}

inline bool fleetRadioBluetooth() { return fleetradio::bt; }
inline bool fleetRadioWifi() { return !fleetradio::bt; }

inline void fleetRadioBegin() {
  Preferences p;
  p.begin("radio", true);
  fleetradio::bt = p.getBool("bt", false);
  p.end();
  // On WiFi nothing starts Bluetooth before the next restart, so its controller's reserved RAM
  // (tens of KB) goes back to the heap. Linking BluetoothSerial / BLE keeps the core from doing it.
  if (!fleetradio::bt) esp_bt_controller_mem_release(ESP_BT_MODE_BTDM);
}

// Bluetooth: WiFi stays off, but the network stack (lwIP) still starts, so the robot's web server
// listens and fleet_bt can replay each request to it on 127.0.0.1.
inline void fleetRadioNoWifi() {
  WiFi.mode(WIFI_OFF);
  Network.begin();
}

// Save the radio and restart into it (after the answer has gone out)
inline void fleetRadioSet(bool bluetooth) {
  Preferences p;
  p.begin("radio", false);
  p.putBool("bt", bluetooth);
  p.end();
}

inline void fleetRadioRoutes(WebServer& server, const char* pin) {
  server.on("/radio", [&server, pin]() {
    const String mode = server.arg("mode");
    if (!mode.length()) {
      server.send(200, "application/json", String("{\"radio\":\"") + (fleetradio::bt ? "bluetooth" : "wifi") + "\"}");
      return;
    }
    if (mode != "wifi" && mode != "bluetooth") { server.send(400, "application/json", "{\"ok\":false,\"error\":\"mode is wifi or bluetooth\"}"); return; }
    if (server.arg("pw") != pin) { server.send(403, "application/json", "{\"ok\":false,\"error\":\"bad pin\"}"); return; }
    const bool want = mode == "bluetooth";
    if (want == fleetradio::bt) { server.send(200, "application/json", "{\"ok\":true,\"radio\":\"" + mode + "\",\"restarting\":false}"); return; }
    fleetRadioSet(want);
    server.send(200, "application/json", "{\"ok\":true,\"radio\":\"" + mode + "\",\"restarting\":true}");
    delay(600);   // let the answer leave (WiFi or Bluetooth) before the radio goes
    ESP.restart();
  });
}
