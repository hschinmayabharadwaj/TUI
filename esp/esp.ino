#include <WiFi.h>
#include <cstring>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_wifi.h"

#define SSID "ssid"
#define PASSWORD "pass"

#ifndef configUSE_TRACE_FACILITY
#define configUSE_TRACE_FACILITY 0
#endif

#if !configUSE_TRACE_FACILITY
#error "configUSE_TRACE_FACILITY must be 1 (enabled by default on ESP32 Arduino core)"
#endif

static const char* PROTECTED_TASKS[] = {
  "IDLE", "IDLE0", "IDLE1", "ipc0", "ipc1",
  "Tmr Svc", "wifi", "loopTask", "esp_timer"
};
static const size_t PROTECTED_TASK_COUNT = sizeof(PROTECTED_TASKS) / sizeof(PROTECTED_TASKS[0]);

#define MAX_TRACKED_TASKS 48

struct TaskEntry {
  TaskHandle_t handle;
  UBaseType_t number;
  char name[configMAX_TASK_NAME_LEN];
};

static TaskEntry task_table[MAX_TRACKED_TASKS];
static size_t task_table_count = 0;

static bool str_iequals(const char* a, const char* b) {
  while (*a && *b) {
    char ca = (*a >= 'A' && *a <= 'Z') ? (*a + 32) : *a;
    char cb = (*b >= 'A' && *b <= 'Z') ? (*b + 32) : *b;
    if (ca != cb) return false;
    a++;
    b++;
  }
  return *a == *b;
}

static bool is_protected_task(const char* name) {
  for (size_t i = 0; i < PROTECTED_TASK_COUNT; i++) {
    if (str_iequals(name, PROTECTED_TASKS[i])) return true;
  }
  return false;
}

static const char* task_state_str(eTaskState state) {
  switch (state) {
    case eRunning: return "Running";
    case eReady: return "Ready";
    case eBlocked: return "Blocked";
    case eSuspended: return "Suspended";
    case eDeleted: return "Deleted";
    case eInvalid: return "Invalid";
    default: return "Unknown";
  }
}

static void json_escape_print(const char* s) {
  Serial.print('"');
  for (const char* p = s; *p; p++) {
    char c = *p;
    if (c == '"' || c == '\\') {
      Serial.print('\\');
      Serial.print(c);
    } else if (c >= 32 && c < 127) {
      Serial.print(c);
    } else {
      Serial.print('?');
    }
  }
  Serial.print('"');
}

static void rebuild_task_table(TaskStatus_t* status, UBaseType_t count) {
  task_table_count = 0;
  for (UBaseType_t i = 0; i < count && task_table_count < MAX_TRACKED_TASKS; i++) {
    TaskEntry* entry = &task_table[task_table_count];
    entry->handle = status[i].xHandle;
    entry->number = status[i].xTaskNumber;
    strncpy(entry->name, status[i].pcTaskName ? status[i].pcTaskName : "?", configMAX_TASK_NAME_LEN - 1);
    entry->name[configMAX_TASK_NAME_LEN - 1] = '\0';
    task_table_count++;
  }
}

static TaskHandle_t lookup_task_handle(UBaseType_t pid, const char* name, bool by_name) {
  for (size_t i = 0; i < task_table_count; i++) {
    if (by_name) {
      if (name && str_iequals(task_table[i].name, name)) {
        return task_table[i].handle;
      }
    } else if (task_table[i].number == pid) {
      return task_table[i].handle;
    }
  }
  return NULL;
}

static const char* lookup_task_name(UBaseType_t pid) {
  for (size_t i = 0; i < task_table_count; i++) {
    if (task_table[i].number == pid) return task_table[i].name;
  }
  return NULL;
}

static void send_kill_ack(UBaseType_t pid, bool ok, const char* reason) {
  Serial.print("{\"ack\":\"kill\",\"pid\":");
  Serial.print(pid);
  Serial.print(",\"ok\":");
  Serial.print(ok ? "true" : "false");
  if (reason && reason[0]) {
    Serial.print(",\"reason\":");
    json_escape_print(reason);
  }
  Serial.println("}");
}

static int parse_json_int(const String& line, const char* key) {
  String needle = String("\"") + key + "\":";
  int idx = line.indexOf(needle);
  if (idx < 0) return -1;
  idx += needle.length();
  while (idx < (int)line.length() && (line[idx] == ' ' || line[idx] == '\t')) idx++;
  return line.substring(idx).toInt();
}

static bool parse_json_string(const String& line, const char* key, char* out, size_t out_len) {
  String needle = String("\"") + key + "\":\"";
  int idx = line.indexOf(needle);
  if (idx < 0) return false;
  idx += needle.length();
  int end = line.indexOf('"', idx);
  if (end < 0) return false;
  String value = line.substring(idx, end);
  strncpy(out, value.c_str(), out_len - 1);
  out[out_len - 1] = '\0';
  return true;
}

