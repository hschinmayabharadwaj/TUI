// ESP-Top runtime foundation scaffold.
//
// This sketch is intentionally separate from esp/esp.ino: the latter remains
// the v0 telemetry prototype. This runtime owns a small workload registry and
// speaks the versioned envelope used by the host client. Native workload
// loading and hardware-specific accounting are added behind these boundaries.
#include <Arduino.h>

static const char *PROTOCOL = "1.0";
static const size_t MAX_WORKLOADS = 8;

enum WorkloadState { INSTALLED, STARTING, RUNNING, STOPPING, STOPPED, FAILED, QUARANTINED };
struct Workload { int id; const char *name; const char *version; WorkloadState state; };

static Workload workloads[MAX_WORKLOADS] = {
    {101, "hello-workload", "0.1.0", INSTALLED},
};
static const size_t workload_count = 1;

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
    workload_list();
  }
  // Command parsing is kept behind the same framed protocol boundary; the
  // production implementation will validate request IDs and signatures here.
  while (Serial.available()) {
    if (Serial.read() == '\n') {
      Serial.println("{\"protocol\":\"1.0\",\"type\":\"ERROR\",\"request_id\":\"unknown\",\"timestamp\":0,\"payload\":{\"reason\":\"runtime scaffold accepts telemetry only\"}}");
    }
  }
}
