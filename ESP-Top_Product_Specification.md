# ESP-Top: ESP32 Runtime Manager & btop-Style Workload Platform

## 1. Product Vision

Build **ESP-Top**, a production-grade developer tool and runtime platform for ESP32-family devices.

The product should provide a **btop-like live terminal interface**, but its primary purpose is not merely displaying CPU/RAM statistics. It should provide a complete **runtime management layer for independently deployed ESP32 workloads**.

The core promise:

> **Deploy, observe, diagnose, stop, restart, update, quarantine, and remove individual application workloads on an ESP32 without reflashing the base firmware.**

The base runtime is flashed once. Applications are subsequently installed as managed workloads.

### Target user

- Embedded developers
- IoT developers
- PlatformIO users
- Arduino IDE users
- ESP-IDF developers
- Edge/industrial developers
- Developers debugging resource-constrained firmware
- Teams operating multiple ESP32 devices

---

# 2. Fundamental Architectural Change

## Current model

```text
Arduino / PlatformIO
        |
        v
   Entire firmware
        |
        v
      Flash
        |
        v
   ESP32 application
```

An arbitrary function inside that firmware cannot safely be treated as an independently removable process.

## Target model

```text
                 FLASH ONCE
                    |
                    v
          +----------------------+
          |    ESP Runtime       |
          |----------------------|
          | Supervisor            |
          | Workload Manager      |
          | Resource Manager      |
          | Storage Manager       |
          | Log Manager           |
          | Crash Manager         |
          | Security              |
          | Telemetry             |
          +----------+-----------+
                     |
              Install / Update
                     |
       +-------------+-------------+
       |             |             |
       v             v             v
  Workload A    Workload B    Workload C
```

The base firmware becomes a permanent supervisor/runtime.

Application code becomes a managed workload with an explicit lifecycle.

---

# 3. Product Components

The system should contain:

1. **ESP Runtime**
2. **Workload SDK**
3. **Workload packaging/build system**
4. **ESP-Top terminal UI**
5. **Device communication protocol**
6. **Storage manager**
7. **Resource monitor**
8. **Logging and crash subsystem**
9. **Security subsystem**
10. **CLI**
11. **PlatformIO integration**
12. **Arduino integration**
13. **Configuration system**
14. **Documentation**
15. **Testing/CI**
16. Optional web dashboard
17. Optional multi-device/fleet management layer

---

# 4. ESP Runtime

The runtime is the most important part of the project.

It must remain independent from individual workloads.

## Responsibilities

- Boot the device
- Initialize hardware
- Initialize networking
- Manage workloads
- Track workload state
- Track resources
- Manage workload storage
- Start/stop/restart workloads
- Detect crashes
- Collect logs
- Apply resource limits
- Enforce permissions
- Handle upgrades
- Maintain persistent workload metadata
- Communicate with ESP-Top
- Recover from failed workloads
- Protect critical system services

## Runtime lifecycle

```text
BOOT
 |
 v
INITIALIZE
 |
 v
LOAD REGISTRY
 |
 v
VERIFY WORKLOADS
 |
 v
START REQUIRED WORKLOADS
 |
 v
MONITOR
 |
 +--> HEALTHY
 |
 +--> WARNING
 |
 +--> FAILED
 |      |
 |      v
 |   RESTART POLICY
 |
 +--> QUARANTINED
 |
 +--> STOPPED
```

---

# 5. Workload Model

A workload is the unit that users deploy and manage.

Each workload should have:

```text
Workload
├── unique ID
├── name
├── version
├── executable/module
├── manifest
├── dependencies
├── configuration
├── permissions
├── resource limits
├── storage allocation
├── logs
├── crash history
├── runtime statistics
└── lifecycle state
```

## Workload identity

Do NOT use a raw FreeRTOS task handle as the user-facing PID.

Use:

```text
Workload ID
    |
    +-- persistent UUID
    +-- short numeric display ID
    +-- version
    +-- task handle(s)
```

Example:

```text
101  cloud-function
102  mqtt-agent
103  sensor-worker
```

A workload may own multiple FreeRTOS tasks.

Therefore:

```text
WORKLOAD
  |
  +-- MainTask
  +-- NetworkTask
  +-- WorkerTask
  +-- Timer resources
  +-- Queues
  +-- Allocations
  +-- Files
```

This gives a real application-level abstraction above FreeRTOS.

---

# 6. Workload Lifecycle

Every workload should have explicit states:

```text
INSTALLED
    |
    v
STARTING
    |
    v
RUNNING
    |
    +--> STOPPING --> STOPPED
    |
    +--> FAILED
    |
    +--> QUARANTINED
    |
    +--> RESTARTING
    |
    +--> UPDATING
    |
    +--> DELETING
```

