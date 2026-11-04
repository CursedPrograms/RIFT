// fleet_bt_ble.h - the fleet's one Bluetooth protocol (fleet_bt.h) over Bluetooth LE, for robots whose
// chip has no Classic Bluetooth (ESP32-C3 / S3) or whose Bluetooth is already BLE (ARIA).
//
// The master copy is RIFT/Fleet/esp32/fleet_bt_ble.h; robots carry it byte for byte. The same lines as
// fleet_bt.h, carried by the standard "Nordic UART" service (any BLE serial tool speaks it):
//
//     write to RX  (6E400002-...)   >GET /status\n
//     notified on TX (6E400003-...)  <code> <length>\n<body>   (in pieces of up to 180 bytes)
//
// Python's side: fleet_bt.BtSession("ble:ARIA") (bleak). A robot can limit what Bluetooth may ask
// (ARIA: only /status, /near, /ping, /chirp: flying stays on her paired app):
//
//     static const char* const ALLOWED[] = { "/status", "/near", "/ping", "/chirp", nullptr };
//     fleetBtBleAttach(server, 5014, ALLOWED);   // into the robot's existing BLEServer, before advertising
//
// It answers from its own task (core 0, low priority), so a request never holds up the robot's loop.
#pragma once
#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLE2902.h>
#include <HTTPClient.h>

#define FLEET_NUS_SERVICE "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
#define FLEET_NUS_RX      "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
#define FLEET_NUS_TX      "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

namespace fleetble {

BLECharacteristic* tx = nullptr;
uint16_t webPort = 80;
const char* const* allowed = nullptr;   // nullptr: everything on webPort
QueueHandle_t lines = nullptr;           // whole request lines, for the task
String partial;

bool permitted(const String& path) {
  if (!allowed) return true;
  String bare = path.substring(0, path.indexOf('?') < 0 ? path.length() : path.indexOf('?'));
  for (int i = 0; allowed[i]; i++) if (bare == allowed[i]) return true;
  return false;
}

void send(const String& data) {
  for (size_t i = 0; i < data.length(); i += 180) {
    const String part = data.substring(i, min(data.length(), (unsigned)(i + 180)));
    tx->setValue((uint8_t*)part.c_str(), part.length());
    tx->notify();
    vTaskDelay(pdMS_TO_TICKS(8));       // let each piece go out
  }
}

void answer(int code, const String& body) { send(String(code) + " " + body.length() + "\n" + body); }

void request(String line) {
  line.trim();
  const int sp = line.indexOf(' ');
  if (sp < 0) { answer(400, "bad request"); return; }
  const String method = line.substring(0, sp);
  String rest = line.substring(sp + 1), body;
  const int tab = rest.indexOf('\t');
  if (tab >= 0) { body = rest.substring(tab + 1); rest = rest.substring(0, tab); }
  if (!rest.startsWith("/")) { answer(400, "bad path"); return; }   // its own port only: no ":<port>" here
  if (!permitted(rest)) { answer(403, "not over Bluetooth"); return; }
  HTTPClient http;
  http.begin("http://127.0.0.1:" + String(webPort) + rest);
  http.setTimeout(3000);
  const int code = method == "POST" ? http.POST(body) : http.GET();
  answer(code > 0 ? code : 502, code > 0 ? http.getString() : String("no answer from its web server"));
  http.end();
}

void task(void*) {
  char* line = nullptr;
  for (;;) {
    if (xQueueReceive(lines, &line, portMAX_DELAY) == pdTRUE && line) {
      request(String(line));
      free(line);
    }
  }
}

class Rx : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* c) override {
    const String chunk = String((const char*)c->getData(), c->getLength());
    for (size_t i = 0; i < chunk.length(); i++) {
      const char ch = chunk[i];
      if (ch == '\n') {
        if (partial.startsWith(">") && partial.length() > 1) {
          char* copy = strdup(partial.c_str() + 1);
          if (copy && xQueueSend(lines, &copy, 0) != pdTRUE) free(copy);
        }
        partial = "";
      } else if (ch != '\r' && partial.length() < 1024) {
        partial += ch;
      }
    }
  }
};

}  // namespace fleetble

// Adds the fleet's Bluetooth to a robot's BLE server (call before it starts advertising)
inline void fleetBtBleAttach(BLEServer* server, uint16_t port, const char* const* allowed = nullptr) {
  fleetble::webPort = port;
  fleetble::allowed = allowed;
  fleetble::lines = xQueueCreate(4, sizeof(char*));
  BLEService* s = server->createService(FLEET_NUS_SERVICE);
  BLECharacteristic* rx = s->createCharacteristic(FLEET_NUS_RX, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR);
  fleetble::tx = s->createCharacteristic(FLEET_NUS_TX, BLECharacteristic::PROPERTY_NOTIFY);
  fleetble::tx->addDescriptor(new BLE2902());
  rx->setCallbacks(new fleetble::Rx());
  s->start();
  BLEDevice::getAdvertising()->addServiceUUID(FLEET_NUS_SERVICE);
  xTaskCreatePinnedToCore(fleetble::task, "fleet-ble", 6144, nullptr, 1, nullptr, 0);
}
