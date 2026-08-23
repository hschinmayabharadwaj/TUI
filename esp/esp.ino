#include <WiFi.h>
#include <Arduino.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#ifndef WIFI_SSID
#define WIFI_SSID "Airtel_shiv_7160"
#endif
#ifndef WIFI_PASS
#define WIFI_PASS "Air@29269"
#endif

#define SEND_INTERVAL_MS 1000
#define MAX_TASKS 40
#define LINE_MAX 256

static const char *PROTECTED_TASKS[] = {
    "IDLE", "IDLE0", "IDLE1", "ipc0", "ipc1", "Tmr Svc",
    "wifi", "wifiN", "loopTask", "esp_timer", "sys_evt",
    "arduino_events", "tiT", NULL};

static uint32_t prev_idle0 = 0;
static uint32_t prev_idle1 = 0;
static uint32_t prev_total = 0;
static unsigned long last_send = 0;
static TaskHandle_t h_demo_worker = NULL;
static TaskHandle_t h_demo_blink = NULL;

static int task_pid_from_handle(TaskHandle_t handle) {
  if (!handle) {
    return -1;
  }
  return (int)((((uintptr_t)handle) >> 4) & 0x7FFF);
}

static bool name_eq(const char *a, const char *b) {
  if (!a || !b) return false;
  while (*a && *b) {
    char ca = (*a >= 'A' && *a <= 'Z') ? (char)(*a + 32) : *a;
    char cb = (*b >= 'A' && *b <= 'Z') ? (char)(*b + 32) : *b;
    if (ca != cb) return false;
    a++; b++;
  }
  return *a == *b;
}

static bool is_protected_name(const char *name) {
  for (int i = 0; PROTECTED_TASKS[i]; i++) {
    if (name_eq(name, PROTECTED_TASKS[i])) return true;
  }
  return false;
}

static const char *state_name(eTaskState state) {
  switch (state) {
    case eRunning: return "Running";
    case eReady: return "Ready";
    case eBlocked: return "Blocked";
    case eSuspended: return "Suspended";
    case eDeleted: return "Deleted";
    default: return "Invalid";
  }
}

static void json_escape(const char *s) {
  for (; s && *s; s++) {
    if (*s == '"' || *s == '\\') {
      Serial.write('\\');
      Serial.write(*s);
    } else if (*s == '\n') {
      Serial.print("\\n");
    } else if ((unsigned char)*s >= 32) {
      Serial.write(*s);
    }
  }
}

static void print_ack(int pid, bool ok, const char *reason) {
  Serial.print("{\"ack\":\"kill\",\"pid\":");
  Serial.print(pid);
  Serial.print(",\"ok\":");
  Serial.print(ok ? "true" : "false");
  if (!ok && reason) {
    Serial.print(",\"reason\":\"");
    json_escape(reason);
    Serial.print("\"");
  }
  Serial.println("}");
}

static int json_int(const String &line, const char *key, int fallback) {
  String needle = String("\"") + key + "\":";
  int idx = line.indexOf(needle);
  if (idx < 0) return fallback;
  idx += needle.length();
  while (idx < (int)line.length() && line[idx] == ' ') idx++;
  return line.substring(idx).toInt();
}

static String json_string(const String &line, const char *key) {
  String needle = String("\"") + key + "\":\"";
  int idx = line.indexOf(needle);
  if (idx < 0) return "";
  idx += needle.length();
  int end = line.indexOf('"', idx);
  if (end < 0) return "";
  return line.substring(idx, end);
}

static TaskHandle_t find_task(int pid, const char *name, char *found_name, size_t found_len, bool *protected_out) {
  static const char *known[] = {
      "demo_worker", "demo_blink", "loopTask", "IDLE", "IDLE0", "IDLE1",
      "ipc0", "ipc1", "Tmr Svc", "wifi", "wifiN", "tiT", "esp_timer",
      "sys_evt", "arduino_events", "sysWdt", NULL};
  TaskHandle_t extras[] = {h_demo_worker, h_demo_blink, xTaskGetCurrentTaskHandle(), NULL};
  TaskHandle_t candidates[MAX_TASKS];
  int count = 0;
  for (int i = 0; known[i] && count < MAX_TASKS; i++) {
    TaskHandle_t h = xTaskGetHandle(known[i]);
    if (h) {
      candidates[count++] = h;
    }
  }
  for (int i = 0; extras[i] && count < MAX_TASKS; i++) {
    candidates[count++] = extras[i];
  }
#if (configUSE_TRACE_FACILITY == 1)
  {
    UBaseType_t n = uxTaskGetNumberOfTasks();
    if (n > MAX_TASKS) n = MAX_TASKS;
    TaskStatus_t *arr = (TaskStatus_t *)pvPortMalloc(n * sizeof(TaskStatus_t));
    if (arr) {
      n = uxTaskGetSystemState(arr, n, NULL);
      for (UBaseType_t i = 0; i < n && count < MAX_TASKS; i++) {
        candidates[count++] = arr[i].xHandle;
      }
      vPortFree(arr);
    }
  }
#endif
  for (int i = 0; i < count; i++) {
    TaskHandle_t handle = candidates[i];
    if (!handle) {
      continue;
    }
    const char *tn = pcTaskGetName(handle);
    bool match = false;
    if (pid >= 0 && task_pid_from_handle(handle) == pid) {
      match = true;
    }
    if (name && name[0] && name_eq(tn, name)) {
      match = true;
    }
    if (match) {
      if (found_name && found_len && tn) {
        strncpy(found_name, tn, found_len - 1);
        found_name[found_len - 1] = 0;
      }
      if (protected_out) {
        *protected_out = is_protected_name(tn);
      }
      return handle;
    }
  }
  return NULL;
}