Commands:

```text
INSTALL
START
STOP
RESTART
KILL
PAUSE        (where safely supported)
RESUME       (where safely supported)
UPDATE
DELETE
QUARANTINE
UNQUARANTINE
INFO
LOGS
EXPORT
```

---

# 7. Safe Stop vs Force Kill

Do not make `KILL` simply call `vTaskDelete()`.

A workload must first receive a graceful shutdown request.

```text
STOP
 |
 v
STOPPING
 |
 +-- close sockets
 +-- stop timers
 +-- unregister callbacks
 +-- release queues
 +-- release mutexes
 +-- close files
 +-- free owned memory
 +-- stop child tasks
 |
 v
VERIFY CLEANUP
 |
 v
STOPPED
```

If the workload fails to stop within a configurable timeout:

```text
STOPPING
    |
    | timeout
    v
FORCE TERMINATE
```

Force termination should be treated as exceptional and clearly displayed.

---

# 8. Resource Monitoring

ESP-Top must monitor the ESP32 as both a system and a workload platform.

## CPU

Display:

- Total CPU utilization
- Per-core utilization
- Per-task utilization
- Per-workload utilization
- Current utilization
- Average utilization
- Peak utilization
- CPU history
- CPU saturation warnings

CPU percentages should be calculated from runtime-counter deltas over sampling windows rather than cumulative counters.

```text
CPU % =
task_runtime_delta
------------------ x 100
total_runtime_delta
```

Support ESP32 variants with one or two cores.

---

# 9. RAM Monitoring

RAM must be treated separately from flash.

Display:

```text
Internal RAM
Used
Free
Largest free block
Minimum-ever free
Allocation count
Free count
Fragmentation estimate
```

Where supported:

```text
DRAM
IRAM
DMA-capable memory
RTC memory
PSRAM
```

Important metric:

```text
largest_free_block
```

because total free RAM does not indicate whether a large contiguous allocation can succeed.

## Memory leak detection

Maintain history:

```text
Heap:
22 KB
27 KB
31 KB
37 KB
44 KB
```

Detect persistent growth and report:

```text
POSSIBLE MEMORY LEAK
```

---

# 10. Per-Workload Memory Attribution

Use ESP-IDF heap/task tracking where available.

Each workload should report:

```text
Current heap
Peak heap
Stack high-water mark
Allocation count
Free count
Net allocations
Largest allocation
```

The system should distinguish:

```text
Task stack
Heap allocations
Shared/system allocations
PSRAM allocations
```

Never label stack high-water data simply as total process memory.

---

# 11. Flash and Storage Management

Storage is a first-class feature.

The monitor must answer:

> What is consuming my flash?

Show:

```text
FLASH
------------------------------------------------
Bootloader
Partition table
Runtime
OTA partitions
Workloads
Filesystem
Logs
Crash dumps
Configuration
Free
```

## Storage explorer

Example:

```text
NAME                    SIZE       STATUS
------------------------------------------------
cloud-function.pkg      184 KB     RUNNING
mqtt-agent.pkg          102 KB     RUNNING
sensor-worker.pkg        71 KB     RUNNING
old-experiment.pkg      730 KB     STOPPED
test-firmware.pkg       1.20 MB    STOPPED
logs/                   340 KB     DATA
crashdumps/             190 KB     DATA
```

Actions:

```text
DELETE
ARCHIVE
COMPRESS
EXPORT
INSPECT
```

---

# 12. Idle Workloads

A stopped workload may consume no CPU and little/no RAM while still consuming flash.

ESP-Top must make this obvious.

Example:

```text
old-experiment
STATE: STOPPED
CPU:   0%
RAM:   0 KB
FLASH: 730 KB
```

The storage view should highlight removable storage.

Add:

```text
Unused workload detection
Old workload detection
Duplicate version detection
Temporary file detection
Log growth detection
Crash dump growth detection
```

---

# 13. Compression

Support compressed workload packages where beneficial.

Example:

```text
Original:     1.2 MB
Compressed:   420 KB
Savings:      65%
```

Potential formats can include lightweight compression suitable for embedded systems.

Do not compress blindly.

Compression should primarily optimize persistent storage. Execution-time RAM requirements must still be measured.

The package manager should support:

```text
compress
decompress
verify
install
remove
```

---

# 14. Storage Pressure Analyzer

Do not only show:

```text
FLASH 91%
```

Explain why.

Example:

