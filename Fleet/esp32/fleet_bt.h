// fleet_bt.h - Bluetooth as equal as WiFi: a robot's whole web API over Bluetooth serial.
//
// The master copy is RIFT/Fleet/esp32/fleet_bt.h; every ESP32 robot carries it byte for byte (like
// fleet_near.h). Python's side, for the Pi robots and every controller: RIFT/Fleet/fleet_bt.py.
//
// The robot shows up as a Bluetooth serial device named after it ("WHIP"). A controller sends one
// line per request, exactly what it would ask over WiFi:
//
//     >GET /web?cmd=drive&f=1&l=0&t=0
//     >POST /command<TAB>{"command":"forward"}
//     >GET :5000/robots                (another of its ports: NORA's fleet list)
//
// This is the fleet's one Bluetooth protocol: every robot speaks it, NORA too.
// and the robot asks its own web server (127.0.0.1, its port) and answers:
//
//     <code> <length>\n<body: exactly that many bytes>
//
// So every command works the same both ways, including ones added later, and the same rules hold:
// a controller unlocks with the PIN (over Bluetooth it's "127.0.0.1"), the robot's own stops hold.
// A line that doesn't start with '>' is ignored (left for an older one-letter protocol, like NORA's).
//
//     fleetBtBegin("WHIP", 5005);    // in setup(), after the web server has started
//
// It runs in its own task on core 0, so a request waits for the web server without stopping the
// robot's loop (which is what answers it).
#pragma once
#include <Arduino.h>
#include <BluetoothSerial.h>
#include <HTTPClient.h>

namespace fleetbt {

BluetoothSerial link;
uint16_t webPort = 80;
const size_t MAX_LINE = 1024;

void answer(int code, const String& body) {
  link.print(code);
  link.print(' ');
  link.print(body.length());
  link.print('\n');
  link.print(body);
}

void request(String line) {
  line.trim();
  const int sp = line.indexOf(' ');
  if (sp < 0) { answer(400, "bad request"); return; }
  const String method = line.substring(0, sp);
  String rest = line.substring(sp + 1), body;
  const int tab = rest.indexOf('\t');
  if (tab >= 0) { body = rest.substring(tab + 1); rest = rest.substring(0, tab); }
  uint16_t port = webPort;
  if (rest.startsWith(":") && rest.indexOf('/') > 1) {   // ":5000/robots": another of its ports (NORA's fleet list)
    port = rest.substring(1, rest.indexOf('/')).toInt();
    rest = rest.substring(rest.indexOf('/'));
  }
  if (!rest.startsWith("/") || !port) { answer(400, "bad path"); return; }
  HTTPClient http;
  http.begin("http://127.0.0.1:" + String(port) + rest);
  http.setTimeout(4000);
  int code;
  if (method == "POST") {
    http.addHeader("Content-Type", body.startsWith("{") ? "application/json" : "application/x-www-form-urlencoded");
    code = http.POST(body);
  } else {
    code = http.GET();
  }
  answer(code > 0 ? code : 502, code > 0 ? http.getString() : String("no answer from its web server"));
  http.end();
}

void task(void*) {
  String line;
  bool mine = false;   // this line started with '>'
  for (;;) {
    while (link.available()) {
      const char c = link.read();
      if (c == '\n') {
        if (mine) request(line);
        line = ""; mine = false;
      } else if (c == '>' && !line.length() && !mine) {
        mine = true;
      } else if (mine && c != '\r' && line.length() < MAX_LINE) {
        line += c;
      }
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

}  // namespace fleetbt

// The robot's Bluetooth: its name, and the port its web server listens on
inline void fleetBtBegin(const char* name, uint16_t port) {
  fleetbt::webPort = port;
  fleetbt::link.begin(name);
  xTaskCreatePinnedToCore(fleetbt::task, "fleet-bt", 8192, nullptr, 1, nullptr, 0);
}
inline bool fleetBtConnected() { return fleetbt::link.hasClient(); }
