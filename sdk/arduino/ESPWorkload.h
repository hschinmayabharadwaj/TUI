#pragma once

// Minimal Arduino-compatible workload boundary. The ESP runtime owns the task
// and invokes shutdown before a workload is force-terminated.
class ESPWorkload {
public:
  virtual ~ESPWorkload() = default;
  virtual void setup() {}
  virtual void run() = 0;
  virtual void shutdown() {}
};

// Registration is intentionally a small compile-time hook in Phase 1. The
// runtime can replace this macro with a linker-section registry later.
#define REGISTER_WORKLOAD(Type) \
  ESPWorkload *esp_top_create_workload() { return new Type(); }
