import json
import serial
import time
from collections import deque
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live

PORT = "/dev/ttyUSB0"
BAUD = 115200

console = Console()
ser = serial.Serial(PORT, BAUD, timeout=1)

rx_history = deque(maxlen=10)
last_time = time.time()

def render_system(data):
    t = Table(show_header=False)
    t.add_row("Free Heap", f"{data['heap']} B")
    t.add_row("Min Heap", f"{data['min_heap']} B")
    t.add_row("WiFi RSSI", f"{data['rssi']} dBm")
    return Panel(t, title="System")

def render_tasks(tasks):
    table = Table(title="FreeRTOS Tasks", expand=True)
    table.add_column("Task")
    table.add_column("State")
    table.add_column("Stack HW")

    for t in tasks:
        table.add_row(
            t["name"],
            str(t["state"]),
            str(t["stack"])
        )
    return Panel(table)

def render_wifi(rate):
    table = Table(show_header=False)
    table.add_row("Throughput", f"{rate:.2f} KB/s")
    return Panel(table, title="Wi-Fi")

def calculate_throughput(raw_len):
    global last_time
    now = time.time()
    dt = now - last_time
    last_time = now
    rate = raw_len / dt / 1024
    return rate

layout = Layout()
layout.split_column(
    Layout(name="top", size=8),
    Layout(name="bottom")
)
layout["top"].split_row(
    Layout(name="system"),
    Layout(name="wifi")
)
layout["bottom"].update(Panel("Waiting for ESP32...", title="Tasks"))

with Live(layout, refresh_per_second=4, console=console):
    while True:
        raw = ser.readline()
        if not raw:
            continue

        try:
            data = json.loads(raw.decode())
        except:
            continue

        rate = calculate_throughput(len(raw))

        layout["system"].update(render_system(data))
        layout["wifi"].update(render_wifi(rate))
        layout["bottom"].update(render_tasks(data["tasks"]))