static void handle_command(const String &line) {
  if (line.indexOf("\"cmd\"") < 0 || line.indexOf("kill") < 0) {
    print_ack(-1, false, "unknown command");
    return;
  }
  int pid = json_int(line, "pid", -1);
  String name = json_string(line, "name");
  if (pid < 0 && name.length() == 0) {
    print_ack(-1, false, "missing pid or name");
    return;
  }
  char found[configMAX_TASK_NAME_LEN + 1] = {0};
  bool protected_task = false;
  TaskHandle_t handle = find_task(pid, name.c_str(), found, sizeof(found), &protected_task);
  if (!handle) {
    print_ack(pid, false, "task not found");
    return;
  }
  if (protected_task || is_protected_name(found) || handle == xTaskGetCurrentTaskHandle()) {
    print_ack(pid >= 0 ? pid : 0, false, "protected task");
    return;
  }
  vTaskDelete(handle);
  print_ack(pid >= 0 ? pid : 0, true, NULL);
}

static void poll_commands() {
  static char buf[LINE_MAX];
  static size_t len = 0;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (len > 0) {
        buf[len] = 0;
        String line(buf);
        line.trim();
        if (line.length() && line[0] == '{') handle_command(line);
        len = 0;
      }
    } else if (len + 1 < sizeof(buf)) {
      buf[len++] = c;
    } else {
      len = 0;
    }
  }
}

static void demo_worker(void *param) {
  (void)param;
  for (;;) vTaskDelay(pdMS_TO_TICKS(400));
}

static void demo_blink(void *param) {
  (void)param;
  for (;;) vTaskDelay(pdMS_TO_TICKS(750));
}

static void emit_task(bool *first, int pid, const char *name, const char *state,
                      int priority, uint32_t stack_bytes, uint32_t cpu_pct) {
  if (!name || !name[0]) return;
  if (!*first) Serial.print(",");
  *first = false;
  bool prot = is_protected_name(name);
  Serial.print("{\"pid\":");
  Serial.print(pid);
  Serial.print(",\"name\":\"");
  json_escape(name);
  Serial.print("\",\"state\":\"");
  json_escape(state ? state : "?");
  Serial.print("\",\"priority\":");
  Serial.print(priority);
  Serial.print(",\"stack_hwm\":");
  Serial.print(stack_bytes);
  Serial.print(",\"cmd\":\"");
  json_escape(name);
  Serial.print("\",\"threads\":1,\"user\":\"");
  Serial.print(prot ? "system" : "app");
  Serial.print("\",\"mem\":");
  Serial.print(stack_bytes);
  Serial.print(",\"cpu\":");
  Serial.print(cpu_pct);
  Serial.print(",\"protected\":");
  Serial.print(prot ? "true" : "false");
  Serial.print("}");
}

static void emit_task_from_handle(bool *first, TaskHandle_t handle) {
  if (!handle) return;
  const char *name = pcTaskGetName(handle);
  if (!name) return;
  uint32_t stack_bytes = uxTaskGetStackHighWaterMark(handle) * sizeof(StackType_t);
  emit_task(first, task_pid_from_handle(handle), name, state_name(eTaskGetState(handle)),
            (int)uxTaskPriorityGet(handle), stack_bytes, 0);
}

static void emit_tasks_by_handle(bool *first) {
  static const char *known[] = {
      "demo_worker", "demo_blink", "loopTask", "IDLE", "IDLE0", "IDLE1",
      "ipc0", "ipc1", "Tmr Svc", "wifi", "wifiN", "tiT", "esp_timer",
      "sys_evt", "arduino_events", "sysWdt", NULL};
  emit_task_from_handle(first, h_demo_worker);
  emit_task_from_handle(first, h_demo_blink);
  emit_task_from_handle(first, xTaskGetCurrentTaskHandle());
  for (int i = 0; known[i]; i++) {
    emit_task_from_handle(first, xTaskGetHandle(known[i]));
  }
}