```text
STORAGE PRESSURE

Flash: 91% used

Largest consumers:
1. TestFirmware.pkg       1.8 MB
2. OldExperiment.pkg      1.2 MB
3. crashlogs/             640 KB
4. CloudFunction.pkg      430 KB

Potential recovery:
Delete OldExperiment       +1.2 MB
Delete TestFirmware        +1.8 MB
Clean old logs             +640 KB

Available after cleanup:
4.1 MB
```

---

# 15. Filesystem Support

Abstract filesystem operations behind a storage API.

Support, where available:

- LittleFS
- SPIFFS
- FAT
- custom partition-backed storage

Expose:

```text
list
stat
read
write
delete
rename
size
checksum
```

The TUI should have a file/storage browser.

---

# 16. Resource Limits

Every workload should have a manifest.

Example:

```yaml
name: cloud-function
version: 1.4.2

resources:
  max_heap: 64KB
  max_stack: 16KB
  max_cpu: 40%
  max_storage: 512KB

restart:
  policy: on-failure
  max_restarts: 3

permissions:
  network: true
  filesystem: true
  gpio: false
```

The runtime should enforce limits where technically possible.

Show:

```text
CPU
████████████████░░░░ 38 / 40%

HEAP
████████████░░░░░░░░ 48 / 64 KB

STORAGE
██████████░░░░░░░░░░ 280 / 512 KB
```

---

# 17. Health Monitoring

Every workload should have health state:

```text
HEALTHY
WARNING
DEGRADED
FAILED
CRASHED
QUARANTINED
STOPPED
```

Health checks can include:

- heartbeat
- execution latency
- failure count
- CPU limit
- memory growth
- stack safety margin
- storage limit
- network state
- watchdog events

---

# 18. Automatic Recovery

Support restart policies:

```text
never
always
on-failure
on-crash
```

Example:

```yaml
restart:
  policy: on-failure
  max_restarts: 3
  backoff: exponential
```

Flow:

```text
WORKLOAD FAILS
      |
      v
RESTART #1
      |
      v
FAIL
      |
      v
RESTART #2
      |
      v
FAIL
      |
      v
RESTART #3
      |
      v
FAIL
      |
      v
QUARANTINE
```

The dashboard should explain why the workload was quarantined.

---

# 19. Crash Management

Capture crash information where supported.

Record:

- workload ID
- version
- timestamp
- reset reason
- exception reason
- program counter
- backtrace
- stack information
- recent logs
- restart count
- resource state before failure

Display:

```text
WORKLOAD CRASHED

CloudFunction
Version 1.4.2

Reason:
LoadProhibited

Restart count:
3 / 3

Action:
Automatically quarantined
```

---

# 20. Logging

Every workload gets its own log stream.

Commands:

```text
esp logs cloud-function
```

TUI:

```text
[L] Logs
```

Support:

- severity
- timestamp
- workload ID
- task
- structured fields
- ring buffers
- persistent logs
- log rotation
- log retention limits
- export

Example:

```text
20:31:14 INFO  request started
20:31:15 INFO  contacting API
20:31:17 WARN  timeout
20:31:20 ERROR retry limit exceeded
```

---

# 21. Telemetry Protocol

Do not make the final protocol an ad-hoc collection of JSON lines.

Define a versioned protocol.

Message types:

```text
HELLO
CAPABILITIES
DEVICE_INFO
SYSTEM_STATS
TASK_LIST
WORKLOAD_LIST
WORKLOAD_INFO
STORAGE
FILES
LOG
CRASH
COMMAND
COMMAND_ACK
ERROR
HEARTBEAT
```

Each message should contain:

```text
protocol version
message type
request ID
timestamp
payload
```

Transport options:

```text
USB serial
Wi-Fi TCP
WebSocket
BLE (optional)
```

Start with serial, then add network transport.

---

# 22. Binary Protocol

JSON is acceptable during development.

For production, evaluate a compact binary protocol such as:

- CBOR
- MessagePack
- custom compact frames

Priorities:

1. low RAM overhead
2. low bandwidth
3. deterministic parsing
4. version compatibility
5. corruption detection

Use framing and checksums where appropriate.

---

# 23. Device Discovery

For Wi-Fi operation, support mDNS/service discovery.

Example:

```text
ESP-TOP DISCOVERY

esp32-lab-01
ESP32-S3
192.168.1.42

esp32-gateway
ESP32
192.168.1.51
```

The user should not need to manually type IP addresses in normal operation.

---

# 24. ESP-Top TUI

The UI should preserve the successful btop mental model.

Primary views:

```text
1 CPU
2 MEMORY
3 PROCESSES / TASKS
4 WORKLOADS
5 STORAGE
6 NETWORK
7 LOGS
8 DEVICE
9 HELP
```

