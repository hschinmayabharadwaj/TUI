# ESP32 Monitor TUI

A btop-style terminal user interface for real-time monitoring of ESP32 microcontroller metrics over serial connection.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![ESP32](https://img.shields.io/badge/ESP32-Arduino-green.svg)


## Features

- **Real-time CPU monitoring** - Frequency, dual-core usage, and uptime
- **Memory visualization** - Heap usage with progress bars and watermark tracking
- **Network stats** - WiFi RSSI, download/upload throughput with live graphs
- **Task manager** - FreeRTOS task list with filtering
- **Keyboard controls** - Interactive navigation like btop
- **ASCII graphs** - Live updating charts for CPU and network activity

## Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ESP32 Monitor   A:alltasks  S:stop  Q:quit  │  ● RUNNING  │  12:34:56   │
├────────────────────────────────┬────────────────────────────────────────┤
│ cpu                            │ proc                                   │
│ CPU ████████████░░░░░░░░ 60%   │ Pid  Program     Command    Cpu%       │
│ C0  ██████████░░░░░░░░░░ 50%   │ 1    loopTask    arduino    0.0        │
│ C1  ██████░░░░░░░░░░░░░░ 30%   │ 2    wifi        wifi_task  0.0        │
│ [live graph]                   │ ...                                    │
│ up 0d 01:23:45                 │                                        │
├───────────────┬────────────────┤                                        │
│ mem           │ net            │                                        │
│ Total: 320KiB │ RSSI: -65dBm   │                                        │
│ Used:  140KiB │ ▼ 2.5 KB/s     │                                        │
│ Free:  180KiB │ ▲ 0.0 KB/s     │                                        │
└───────────────┴────────────────┴────────────────────────────────────────┘
```

## Requirements

### Python (Host Machine)
- Python 3.8+
- Virtual environment (recommended)

### ESP32
- ESP32 development board
- Arduino IDE or PlatformIO
- WiFi connection (for RSSI monitoring)

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd TUI
```

### 2. Set up Python environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
# or
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install rich pyserial
```

### 3. Flash the ESP32

1. Open `esp/esp.ino` in Arduino IDE
2. Update WiFi credentials:
   ```cpp
   #define SSID "your_wifi_ssid"
   #define PASSWORD "your_wifi_password"
   ```
3. Select your ESP32 board and port
4. Upload the sketch

### 4. Configure the serial port

Edit `esp32_tui.py` and update the port:

```python
PORT = "/dev/cu.usbserial-0001"  # macOS
# PORT = "/dev/ttyUSB0"          # Linux
# PORT = "COM3"                   # Windows
```

## Usage

### Start the TUI

```bash
source venv/bin/activate
python esp32_tui.py
```

### Keyboard Controls

| Key | Action |
|-----|--------|
| `A` | Toggle all tasks (show/hide system tasks like IDLE) |
| `↑` / `↓` | Select task row in proc panel |
| `K` | Request kill for selected task (requires confirmation) |
| `Y` | Confirm pending kill |
| `N` / `Esc` | Cancel pending kill |
| `S` | Stop/Start monitoring (pause/resume) |
| `Q` | Quit the application |

> **Platform note:** Arrow-key selection uses POSIX terminal raw mode (`termios`). On Windows, basic keys work via `msvcrt`; arrow keys may be limited depending on the terminal.

## JSON Data Format

The ESP32 sends newline-delimited JSON over serial at 115200 baud. Each second it emits a **telemetry** line; **command** and **ack** lines use the same framing.

### Telemetry (ESP32 → host)

```json
{
  "cpu_mhz": 240,
  "max_cpu_mhz": 240,
  "cpu_core0": 0,
  "cpu_core1": 0,
  "heap": 280000,
  "total_heap": 327680,
  "min_heap": 250000,
  "rssi": -65,
  "tx_rate": 0,
  "uptime_ms": 123456,
  "task_count": 8,
  "tasks": [
    {
      "pid": 5,
      "name": "demo_worker",
      "state": "Blocked",
      "priority": 1,
      "stack_hwm": 1536,
      "cmd": "demo_worker",
      "threads": 1,
      "user": "app",
      "mem": 1536,
      "cpu": 0,
      "protected": false
    }
  ]
}
```

Task fields come from FreeRTOS `uxTaskGetSystemState()` (`TaskStatus_t`):

| Field | Type | Description |
|-------|------|-------------|
| `pid` | int | FreeRTOS task number (`xTaskNumber`) |
| `name` | string | Task name |
| `state` | string | `Running`, `Ready`, `Blocked`, `Suspended`, `Deleted`, `Invalid` |
| `priority` | int | Current priority |
| `stack_hwm` | int | Stack high-water mark in **bytes** (`usStackHighWaterMark × 4` on ESP32) |
| `protected` | bool | `true` if the task is on the firmware deny-list |
| `cmd`, `threads`, `user`, `mem`, `cpu` | — | Legacy/display fields kept for backward compatibility |

### Commands (host → ESP32)

One JSON object per line, terminated with `\n`:

```json
{"cmd":"kill","pid":5}
```

Kill by name is also supported:

```json
{"cmd":"kill","name":"demo_worker"}
```

### Acknowledgements (ESP32 → host)

```json
{"ack":"kill","pid":5,"ok":true}
```

Rejected kill (firmware is the trust boundary):

```json
{"ack":"kill","pid":1,"ok":false,"reason":"protected task"}
```

Other rejection reasons: `task not found`, `missing pid or name`, `unknown command`.

### Protected task deny-list (firmware enforced)

These tasks **cannot** be killed via `vTaskDelete` — doing so can hang or crash the chip:

| Task name |
|-----------|
| `IDLE`, `IDLE0`, `IDLE1` |
| `ipc0`, `ipc1` |
| `Tmr Svc` |
| `wifi` |
| `loopTask` |
| `esp_timer` |

The Python UI also blocks selecting protected tasks for kill, but enforcement happens on the ESP32.

**Killable tasks in practice:** only user workloads created in the sketch with `xTaskCreate` (e.g. the bundled `demo_worker` and `demo_blink` demo tasks). Do not attempt to kill core runtime tasks.

## Python client architecture

`esp32_tui.py` runs three concurrent responsibilities:

1. **Serial I/O thread** — blocking `readline()`, pushes telemetry/acks onto a queue, drains an outgoing command queue.
2. **Keyboard thread** — non-blocking key capture; `K` → confirm with `Y` btop-style kill flow.
3. **Render loop (main thread)** — drains telemetry, updates Rich `Live` UI, shows pending-kill and ack/reject status in the header.

`dashboard.py` is a simpler alternate viewer with the same serial-thread pattern and extended task columns.

## Requirements (FreeRTOS)

Real task enumeration requires `configUSE_TRACE_FACILITY 1` and `configRECORD_STACK_HIGH_ADDRESS 1`. These are enabled by default on the ESP32 Arduino core; the sketch fails at compile time if trace facility is off.

## Customization

### Adjust refresh rate

In `esp32_tui.py`:
```python
with Live(..., refresh_per_second=10, ...):  # Change 10 to desired FPS
```

### Modify graph history length

```python
download_history = deque(maxlen=60)  # Increase for longer history
cpu_history = deque(maxlen=50)
```

### Change serial timeout

```python
ser = serial.Serial(PORT, BAUD, timeout=0.1)  # Adjust timeout in seconds
```

## Troubleshooting

### Serial port not found

```
Error opening serial port: [Errno 2] No such file or directory
```

**Solution:** Check the correct port:
```bash
# macOS
ls /dev/cu.*

# Linux
ls /dev/ttyUSB*
```

### Permission denied (Linux)

```bash
sudo usermod -a -G dialout $USER
# Log out and back in
```

### No data received

1. Verify ESP32 is connected and powered
2. Check baud rate matches (115200)
3. Open Arduino Serial Monitor to verify ESP32 is sending data
4. Ensure WiFi credentials are correct in `esp/esp.ino`

### externally-managed-environment error

Use a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
pip install rich pyserial
```

## Project Structure

```
TUI/
├── esp32_tui.py    # Full btop-style TUI (serial + keyboard + render threads)
├── dashboard.py    # Simpler dashboard with serial thread
├── esp/
│   └── esp.ino     # ESP32 Arduino sketch (telemetry + kill commands)
├── venv/           # Python virtual environment
└── README.md       # This file
```



## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Acknowledgments

- [Rich](https://github.com/Textualize/rich) - Beautiful terminal formatting
- [btop](https://github.com/aristocratos/btop) - Inspiration for the UI design
- [pyserial](https://github.com/pyserial/pyserial) - Serial communication