static void publish_metrics() {
  uint32_t free_heap = ESP.getFreeHeap();
  uint32_t min_heap = ESP.getMinFreeHeap();
  uint32_t total_heap = ESP.getHeapSize();
  uint32_t cpu_mhz = getCpuFrequencyMhz();
  int rssi = (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : 0;
  uint32_t psram = ESP.getPsramSize();
  uint32_t psram_free = ESP.getFreePsram();
  float temp_c = 0;
#if defined(CONFIG_IDF_TARGET_ESP32)
  temp_c = temperatureRead();
#endif
  float core0 = 0, core1 = 0;
  TaskStatus_t *arr = NULL;
  UBaseType_t filled = 0;
  uint32_t total_runtime = 0;

#if (configUSE_TRACE_FACILITY == 1)
  UBaseType_t n = uxTaskGetNumberOfTasks();
  if (n > MAX_TASKS) n = MAX_TASKS;
  arr = (TaskStatus_t *)pvPortMalloc(n * sizeof(TaskStatus_t));
  if (arr) {
    uint32_t idle0 = 0, idle1 = 0;
    filled = uxTaskGetSystemState(arr, n, &total_runtime);
    for (UBaseType_t i = 0; i < filled; i++) {
      if (name_eq(arr[i].pcTaskName, "IDLE0") || name_eq(arr[i].pcTaskName, "IDLE")) idle0 += arr[i].ulRunTimeCounter;
      else if (name_eq(arr[i].pcTaskName, "IDLE1")) idle1 += arr[i].ulRunTimeCounter;
    }
    if (total_runtime > 0 && prev_total > 0) {
      uint32_t span = total_runtime > prev_total ? total_runtime - prev_total : 1;
      uint32_t i0 = idle0 >= prev_idle0 ? idle0 - prev_idle0 : 0;
      uint32_t i1 = idle1 >= prev_idle1 ? idle1 - prev_idle1 : 0;
      core0 = 100.0f - (100.0f * (float)i0 / (float)span);
      core1 = 100.0f - (100.0f * (float)i1 / (float)span);
      if (core0 < 0) core0 = 0; if (core1 < 0) core1 = 0;
      if (core0 > 100) core0 = 100; if (core1 > 100) core1 = 100;
    }
    prev_idle0 = idle0; prev_idle1 = idle1; prev_total = total_runtime;
  }
#endif

  Serial.print("{");
  Serial.print("\"cpu_mhz\":"); Serial.print(cpu_mhz);
  Serial.print(",\"max_cpu_mhz\":240");
  Serial.print(",\"cpu_core0\":"); Serial.print(core0, 1);
  Serial.print(",\"cpu_core1\":"); Serial.print(core1, 1);
  Serial.print(",\"heap\":"); Serial.print(free_heap);
  Serial.print(",\"total_heap\":"); Serial.print(total_heap);
  Serial.print(",\"min_heap\":"); Serial.print(min_heap);
  Serial.print(",\"rssi\":"); Serial.print(rssi);
  Serial.print(",\"tx_rate\":0,\"rx_rate\":0");
  Serial.print(",\"uptime_ms\":"); Serial.print(millis());
  Serial.print(",\"chip\":\""); json_escape(ESP.getChipModel()); Serial.print("\"");
  Serial.print(",\"flash\":"); Serial.print(ESP.getFlashChipSize());
  Serial.print(",\"psram\":"); Serial.print(psram);
  Serial.print(",\"psram_free\":"); Serial.print(psram_free);
  Serial.print(",\"temp_c\":"); Serial.print(temp_c, 1);
  Serial.print(",\"task_count\":"); Serial.print((int)uxTaskGetNumberOfTasks());
  Serial.print(",\"tasks\":[");
  bool first = true;
#if (configUSE_TRACE_FACILITY == 1)
  if (arr && filled > 0) {
    for (UBaseType_t i = 0; i < filled; i++) {
      uint32_t stack_bytes = (uint32_t)arr[i].usStackHighWaterMark * sizeof(StackType_t);
      uint32_t cpu_pct = total_runtime > 100 ? (uint32_t)(arr[i].ulRunTimeCounter / (total_runtime / 100UL)) : 0;
      emit_task(&first, task_pid_from_handle(arr[i].xHandle), arr[i].pcTaskName,
                state_name(arr[i].eCurrentState), (int)arr[i].uxCurrentPriority, stack_bytes, cpu_pct);
    }
  }
  if (arr) vPortFree(arr);
#endif
  if (first) {
    emit_tasks_by_handle(&first);
  }
  Serial.println("]}");
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(20);
  delay(200);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  xTaskCreate(demo_worker, "demo_worker", 2048, NULL, 1, &h_demo_worker);
  xTaskCreate(demo_blink, "demo_blink", 2048, NULL, 1, &h_demo_blink);
}

void loop() {
  unsigned long now = millis();
  if (now - last_send >= SEND_INTERVAL_MS) {
    last_send = now;
    publish_metrics();
  }
  poll_commands();
  vTaskDelay(pdMS_TO_TICKS(10));
}