Core navigation:

```text
↑ ↓       select
Enter     inspect
K         stop/kill
R         restart
D         delete
S         start
L         logs
I         info
F         files
M         memory
/         search
T         sort
H         help
Q         quit
```

---

# 25. Main TUI

Example:

```text
┌─ ESP-TOP ──────────────────────────────────────────────┐
│ ESP32-S3   uptime 04:31:22       WiFi -51 dBm         │
├────────────────────────────────────────────────────────┤
│ CPU                                                    │
│ Core 0 ███████████████░░░░ 63%   Core 1 ███████░ 31% │
│                                                        │
│ MEMORY                                                 │
│ RAM   ███████████████░░░ 142 / 320 KB                │
│ PSRAM ███████░░░░░░░░░░  1.8 / 8 MB                  │
│                                                        │
│ FLASH                                                  │
│ █████████████░░░░░░░░░ 74%                            │
├─ WORKLOADS ────────────────────────────────────────────┤
│ ID   NAME              CPU     RAM     FLASH  STATE    │
│ 101  CloudFunction     21.4%   31KB    184KB  RUNNING  │
│ 102  SensorProcessor    8.7%    9KB     72KB  RUNNING  │
│ 103  MQTTHandler        3.2%    6KB    118KB  BLOCKED  │
│ 104  OldExperiment       --      --    730KB  STOPPED  │
├────────────────────────────────────────────────────────┤
│ [K] Kill [R] Restart [D] Delete [L] Logs [I] Info     │
└────────────────────────────────────────────────────────┘
```

---

# 26. Workload Inspection

Selecting a workload and pressing `I` should show:

```text
CloudFunction
------------------------------------------------

Version             1.4.2
Status              RUNNING
Uptime              03:41:12

CPU                 21.4%
CPU peak            39.1%

Heap                31.4 KB
Heap peak           48.2 KB
Stack free           4.2 KB

Flash              184 KB
Files                 6

Executions         4,291
Failures              17
Restarts               3

Last error:
HTTP request timeout

[STOP] [RESTART] [DELETE] [LOGS]
```

---

# 27. Task View

The runtime should still expose underlying FreeRTOS tasks.

Display:

```text
TASKS

Task                CPU     Stack    State
------------------------------------------------
CloudMain           18.2%   4.2KB    RUN
CloudNetwork         3.2%   3.1KB    BLOCK
SensorTask           8.7%   2.9KB    RUN
MQTTTask             3.2%   2.7KB    BLOCK
IDLE0                21%    1.1KB    READY
IDLE1                24%    1.1KB    READY
```

Make clear that tasks are not necessarily equivalent to workloads.

---

# 28. Process/Workload Safety

Critical runtime tasks must be protected.

Never allow ordinary users to terminate:

- supervisor
- watchdog infrastructure
- storage manager
- communication manager
- critical system tasks

The protection should be capability-based, not merely a hardcoded list of task names.

---

# 29. Security

This product will expose powerful remote control.

Security must therefore be designed from the beginning.

Required features:

- authenticated devices
- encrypted network transport
- workload signatures
- package checksums
- version validation
- secure boot compatibility
- flash encryption compatibility
- authorization for destructive operations
- replay protection
- command IDs
- audit log
- safe provisioning
- credential storage in secure/non-public configuration

Do not embed Wi-Fi passwords or secrets in source code.

---

# 30. Workload Signing

Production workloads should be verifiable.

Package:

```text
manifest
binary/module
configuration schema
dependencies
signature
checksum
```

Before installation:

```text
DOWNLOAD
   |
VERIFY CHECKSUM
   |
VERIFY SIGNATURE
   |
CHECK COMPATIBILITY
   |
CHECK RESOURCES
   |
INSTALL
```

Reject corrupted or unauthorized packages.

---

# 31. Workload Package Format

Define a standard package:

```text
workload.pkg
├── manifest
├── executable/module
├── metadata
├── optional assets
├── optional configuration
└── signature
```

Manifest should contain:

```yaml
name:
version:
target:
architecture:
runtime_version:
entrypoint:
resources:
permissions:
dependencies:
restart:
storage:
```

---

# 32. Compatibility

The runtime should expose:

```text
runtime version
hardware model
chip revision
flash size
PSRAM availability
CPU cores
features
```

A workload can declare requirements:

```yaml
requires:
  runtime: ">=1.2"
  psram: true
  flash: ">=8MB"
```

Installation should fail before deployment if requirements aren't met.

---

# 33. Arduino IDE Integration

Do not require users to abandon Arduino.

Provide an ESP-Top workload SDK.

