import json
import queue
import serial
import sys
import threading
import time
from collections import deque

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

PORT = None
BAUD = 115200

console = Console()
running = True
telemetry_queue = queue.Queue()
command_queue = queue.Queue()
last_data = {}
status_line = "Waiting for ESP32..."

rx_history = deque(maxlen=10)
last_time = time.time()


def calculate_throughput(raw_len):
    global last_time
    now = time.time()
    dt = max(now - last_time, 1e-6)
    last_time = now
    return raw_len / dt / 1024


def render_system(data):
    t = Table(show_header=False)
    t.add_row("Free Heap", f"{data.get('heap', 0)} B")
    t.add_row("Min Heap", f"{data.get('min_heap', 0)} B")
    t.add_row("WiFi RSSI", f"{data.get('rssi', 0)} dBm")
    t.add_row("Tasks", str(data.get("task_count", 0)))
    return Panel(t, title="System")


def render_tasks(tasks):
    table = Table(title="FreeRTOS Tasks", expand=True)
    table.add_column("Pid", justify="right")
    table.add_column("Task")
    table.add_column("State")
    table.add_column("Prio", justify="right")
    table.add_column("Stack HWM")

    for t in tasks:
        stack = t.get("stack_hwm", t.get("stack", 0))
        table.add_row(
            str(t.get("pid", "")),
            t.get("name", "?"),
            str(t.get("state", "?")),
            str(t.get("priority", "?")),
            f"{stack} B",
        )
    return Panel(table)


def render_wifi(rate):
    table = Table(show_header=False)
    table.add_row("Throughput", f"{rate:.2f} KB/s")
    return Panel(table, title="Wi-Fi")


def serial_worker(ser):
    global running, last_data, status_line

    while running:

        try:
            while True:
                cmd = command_queue.get_nowait()
                ser.write((json.dumps(cmd) + "\n").encode())
        except queue.Empty:
            pass

        raw = ser.readline()
        if not raw:
            continue

        try:
            payload = json.loads(raw.decode(errors="ignore"))
        except json.JSONDecodeError:
            continue

        if payload.get("ack") == "kill":
            if payload.get("ok"):
                status_line = f"Kill ok pid {payload.get('pid')}"
            else:
                status_line = f"Kill rejected: {payload.get('reason', '?')}"
            telemetry_queue.put({"type": "ack", "data": payload})
            continue

        last_data = payload
        telemetry_queue.put({"type": "telemetry", "data": payload, "raw_len": len(raw)})


def pick_port():
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    for info in ports:
        blob = f"{info.description} {info.hwid}".lower()
        if "bluetooth" in blob:
            continue
        if any(tok in blob for tok in ("usb", "uart", "cp210", "ch340", "esp")):
            return info.device
    return ports[0].device if ports else PORT


def main():
    global running, last_data, status_line

    port = sys.argv[1] if len(sys.argv) > 1 else pick_port()
    if not port:
        console.print("[red]No serial port found. Pass one as the first argument.[/]")
        sys.exit(1)
    try:
        ser = serial.Serial(port, BAUD, timeout=0.1)
    except serial.SerialException as exc:
        console.print(f"[red]Serial open failed: {exc}[/]")
        sys.exit(1)
    console.print(f"[dim]Using {port} @ {BAUD}[/]")

    io_thread = threading.Thread(target=serial_worker, args=(ser,), daemon=True)
    io_thread.start()

    layout = Layout()
    layout.split_column(
        Layout(name="top", size=8),
        Layout(name="bottom"),
        Layout(name="status", size=1),
    )
    layout["top"].split_row(
        Layout(name="system"),
        Layout(name="wifi"),
    )
    layout["bottom"].update(Panel("Waiting for ESP32...", title="Tasks"))
    layout["status"].update(Panel(status_line, title="Status"))

    try:
        with Live(layout, refresh_per_second=4, console=console):
            while running:
                updated = False
                while True:
                    try:
                        item = telemetry_queue.get_nowait()
                    except queue.Empty:
                        break
                    updated = True
                    if item["type"] == "telemetry":
                        data = item["data"]
                        rate = calculate_throughput(item["raw_len"])
                        layout["system"].update(render_system(data))
                        layout["wifi"].update(render_wifi(rate))
                        layout["bottom"].update(render_tasks(data.get("tasks", [])))
                    layout["status"].update(Panel(status_line, title="Status"))

                if not updated:
                    time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        running = False
        ser.close()


if __name__ == "__main__":
    main()
