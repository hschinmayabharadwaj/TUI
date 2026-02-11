#include <WiFi.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_wifi.h"

#define SSID "ssid"
#define PASSWORD "pass"

void publish_metrics() {

  uint32_t freeHeap = ESP.getFreeHeap();
  uint32_t minHeap = ESP.getMinFreeHeap();
  uint32_t totalHeap = ESP.getHeapSize();
  uint32_t cpuFreq = getCpuFrequencyMhz();
  uint32_t uptime = millis();
  int rssi = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  UBaseType_t taskCount = uxTaskGetNumberOfTasks();

  Serial.print("{");

  Serial.print("\"cpu_mhz\":");
  Serial.print(cpuFreq);

  Serial.print(",\"max_cpu_mhz\":240");  // Fixed max for ESP32

  Serial.print(",\"cpu_core0\":0");  // Not available in Arduino
  Serial.print(",\"cpu_core1\":0");  // Not available in Arduino

  Serial.print(",\"heap\":");
  Serial.print(freeHeap);

  Serial.print(",\"total_heap\":");
  Serial.print(totalHeap);

  Serial.print(",\"min_heap\":");
  Serial.print(minHeap);

  Serial.print(",\"rssi\":");
  Serial.print(rssi);

  Serial.print(",\"tx_rate\":0"); // Not accessible directly

  Serial.print(",\"uptime_ms\":");
  Serial.print(uptime);

  Serial.print(",\"task_count\":");
  Serial.print(taskCount);

  // Minimal safe task structure (no CPU%, no mem)
  Serial.print(",\"tasks\":[");
  Serial.print("{\"pid\":1,\"name\":\"loopTask\",\"cmd\":\"arduino_loop\",\"threads\":1,\"user\":\"app\",\"mem\":0,\"cpu\":0}");
  Serial.print("]");

  Serial.println("}");
}

void setup() {
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
}

void loop() {
  publish_metrics();
  delay(1000);
}