Example:

```cpp
#include <ESPWorkload.h>

class CloudFunction : public ESPWorkload {
public:
    void setup() override {
        // initialization
    }

    void run() override {
        // workload
    }

    void shutdown() override {
        // cleanup
    }
};

REGISTER_WORKLOAD(CloudFunction);
```

The Arduino project should produce a workload package rather than only a monolithic firmware image when used with the ESP-Top runtime.

Provide examples.

---

# 34. PlatformIO Integration

PlatformIO should be a first-class integration.

Example:

```bash
esp deploy
esp list
esp start cloud-function
esp stop cloud-function
esp restart cloud-function
esp logs cloud-function
esp remove cloud-function
esp inspect cloud-function
```

Deployment pipeline:

```text
compile
  |
package
  |
compress
  |
checksum
  |
sign
  |
upload
  |
verify
  |
install
  |
start
  |
monitor
```

---

# 35. CLI

Create a native CLI:

```bash
esp-top
```

and management commands:

```bash
esp device list
esp device info
esp workload list
esp workload install
esp workload start
esp workload stop
esp workload restart
esp workload remove
esp workload logs
esp workload inspect
esp storage list
esp storage clean
esp doctor
```

Provide machine-readable output:

```bash
esp workload list --json
```

---

# 36. Configuration

Support a human-readable configuration file.

Example:

```toml
[ui]
theme = "nord"
refresh_rate = 2
show_idle = true

[monitor]
history_seconds = 60
warn_cpu = 80
warn_heap = 80
warn_flash = 85

[workload]
stop_timeout_ms = 3000
max_restarts = 3

[connection]
transport = "serial"
baud = 921600
```

---

# 37. Themes

Provide built-in themes:

```text
Default
Nord
Dracula
Solarized
Monokai
High Contrast
Minimal
```

Allow custom themes.

---

# 38. Performance

The monitor must not become a resource problem itself.

Principles:

- bounded sampling
- non-blocking telemetry
- ring buffers
- fixed-size allocations where practical
- avoid unnecessary heap allocations
- avoid scanning flash repeatedly
- cache static information
- incremental filesystem scans
- configurable refresh rate
- separate collection and rendering
- asynchronous communication
- backpressure
- bounded log queues

Target:

```text
monitor overhead < 1-3% CPU
```

where realistically achievable and configurable.

---

# 39. Sampling Architecture

Separate:

```text
Collector
    |
    v
Telemetry snapshot
    |
    v
Protocol
    |
    v
TUI
```

Do not make the UI directly query hardware.

Recommended:

```text
Fast metrics:
100-500 ms

Normal metrics:
1 s

Storage scan:
5-30 s

Deep diagnostics:
on demand
```

---

# 40. Historical Data

Maintain short-lived in-memory history:

```text
CPU history
RAM history
PSRAM history
temperature history
network history
workload CPU
workload heap
storage usage
failure rate
```

Display small graphs/sparklines.

Do not store high-frequency telemetry permanently by default because flash writes have endurance implications.

---

# 41. Network Monitoring

Show:

```text
RSSI
connection state
reconnect count
RX
TX
packet/error statistics where available
```

Per workload where attribution is possible:

```text
CloudFunction
RX 14.2 KB/s
TX 3.7 KB/s
```

---

# 42. Device Information

Show:

```text
Chip
Revision
CPU frequency
CPU cores
Flash size
PSRAM size
SDK/runtime version
MAC
IP
Uptime
Reset reason
Temperature where supported
```

---

# 43. Watchdog Integration

Track:

- watchdog resets
- timeout events
- task starvation
- workload heartbeat failures

Example:

```text
WARNING

CloudFunction missed heartbeat
for 4.2 seconds.

Configured timeout: 3 seconds.

Action:
Restarting workload...
```

---

# 44. Resource Leak Detection

Track trends rather than only current values.

Detect:

```text
heap growth
allocation imbalance
stack reduction
file growth
log growth
restart loops
CPU creep
latency creep
```

Example:

```text
POSSIBLE LEAK

CloudFunction heap:
+18.2 KB / 6 min

Allocations:
+37 net

Confidence:
High
```

---

# 45. Dependency Management

Workloads may depend on:

```text
runtime APIs
other workloads
hardware capabilities
filesystem resources
network services
```

Example:

```yaml
dependencies:
  runtime: ">=1.3"
  mqtt-service: "^2.0"
```

Do not allow unsafe removal of a dependency.

---

# 46. Atomic Updates

Workload updates should be atomic.

Never replace a working workload directly with an unverified upload.

Use:

```text
download
verify
stage
validate
switch
start
health-check
commit
```

