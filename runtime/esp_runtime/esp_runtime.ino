// ESP-Top runtime foundation.
//
// The runtime speaks versioned envelopes and publishes a telemetry frame every
// second.  Keeping telemetry in this sketch is important: the host TUI is
// normally used with this runtime (rather than the older esp/esp.ino sketch).
#include <Arduino.h>
#include <WiFi.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *PROTOCOL = "1.0";
static const size_t MAX_WORKLOADS = 8;

enum WorkloadState { INSTALLED, STARTING, RUNNING, STOPPING, STOPPED, FAILED, QUARANTINED };
struct Workload { int id; const char *name; const char *version; WorkloadState state; };

static Workload workloads[MAX_WORKLOADS] = {
    {101, "hello-workload", "0.1.0", INSTALLED},
};
static const size_t workload_count = 1;

static void telemetry() {
  const uint32_t heap = ESP.getFreeHeap();
  const uint32_t total_heap = ESP.getHeapSize();
  const uint32_t psram = ESP.getPsramSize();
  const int rssi = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  float temperature = 0;
#if defined(CONFIG_IDF_TARGET_ESP32)
  temperature = temperatureRead();
#endif

  Serial.print("{\"protocol\":\""); Serial.print(PROTOCOL);
  Serial.print("\",\"type\":\"TELEMETRY\",\"request_id\":\"sample\",\"timestamp\":");
  Serial.print(millis() / 1000.0, 3);
  Serial.print(",\"payload\":{");
  Serial.print("\"cpu_mhz\":"); Serial.print(getCpuFrequencyMhz());
  Serial.print(",\"max_cpu_mhz\":240");
  // CPU accounting requires an ESP-IDF build-time option that Arduino does
  // not enable on every board package. Report a known value until the runtime
  // accounting adapter is installed rather than fabricating utilization.
  Serial.print(",\"cpu_core0\":0,\"cpu_core1\":0");
  Serial.print(",\"heap\":"); Serial.print(heap);
  Serial.print(",\"total_heap\":"); Serial.print(total_heap);
  Serial.print(",\"min_heap\":"); Serial.print(ESP.getMinFreeHeap());
  Serial.print(",\"flash\":"); Serial.print(ESP.getFlashChipSize());
  Serial.print(",\"psram\":"); Serial.print(psram);
  Serial.print(",\"psram_free\":"); Serial.print(ESP.getFreePsram());
  Serial.print(",\"rssi\":"); Serial.print(rssi);
  Serial.print(",\"tx_rate\":0,\"rx_rate\":0");
  Serial.print(",\"temp_c\":"); Serial.print(temperature, 1);
  Serial.print(",\"uptime_ms\":"); Serial.print(millis());
  Serial.print(",\"chip\":\""); Serial.print(ESP.getChipModel()); Serial.print("\"");
  Serial.print(",\"task_count\":"); Serial.print(uxTaskGetNumberOfTasks());
  Serial.println(",\"tasks\":[]}}");
}

static const char *state_name(WorkloadState state) {
  switch (state) {
    case INSTALLED: return "INSTALLED";
    case STARTING: return "STARTING";
    case RUNNING: return "RUNNING";
    case STOPPING: return "STOPPING";
    case STOPPED: return "STOPPED";
    case FAILED: return "FAILED";
    case QUARANTINED: return "QUARANTINED";
  }
  return "FAILED";
}

static void hello() {
  Serial.print("{\"protocol\":\""); Serial.print(PROTOCOL);
  Serial.print("\",\"type\":\"HELLO\",\"request_id\":\"boot\",\"timestamp\":");
  Serial.print(millis() / 1000.0, 3);
  Serial.println(",\"payload\":{\"runtime\":\"0.1.0\",\"features\":[\"workloads\",\"serial\"]}}");
}

static void workload_list() {
  Serial.print("{\"protocol\":\""); Serial.print(PROTOCOL);
  Serial.print("\",\"type\":\"WORKLOAD_LIST\",\"request_id\":\"poll\",\"timestamp\":");
  Serial.print(millis() / 1000.0, 3); Serial.print(",\"payload\":{\"workloads\":[");
  for (size_t i = 0; i < workload_count; ++i) {
    if (i) Serial.print(",");
    Serial.print("{\"id\":"); Serial.print(workloads[i].id);
    Serial.print(",\"name\":\""); Serial.print(workloads[i].name);
    Serial.print("\",\"version\":\""); Serial.print(workloads[i].version);
    Serial.print("\",\"state\":\""); Serial.print(state_name(workloads[i].state)); Serial.print("\"}");
  }
  Serial.println("]}}");
}

void setup() {
  Serial.begin(115200);
  delay(100);
  hello();
}

void loop() {
  static unsigned long last = 0;
  if (millis() - last >= 1000) {
    last = millis();
    telemetry();
  }
  // Command parsing is kept behind the same framed protocol boundary; the
  // production implementation will validate request IDs and signatures here.
  while (Serial.available()) {
    if (Serial.read() == '\n') {
      Serial.println("{\"protocol\":\"1.0\",\"type\":\"ERROR\",\"request_id\":\"unknown\",\"timestamp\":0,\"payload\":{\"reason\":\"runtime scaffold accepts telemetry only\"}}");
    }
  }
}
