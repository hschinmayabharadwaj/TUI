#include <ESPWorkload.h>

class HelloWorkload : public ESPWorkload {
public:
  void setup() override {
    Serial.println("hello workload ready");
  }

  void run() override {
    delay(1000);
  }

  void shutdown() override {
    Serial.println("hello workload stopping");
  }
};

REGISTER_WORKLOAD(HelloWorkload);
