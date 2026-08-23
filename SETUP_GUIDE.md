# ESP32 Monitor TUI - Complete Setup Guide

## 🚀 Quick Start

This guide will walk you through setting up the complete ESP32 monitoring system with a btop-style terminal interface.

---

## 📋 Prerequisites

### Hardware
- **ESP32 development board** (any variant: ESP32-WROOM, ESP32-S2, ESP32-C3, etc.)
- **USB cable** (data-capable, not charge-only)
- **Computer** running macOS, Linux, or BSD

### Software
- **Python 3.8+**
- **Arduino IDE** (or PlatformIO)
- **WiFi network** (for RSSI monitoring)

---

## 🔧 Part 1: Python Environment Setup

### 1. Navigate to project directory

```bash
cd /Users/chinmayabharadwajhs/TUI
```

### 2. Create and activate virtual environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate
```

You should see `(venv)` in your prompt.

### 3. Install dependencies

```bash
pip install rich pyserial
```

**Packages installed:**
- `rich` - Beautiful terminal formatting and live updates
- `pyserial` - Serial communication with ESP32

---

## 📡 Part 2: ESP32 Firmware Setup

### 1. Open Arduino IDE

Launch Arduino IDE and open the ESP32 sketch:
```
File → Open → /Users/chinmayabharadwajhs/TUI/esp/esp.ino
```

### 2. Configure WiFi credentials

**Edit these lines in `esp.ino`:**

```cpp
#define SSID "your_wifi_ssid"      // ← Replace with your WiFi name
#define PASSWORD "your_wifi_password"  // ← Replace with your WiFi password
```

### 3. Select your ESP32 board

```
Tools → Board → ESP32 Arduino → [Select your ESP32 model]
```

Common boards:
- **ESP32 Dev Module** (most common)
- **ESP32-S2 Dev Module**
- **ESP32-C3 Dev Module**

### 4. Select the serial port

```
Tools → Port → /dev/cu.usbserial-0001
```

Your port might be different. Look for:
- macOS: `/dev/cu.usbserial-*` or `/dev/cu.wchusbserial*`
- Linux: `/dev/ttyUSB0` or `/dev/ttyACM0`

### 5. Upload the firmware

Click the **Upload** button (→) or press `Cmd+U` (macOS) / `Ctrl+U` (Linux).

**Wait for:**
```
Hard resetting via RTS pin...
Leaving...
```

### 6. Verify upload (optional)

Open the Serial Monitor (`Tools → Serial Monitor`) and set baud to **115200**.

You should see JSON lines streaming every second:
```json
{"cpu_mhz":240,"max_cpu_mhz":240,"heap":280000,...}
```

If you see this, **firmware is working!** Close the Serial Monitor before running the TUI.

---

## 🖥️ Part 3: Run the TUI

### 1. Find your serial port

```bash
ls /dev/cu.* | grep usb
```

Expected output:
```
/dev/cu.usbserial-0001
```

### 2. Update port in Python files (if different)

If your port is different, edit:

**esp32_tui.py (line 18):**
```python
PORT = "/dev/cu.usbserial-0001"  # ← Update this
```

**dashboard.py (line 16):**
```python
PORT = "/dev/cu.usbserial-0001"  # ← Update this
```

### 3. Launch the btop-style TUI

```bash
python3 esp32_tui.py
```

**You should see:**
- Live CPU usage with dual-core bars
- Heap memory with sparkline graphs
- WiFi RSSI indicator
- Network throughput charts
- FreeRTOS task list with state badges
- Real-time updates at 15 FPS

---

## ⌨️ Keyboard Controls

| Key | Action |
|-----|--------|
| **A** | Toggle ALL/USER task view (show/hide system tasks) |
| **↑/↓** | Navigate task list (select process) |
| **K** | Kill selected task (requires confirmation) |
| **Y** | Confirm kill |
| **N** / **Esc** | Cancel kill |
| **S** | Pause/Resume monitoring |
| **Q** | Quit application |

---

## 🎨 What You'll See

```
┌───────────────────────────────────────────────────────────────────────┐
│  ◈ ESP32 MONITOR  │  ↑↓ sel │ K kill │ A tasks │ S pause │ Q quit    │
├────────────────────────┬──────────────────────────────────────────────┤
│ ◉ cpu                  │ ☰ proc                                       │
│ clock 240 MHz    60%   │ Pid  NAME          STATE       PRIO  STACK   │
│ ████████████░░░░        │ ▸ 5  demo_worker   Blocked      1    1.5K    │
│                        │   7  demo_blink    Blocked      1    2.0K    │
│ core0 50%              │   1  loopTask      Running      1    3.5K 🔒 │
│ ██████████░░░░          │   2  IDLE0         Ready        0    1.0K 🔒 │
│ core1 30%              │                                              │
│ ██████░░░░░░            │                                              │
│ [braille sparkline]    │                                              │
│ uptime 01:23:45        │                                              │
├───────────┬────────────┤                                              │
│ ▣ mem     │ ⇅ net      │ › detail                                     │
│ Total 320K│ ▮▮▮▯ -65dBm│ pid       5        priority  1               │
│ Used  140K│ ▼ 2.5 KB/s │ name      demo_worker  stack   1.5K          │
│ Free  180K│ ▲ 0.0 KB/s │ state     Blocked      user    app           │
│ [graph]   │ [graphs]   │ protected no — killable                      │
└───────────┴────────────┴──────────────────────────────────────────────┘
```

---

## 🔍 Troubleshooting

### Problem: "Serial open failed: could not open port"

**Solution:** Check the correct port on your system.

```bash
# macOS
ls /dev/cu.*