static void handle_command(const String& line) {
  String trimmed = line;
  trimmed.trim();
  if (trimmed.length() == 0 || trimmed.charAt(0) != '{') return;

  char cmd[32] = {0};
  if (!parse_json_string(trimmed, "cmd", cmd, sizeof(cmd))) return;

  if (strcmp(cmd, "kill") != 0) {
    Serial.print("{\"ack\":\"");
    Serial.print(cmd);
    Serial.println("\",\"ok\":false,\"reason\":\"unknown command\"}");
    return;
  }

  char name[configMAX_TASK_NAME_LEN] = {0};
  bool by_name = parse_json_string(trimmed, "name", name, sizeof(name));
  int pid = parse_json_int(trimmed, "pid");
  if (!by_name && pid < 0) {
    send_kill_ack(0, false, "missing pid or name");
    return;
  }

  UBaseType_t target_pid = by_name ? 0 : (UBaseType_t)pid;
  const char* target_name = by_name ? name : lookup_task_name(target_pid);
  if (by_name) {
    for (size_t i = 0; i < task_table_count; i++) {
      if (str_iequals(task_table[i].name, name)) {
        target_pid = task_table[i].number;
        break;
      }
    }
  }
  if (!target_name) {
    send_kill_ack(target_pid, false, "task not found");
    return;
  }

  if (is_protected_task(target_name)) {
    send_kill_ack(target_pid, false, "protected task");
    return;
  }

  TaskHandle_t handle = lookup_task_handle(target_pid, name, by_name);
  if (handle == NULL) {
    send_kill_ack(target_pid, false, "task not found");
    return;
  }

  vTaskDelete(handle);
  send_kill_ack(target_pid, true, NULL);
}

static void demo_worker(void* param) {
  (void)param;
  while (true) {
    vTaskDelay(pdMS_TO_TICKS(2000));
  }
}

void publish_metrics() {
  uint32_t freeHeap = ESP.getFreeHeap();
  uint32_t minHeap = ESP.getMinFreeHeap();
  uint32_t totalHeap = ESP.getHeapSize();
  uint32_t cpuFreq = getCpuFrequencyMhz();
  uint32_t uptime = millis();
  int rssi = WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
  UBaseType_t taskCount = uxTaskGetNumberOfTasks();

  TaskStatus_t* taskStatusArray = (TaskStatus_t*)malloc(taskCount * sizeof(TaskStatus_t));
  UBaseType_t captured = 0;
  if (taskStatusArray != NULL) {
    captured = uxTaskGetSystemState(taskStatusArray, taskCount, NULL);
    rebuild_task_table(taskStatusArray, captured);
  }

  Serial.print("{");

  Serial.print("\"cpu_mhz\":");
  Serial.print(cpuFreq);

  Serial.print(",\"max_cpu_mhz\":240");

  Serial.print(",\"cpu_core0\":0");
  Serial.print(",\"cpu_core1\":0");

  Serial.print(",\"heap\":");
  Serial.print(freeHeap);

  Serial.print(",\"total_heap\":");
  Serial.print(totalHeap);

  Serial.print(",\"min_heap\":");
  Serial.print(minHeap);

  Serial.print(",\"rssi\":");
  Serial.print(rssi);

  Serial.print(",\"tx_rate\":0");

  Serial.print(",\"uptime_ms\":");
  Serial.print(uptime);

  Serial.print(",\"task_count\":");
  Serial.print(taskCount);

  Serial.print(",\"tasks\":[");
  if (taskStatusArray != NULL) {
    for (UBaseType_t i = 0; i < captured; i++) {
      if (i > 0) Serial.print(',');
      UBaseType_t pid = taskStatusArray[i].xTaskNumber;
      const char* name = taskStatusArray[i].pcTaskName ? taskStatusArray[i].pcTaskName : "?";
      uint32_t stack_bytes = (uint32_t)taskStatusArray[i].usStackHighWaterMark * sizeof(StackType_t);
      bool protected_task = is_protected_task(name);

      Serial.print("{\"pid\":");
      Serial.print(pid);
      Serial.print(",\"name\":");
      json_escape_print(name);
      Serial.print(",\"state\":");
      json_escape_print(task_state_str(taskStatusArray[i].eCurrentState));
      Serial.print(",\"priority\":");
      Serial.print(taskStatusArray[i].uxCurrentPriority);
      Serial.print(",\"stack_hwm\":");
      Serial.print(stack_bytes);
      Serial.print(",\"cmd\":");
      json_escape_print(name);
      Serial.print(",\"threads\":1,\"user\":");
      json_escape_print(protected_task ? "system" : "app");
      Serial.print(",\"mem\":");
      Serial.print(stack_bytes);
      Serial.print(",\"cpu\":0");
      Serial.print(",\"protected\":");
      Serial.print(protected_task ? "true" : "false");
      Serial.print('}');
    }
  }
  Serial.print("]");

  Serial.println("}");

  if (taskStatusArray != NULL) {
    free(taskStatusArray);
  }
}

void setup() {
  Serial.begin(115200);

  // Demo user workloads — only tasks like these are safe/practical to kill.
  xTaskCreate(demo_worker, "demo_worker", 4096, NULL, 1, NULL);
  xTaskCreate(demo_worker, "demo_blink", 2048, NULL, 1, NULL);

  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handle_command(line);
  }

  publish_metrics();
  delay(1000);
}