If startup fails:

```text
ROLLBACK
```

The old version must remain recoverable until the new version is healthy.

---

# 47. Version History

Maintain:

```text
cloud-function
  v1.4.2 ACTIVE
  v1.4.1 BACKUP
  v1.3.9 ARCHIVED
```

Allow:

```text
rollback
```

without reflashing the entire runtime.

---

# 48. Quarantine

A failed workload should be isolated.

Example:

```text
CloudFunction

FAILED repeatedly.

Restart attempts:
3 / 3

STATUS:
QUARANTINED

Reason:
Exceeded failure threshold.

[VIEW LOGS]
[ROLLBACK]
[DELETE]
[FORCE START]
```

---

# 49. Diagnostics Command

Provide:

```bash
esp doctor
```

Output:

```text
ESP-TOP DOCTOR

Runtime                  OK
Free heap                OK
Largest heap block       WARNING
Flash                    OK
Filesystem               OK
WiFi                     OK
Workload registry        OK
CloudFunction            CRITICAL

Problems:
1. Heap growth detected
2. 3 crashes in last 10 min
3. Storage usage > 85%
```

---

# 50. Export and Support Bundle

Provide:

```bash
esp support-bundle
```

Export:

- device info
- runtime version
- workload registry
- resource statistics
- crash reports
- recent logs
- storage summary
- configuration with secrets removed

This dramatically improves debugging and support.

---

# 51. Web Dashboard

Do not build this before the runtime and TUI are stable.

Eventually provide:

```text
Browser
   |
   v
ESP Runtime
```

The web dashboard can mirror:

- workloads
- CPU
- RAM
- storage
- logs
- crashes
- deployment
- configuration

The protocol should make the UI transport-independent.

---

# 52. Multi-Device Support

Later:

```text
ESP-TOP FLEET

DEVICE             HEALTH   CPU   FLASH
------------------------------------------------
lab-01             HEALTHY  42%    61%
lab-02             WARNING  81%    88%
gateway-01         HEALTHY  33%    54%
sensor-17          CRITICAL 97%    91%
```

Support:

- device groups
- tags
- remote deployment
- bulk updates
- fleet health
- inventory
- rollout policies

---

# 53. Alerts

Potential alerts:

```text
CPU > threshold
heap < threshold
storage > threshold
workload crash
workload restart loop
workload quarantined
device offline
watchdog reset
memory leak suspected
filesystem nearly full
```

Notification targets can later include:

- terminal
- webhook
- email
- Slack
- other integrations

---

# 54. AI/Diagnostic Layer — Later

AI should not be the foundation.

Once reliable telemetry exists, an optional diagnostic layer can explain:

```text
WHY DID THIS WORKLOAD FAIL?
```

Example:

```text
CloudFunction failure analysis

Evidence:
- heap increased 31 KB → 58 KB
- 43 net allocations
- 3 timeout errors
- CPU reached 94%
- restart occurred twice

Likely causes:
1. Memory leak
2. Retry storm
3. Blocking network operation
```

The AI must cite actual telemetry and logs rather than invent explanations.

---

# 55. Current Repository Migration

The existing TUI repository should be treated as **v0 prototype/reference UI**, not the final architecture.

Current useful work to preserve:

- TUI interaction model
- process/task table
- selection
- kill confirmation
- CPU display
- heap display
- PSRAM display
- Wi-Fi information
- themes
- installation scripts
- initial ESP32 telemetry protocol

Do not continue endlessly patching the existing monolithic TUI.

Refactor into modules.

---

# 56. Recommended Repository Structure

```text
esp-top/
│
├── runtime/
│   ├── supervisor/
│   ├── workload/
│   ├── telemetry/
│   ├── resources/
│   ├── storage/
│   ├── logging/
│   ├── crash/
│   ├── security/
│   └── protocol/
│
├── sdk/
│   ├── arduino/
│   ├── platformio/
│   └── examples/
│
├── protocol/
│   ├── schema/
│   ├── versioning/
│   └── codecs/
│
├── cli/
│   └── esp-top/
│
├── tui/
│   ├── screens/
│   ├── widgets/
│   ├── themes/
│   └── input/
│
├── packages/
│   ├── builder/
│   ├── verifier/
│   └── installer/
│
├── docs/
│
├── examples/
│
├── tests/
│
├── scripts/
│
├── packaging/
│   ├── desktop/
│   └── man/
│
├── LICENSE
├── README.md
├── CONTRIBUTING.md
└── SECURITY.md
```

---

# 57. Language Recommendations

## ESP32 runtime

Use:

- C/C++
- ESP-IDF APIs
- FreeRTOS
- Arduino compatibility layer where required

The runtime should preferably be ESP-IDF-first and expose Arduino-compatible workload APIs.

## Host CLI/TUI

Recommended:

- Rust
- Ratatui
- Crossterm
- Serde

The existing Python/Rich implementation can remain as a prototype until feature parity exists.

---

# 58. Build and Distribution

Provide:

```text
Linux
macOS
FreeBSD / BSD where practical
Windows optional
```

The host client should be a single native binary.

Provide:

```text
brew
deb
rpm
pkg
binary releases
source build
```

Potential command:

```bash
curl ... | sh
```

only after a trustworthy release/signing system exists.

---

# 59. Desktop Integration

Provide:

```text
esp-top.desktop
```

for Linux desktop environments.

Application metadata:

```text
Name=ESP-Top
Comment=ESP32 Runtime Monitor
Exec=esp-top
Terminal=true
Type=Application
Categories=Development;System;
```

---

# 60. Man Page

Provide:

```text
esp-top(1)
esp(1)
esp-workload(1)
```

Document:

```text
NAME
SYNOPSIS
DESCRIPTION
COMMANDS
OPTIONS
CONFIGURATION
WORKLOADS
STORAGE
SECURITY
EXAMPLES
FILES
EXIT STATUS
SEE ALSO
```

---

# 61. Testing Strategy

The runtime should have automated tests.

## Unit tests

- workload registry
- package parser
- manifest parser
- resource accounting
- lifecycle transitions
- storage calculations
- protocol encoding
- protocol decoding
- authorization
- restart policy

## Hardware tests

- install
- start
- stop
- restart
- delete
- crash
- rollback
- low-memory
- low-storage
- corrupted package
- invalid signature
- network loss
- power loss during update

---

# 62. Fault Injection

Create intentional workloads:

```text
cpu-burner
memory-leaker
stack-overflow-test
crash-test
storage-filler
network-flood-test
restart-loop
slow-task
```

These are essential for validating the supervisor.

Example:

```text
memory-leaker
    |
    v
heap growth detected
    |
    v
warning
    |
    v
limit exceeded
    |
    v
workload stopped/quarantined
```

---

# 63. Performance Benchmarks

Measure:

```text
boot time
workload install time
workload start time
workload stop time
telemetry latency
TUI refresh latency
CPU overhead
RAM overhead
flash overhead
package compression ratio
filesystem scan time
protocol bandwidth
```

Set regression limits.

---

# 64. Reliability Requirements

The runtime must prioritize:

1. Do not brick the device.
2. Do not corrupt persistent storage.
3. Do not compromise the supervisor.
4. Do not allow workload failure to crash unrelated workloads.
5. Never silently lose workload state.
6. Make destructive operations explicit.
7. Prefer rollback over failure.
8. Recover after power loss.

---

# 65. Critical Architectural Limitation

An arbitrary monolithic Arduino sketch cannot be converted into independently killable workloads after the fact.

For example:

```cpp
void loop() {
    cloudFunction();
    sensor();
    mqtt();
}
```

does not automatically become:

```text
PID 101 cloudFunction
PID 102 sensor
PID 103 mqtt
```

The code must be structured for the runtime.

The system therefore needs a workload boundary through:

- managed native modules/tasks, or
- a sandboxed runtime/VM such as WebAssembly where hardware/resources permit.

Native managed workloads should be the initial implementation.

A sandboxed VM can be investigated later if arbitrary third-party code isolation becomes a core requirement.

---

# 66. Product Roadmap

## Phase 0 — Prototype stabilization

- Freeze existing TUI
- Document current protocol
- Remove secrets from repository
- Rotate exposed credentials
- Establish project architecture
- Add CI

## Phase 1 — Runtime foundation

- Workload registry
- Workload IDs
- Lifecycle manager
- Safe stop
- Restart
- Storage registry
- telemetry snapshots
- protocol versioning

## Phase 2 — Real resource accounting

- CPU deltas
- heap tracking
- stack metrics
- PSRAM
- flash partitions
- filesystem usage
- per-workload attribution

## Phase 3 — Deployment

- workload package
- manifest
- installer
- checksum
- Arduino SDK
- PlatformIO integration
- CLI

## Phase 4 — Production TUI

- native client
- workload screen
- storage screen
- logs
- crash view
- history
- themes
- configuration
- help
- keyboard shortcuts

## Phase 5 — Reliability

- rollback
- quarantine
- restart policies
- watchdog integration
- crash capture
- fault injection
- power-loss recovery

## Phase 6 — Security

- device authentication
- encrypted transport
- signed packages
- authorization
- audit logs
- secure provisioning