# Linux
ls /dev/ttyUSB* /dev/ttyACM*
```

Update `PORT` variable in `esp32_tui.py` and `dashboard.py`.

---

### Problem: "Permission denied" (Linux)

**Solution:** Add your user to the `dialout` group.

```bash
sudo usermod -a -G dialout $USER
# Log out and log back in
```

Or run with sudo (temporary):
```bash
sudo python3 esp32_tui.py
```

---

### Problem: No data received / "waiting for ESP32…"

**Solutions:**

1. **Verify ESP32 is connected:**
   ```bash
   ls /dev/cu.usbserial-*
   ```

2. **Check if ESP32 is sending data:**
   ```bash
   cat /dev/cu.usbserial-0001
   ```
   You should see JSON streaming. Press `Ctrl+C` to stop.

3. **Verify WiFi credentials:**
   - Open `esp/esp.ino`
   - Check SSID and PASSWORD are correct
   - Re-upload firmware

4. **Check Arduino Serial Monitor isn't open:**
   - Only one program can access the serial port
   - Close Arduino Serial Monitor before running TUI

5. **Try resetting the ESP32:**
   - Press the **RST** button on the board
   - Watch for data in the TUI

---

### Problem: Arrow keys don't work

**macOS/Linux:** Should work automatically using `termios`.

**Windows:** Arrow key support is limited. Use keyboard shortcuts:
- `K` to select next task
- `Y` to confirm actions

---

### Problem: Tasks show "protected" and can't be killed

This is **by design**. Protected tasks are:
- `IDLE`, `IDLE0`, `IDLE1` - FreeRTOS idle tasks
- `ipc0`, `ipc1` - Inter-processor communication
- `Tmr Svc` - Timer service
- `wifi` - WiFi stack
- `loopTask` - Arduino main loop
- `esp_timer` - System timer

**These tasks keep the ESP32 alive. Killing them will crash the chip.**

**You CAN kill:**
- `demo_worker`
- `demo_blink`
- Any custom tasks you create with `xTaskCreate()`

---

### Problem: externally-managed-environment error

**Solution:** Always use a virtual environment.

```bash
python3 -m venv venv
source venv/bin/activate
pip install rich pyserial
```

---

## 🎯 Testing the Kill Feature

### 1. Launch the TUI

```bash
python3 esp32_tui.py
```

### 2. Select a killable task

- Press **↓** to highlight `demo_worker` or `demo_blink`
- These are user tasks marked as **killable**

### 3. Request kill

- Press **K**
- You'll see: `⚠ TERMINATE TASK` overlay

### 4. Confirm or cancel

- Press **Y** to confirm → Task disappears from list
- Press **N** to cancel → Overlay closes

### 5. Observe the result

The task will be removed from the FreeRTOS task list and stop executing.

---

## 📊 Alternative Dashboard View

For a simpler, less fancy view:

```bash
python3 dashboard.py
```

This provides a basic table view without the full btop-style layout.

---

## 🛠️ Customization

### Change refresh rate

**esp32_tui.py line 844:**
```python
refresh_per_second=15,  # Increase for smoother animation
```

### Adjust graph history length

**esp32_tui.py lines 56-59:**
```python
download_history = deque(maxlen=80)  # Network graph points
cpu_history = deque(maxlen=80)       # CPU sparkline points
```

### Change theme colors

**esp32_tui.py lines 25-42:**
```python
THEME = {
    "cpu": "green",      # ← Change to "cyan", "blue", etc.
    "mem": "magenta",
    "net": "bright_cyan",
    # ... more colors
}
```

---

## 🔄 Creating Your Own Killable Tasks

Add to `esp/esp.ino` before `setup()`:

```cpp
void my_custom_task(void* param) {
  while (true) {
    // Your code here
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}
```

In `setup()`:
```cpp
xTaskCreate(my_custom_task, "my_task", 4096, NULL, 1, NULL);
```

This task will appear in the TUI and **can be killed** since it's not protected.

---

## 📚 Understanding the Architecture

### Data Flow

```
ESP32 Firmware           Serial (115200)         Python TUI
─────────────           ────────────────         ──────────
                                                 
uxTaskGetSystemState()                          serial_worker()
       ↓                                               ↓
publish_metrics()      ──[JSON lines]──>      telemetry_queue
       ↓                                               ↓
Serial.println()                              build_btop_layout()
                                                      ↓
                      <──[kill cmd]───        command_queue
       ↓                                               ↓
handle_command()                              keyboard_worker()
       ↓                                               ↓
vTaskDelete()         ──[ack JSON]──>         Live.update()
```

### Threads in Python

1. **Serial I/O thread** - Blocking `readline()`, handles JSON
2. **Keyboard thread** - Non-blocking key capture, arrow keys
3. **Main render loop** - Updates Rich `Live` display at 15 FPS

### Safety Boundary

**Firmware enforces the kill deny-list**. Even if the Python client sends a kill command for a protected task, the ESP32 will reject it with:

```json
{"ack":"kill","pid":1,"ok":false,"reason":"protected task"}
```

---

## 🎓 What You've Built

✅ **Real-time system monitor** for embedded devices  
✅ **btop-style TUI** with Rich library graphics  
✅ **Bidirectional serial protocol** (JSON-based)  
✅ **FreeRTOS task enumeration** with live updates  
✅ **Safe task termination** with firmware-enforced protections  
✅ **Interactive keyboard controls** (Unix-style)  
✅ **Braille sparklines** and block graphs  
✅ **WiFi connectivity monitoring**  

---

## 🚢 Next Steps

### Enhancements You Can Add

1. **CPU usage per task** - Requires `configGENERATE_RUN_TIME_STATS`
2. **Temperature monitoring** - Read internal temperature sensor
3. **GPIO state display** - Show pin states in a panel
4. **Network traffic counter** - Track WiFi TX/RX bytes
5. **Custom commands** - Extend JSON protocol (reboot, config, etc.)
6. **Log export** - Save telemetry to CSV or JSON file
7. **Multi-board support** - Monitor multiple ESP32s simultaneously
8. **Color themes** - Add theme switcher (press T)

### Share Your Work

- Screenshot your TUI and share it
- Create custom themes
- Add support for ESP32-S3 / ESP32-C6
- Build a web dashboard (WebSocket + Flask)

---

## 📞 Support

**Common issues:**
- Port permissions → Add user to `dialout` group (Linux)
- WiFi not connecting → Check credentials, signal strength
- Task list empty → Verify `configUSE_TRACE_FACILITY` is enabled
- Compile errors → Update ESP32 Arduino core to latest version

**Debugging:**
```bash
# Test serial connectivity
cat /dev/cu.usbserial-0001

# Check Python dependencies
pip list | grep -E "rich|pyserial"

# Verify virtual environment
which python3  # Should show path in venv/bin/
```

---

## 🎉 You're Ready!

Run the TUI and enjoy your btop-style ESP32 monitor:

```bash
source venv/bin/activate
python3 esp32_tui.py
```

**Press Q to quit when done.**

Happy monitoring! 🚀