## Phase 7 — Advanced platform

- Wi-Fi discovery
- remote management
- web dashboard
- fleet management
- alerts
- diagnostics
- optional AI analysis

---

# 67. V1 Definition of Done

The first product release should be considered complete when a developer can:

```text
1. Flash the ESP runtime once.
2. Connect an ESP32 through USB.
3. See CPU/RAM/flash/PSRAM/network information.
4. See workloads.
5. Install a workload.
6. Start it.
7. Inspect it.
8. Observe its CPU/RAM/stack usage.
9. View its logs.
10. Stop it without rebooting.
11. Restart it without reflashing.
12. Delete it without reflashing.
13. See its storage usage.
14. Detect storage pressure.
15. Detect repeated crashes.
16. Quarantine a broken workload.
17. Roll back a workload.
18. Deploy an updated workload.
19. Use Arduino or PlatformIO to build workloads.
20. Use the TUI without Python dependencies.
```

---

# 68. The Product Differentiator

Do not market this as:

> "btop for ESP32."

That undersells it.

The product is:

> **An application runtime and observability platform for ESP32 devices.**

The btop-style interface is the developer experience.

The underlying product is:

```text
Runtime
+
Workload Management
+
Resource Accounting
+
Storage Management
+
Crash Recovery
+
Deployment
+
Security
+
Observability
```

The core value proposition:

> **Debug and manage applications on constrained ESP32 hardware without reflashing the entire device.**

---

# 69. Final Target Architecture

```text
                         DEVELOPER
                             |
             +---------------+---------------+
             |                               |
        Arduino IDE                     PlatformIO
             |                               |
             +---------------+---------------+
                             |
                       Workload Builder
                             |
                     +-------+-------+
                     |               |
                  Package         Sign
                     |               |
                     +-------+-------+
                             |
                         Deploy
                             |
                             v
┌─────────────────────────────────────────────────────────┐
│                        ESP32                             │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │                 ESP RUNTIME                       │  │
│  │                                                   │  │
│  │ Supervisor      Security       Protocol           │  │
│  │ Workload Mgr    Storage        Telemetry          │  │
│  │ Crash Mgr       Logging        Resource Mgr        │  │
│  └───────────────────────┬───────────────────────────┘  │
│                          │                              │
│              ┌───────────┼───────────┐                  │
│              │           │           │                  │
│              v           v           v                  │
│         CloudFn       Sensor       MQTT                 │
│         Workload      Workload     Workload             │
│              │           │           │                  │
│              +-----------+-----------+                  │
│                          │                              │
│                  Resource Accounting                    │
│                          │                              │
│              CPU / RAM / Flash / PSRAM                 │
│              Tasks / Files / Logs / Crashes            │
└──────────────────────────┬──────────────────────────────┘
                           |
                    Serial / Wi-Fi
                           |
                           v
┌─────────────────────────────────────────────────────────┐
│                       ESP-TOP                            │
│                                                         │
│ CPU │ MEMORY │ WORKLOADS │ STORAGE │ NETWORK │ LOGS     │
│                                                         │
│ Start │ Stop │ Restart │ Kill │ Delete │ Update        │
│                                                         │
│ Diagnose │ History │ Health │ Alerts │ Inspect          │
└─────────────────────────────────────────────────────────┘
```

---

# 70. Engineering Principle

The most important principle for the entire project is:

> **The monitor must never become more important than the workloads it monitors.**

The runtime should be small, deterministic, recoverable, and heavily protected.

The UI should be replaceable.

The protocol should be versioned.

The workload model should be stable.

The storage manager should be transactional.

The deployment system should support rollback.

The security boundary should be explicit.

If those foundations are correct, everything else — TUI, web dashboard, fleet management, alerts, AI diagnostics, IDE plugins — can be built on top without redesigning the ESP32 runtime.

---

# 71. Immediate Implementation Order

Do these in exactly this order:

```text
1. Clean/rotate repository secrets
2. Freeze current TUI as prototype
3. Define workload specification
4. Define workload lifecycle
5. Define protocol schema
6. Build ESP runtime supervisor
7. Implement workload registry
8. Implement safe lifecycle management
9. Implement resource accounting
10. Implement storage manager
11. Implement package format
12. Implement installer
13. Build workload SDK
14. Integrate PlatformIO
15. Integrate Arduino
16. Rewrite TUI against protocol
17. Add logs/crash diagnostics
18. Add rollback/quarantine
19. Add security
20. Package and release
```

Do **not** start with UI polish, AI, fleet management, or a web dashboard.

The runtime is the product. The TUI is its first interface.
