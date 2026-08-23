#!/usr/bin/env python3
"""btop-style live ESP32 serial monitor."""

from __future__ import annotations

import argparse
import configparser
import json
import os
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import serial
from serial.tools import list_ports
from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

THEMES = {
    "default": {
        "bg": "grey11", "fg": "grey85", "dim": "grey50", "accent": "cyan",
        "cpu": "green", "mem": "magenta", "net": "bright_cyan", "proc": "yellow",
        "hw": "bright_white", "warn": "bright_yellow", "danger": "bright_red",
        "ok": "bright_green", "select_bg": "grey23", "select_fg": "white", "header_bg": "grey7",
    },
    "nord": {
        "bg": "#2e3440", "fg": "#eceff4", "dim": "#4c566a", "accent": "#88c0d0",
        "cpu": "#a3be8c", "mem": "#b48ead", "net": "#81a1c1", "proc": "#ebcb8b",
        "hw": "#d8dee9", "warn": "#ebcb8b", "danger": "#bf616a",
        "ok": "#a3be8c", "select_bg": "#3b4252", "select_fg": "#eceff4", "header_bg": "#2e3440",
    },
    "dracula": {
        "bg": "#282a36", "fg": "#f8f8f2", "dim": "#6272a4", "accent": "#8be9fd",
        "cpu": "#50fa7b", "mem": "#ff79c6", "net": "#8be9fd", "proc": "#f1fa8c",
        "hw": "#bd93f9", "warn": "#ffb86c", "danger": "#ff5555",
        "ok": "#50fa7b", "select_bg": "#44475a", "select_fg": "#f8f8f2", "header_bg": "#21222c",
    },
    "gruvbox": {
        "bg": "#1d2021", "fg": "#ebdbb2", "dim": "#928374", "accent": "#83a598",
        "cpu": "#b8bb26", "mem": "#d3869b", "net": "#8ec07c", "proc": "#fabd2f",
        "hw": "#fe8019", "warn": "#fabd2f", "danger": "#fb4934",
        "ok": "#b8bb26", "select_bg": "#3c3836", "select_fg": "#ebdbb2", "header_bg": "#1d2021",
    },
}
THEME_NAMES = list(THEMES)
THEME = dict(THEMES["default"])
THEME_NAME = "default"
STATE_COLORS = {
    "running": "bright_green", "ready": "bright_blue", "blocked": "yellow",
    "suspended": "bright_magenta", "deleted": "red", "invalid": "dim",
}
PROTECTED_NAMES = {
    "idle", "idle0", "idle1", "ipc0", "ipc1", "tmr svc", "wifi", "wifin",
    "looptask", "esp_timer", "sys_evt", "arduino_events", "tit", "ipc task",
}

lock = threading.Lock()
running = True
paused = False
show_help = False
show_all_tasks = False
selected_index = 0
scroll_offset = 0
kill_confirm = False
pending_kill_pid = None
pending_kill_name = None
last_data: dict = {}
status_message = ""
status_until = 0.0
last_telemetry_at = 0.0
PORT = "auto"
BAUD = 115200
REFRESH = 12
HISTORY = 80
VISIBLE_ROWS = 16
telemetry_q: queue.Queue = queue.Queue()
command_q: queue.Queue = queue.Queue()
last_byte_time = time.time()
throughput_rate = 0.0
download_history: deque = deque(maxlen=HISTORY)
upload_history: deque = deque(maxlen=HISTORY)
cpu_history: deque = deque(maxlen=HISTORY)
heap_history: deque = deque(maxlen=HISTORY)
total_download = 0.0
total_upload = 0.0


def apply_theme(name: str) -> str:
    global THEME_NAME
    key = (name or "default").lower()
    if key not in THEMES:
        key = "default"
    THEME_NAME = key
    THEME.clear()
    THEME.update(THEMES[key])
    return key


def cycle_theme() -> str:
    idx = THEME_NAMES.index(THEME_NAME) if THEME_NAME in THEME_NAMES else 0
    return apply_theme(THEME_NAMES[(idx + 1) % len(THEME_NAMES)])


def is_protected(task: dict) -> bool:
    return bool(task.get("protected")) or str(task.get("name", "")).lower() in PROTECTED_NAMES


def visible_tasks(data: dict) -> list:
    tasks = data.get("tasks") or []
    return tasks if show_all_tasks else [t for t in tasks if not is_protected(t)]


def clamp_selection(n: int) -> None:
    global selected_index, scroll_offset
    if n <= 0:
        selected_index = 0
        scroll_offset = 0
        return
    selected_index = max(0, min(selected_index, n - 1))
    if selected_index < scroll_offset:
        scroll_offset = selected_index
    elif selected_index >= scroll_offset + VISIBLE_ROWS:
        scroll_offset = selected_index - VISIBLE_ROWS + 1


def set_status(message: str, duration: float = 4.0) -> None:
    global status_message, status_until
    with lock:
        status_message = message
        status_until = time.time() + duration


def normalize_payload(payload: dict) -> dict:
    data = dict(payload)
    tasks = []
    for task in data.get("tasks") or []:
        t = dict(task)
        t.setdefault("pid", t.get("pid", 0))
        t.setdefault("name", t.get("name", "?"))
        t.setdefault("state", t.get("state", "?"))
        t.setdefault("priority", t.get("priority", 0))
        t.setdefault("stack_hwm", t.get("stack_hwm", t.get("mem", 0)))
        t.setdefault("protected", t.get("protected", False))
        t.setdefault("cpu", t.get("cpu", 0))
        t.setdefault("user", t.get("user", "app"))
        tasks.append(t)
    data["tasks"] = tasks
    data.setdefault("cpu_mhz", data.get("cpu_mhz", 0))
    data.setdefault("max_cpu_mhz", data.get("max_cpu_mhz", 240))
    data.setdefault("cpu_core0", data.get("cpu_core0", 0))
    data.setdefault("cpu_core1", data.get("cpu_core1", 0))
    data.setdefault("heap", data.get("heap", 0))
    data.setdefault("total_heap", data.get("total_heap", 0))
    data.setdefault("min_heap", data.get("min_heap", 0))
    data.setdefault("uptime_ms", data.get("uptime_ms", 0))
    data.setdefault("task_count", data.get("task_count", len(tasks)))
    return data


def record_frame(raw_len: int, payload: dict) -> None:
    global last_byte_time, throughput_rate, total_download, total_upload, last_telemetry_at
    now = time.time()
    dt = max(now - last_byte_time, 1e-6)
    last_byte_time = now
    last_telemetry_at = now
    throughput_rate = raw_len / dt / 1024.0
    total_download += raw_len / 1024.0
    download_history.append(throughput_rate)
    tx = float(payload.get("tx_rate", 0) or 0)
    upload_history.append(tx)
    total_upload += tx * 0.1
    mhz = float(payload.get("cpu_mhz", 0) or 0)
    max_mhz = float(payload.get("max_cpu_mhz", 240) or 240)
    cpu_history.append((mhz / max_mhz) * 100 if max_mhz else 0)
    total = float(payload.get("total_heap") or 327680)
    free = float(payload.get("heap") or 0)
    heap_history.append(((total - free) / total) * 100 if total else 0)


def fmt_size(num) -> str:
    try:
        value = float(num)
    except (TypeError, ValueError):
        return "?"
    if value >= 1024 * 1024:
        return f"{value / 1024 / 1024:.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{int(value)} B"


def fmt_uptime(ms) -> str:
    seconds = int(ms or 0) // 1000
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def progress_bar(pct, width=24, fill=None) -> str:
    fill = fill or THEME["cpu"]
    try:
        pct = max(0.0, min(100.0, float(pct or 0)))
    except (TypeError, ValueError):
        pct = 0.0
    filled = max(0, min(width, int(round(pct / 100 * width))))
    return f"[{fill}]{'█' * filled}[/][{THEME['dim']}]{'░' * (width - filled)}[/]"


def sparkline(values, width=44, height=6, color=None) -> Text:
    color = color or THEME["cpu"]
    if not values:
        return Text(" " * width, style=THEME["dim"])
    vals = list(values)
    vals = ([0.0] * (width - len(vals)) + vals) if len(vals) < width else vals[-width:]
    peak = max(max(vals), 0.001)
    lines = []
    for row in range(height - 1, -1, -1):
        lo, hi = row / height, (row + 1) / height
        chars = []
        for val in vals:
            n = val / peak
            if n >= hi:
                chars.append("⣿")
            elif n >= lo + (hi - lo) * 0.66:
                chars.append("⣷")
            elif n >= lo + (hi - lo) * 0.33:
                chars.append("⣯")
            elif n >= lo:
                chars.append("⣀")
            else:
                chars.append(" ")
        lines.append("".join(chars))
    return Text("\n".join(lines), style=color)


def block_graph(values, width=30, height=4, color=None, ceiling=None) -> Text:
    color = color or THEME["net"]
    if not values:
        return Text("", style=THEME["dim"])
    vals = list(values)
    vals = ([0.0] * (width - len(vals)) + vals) if len(vals) < width else vals[-width:]
    peak = ceiling if ceiling else max(max(vals), 0.001)
    glyphs = " ▁▂▃▄▅▆▇█"
    rows = []
    for row in range(height - 1, -1, -1):
        line = Text()
        for val in vals:
            n = val / peak
            if int(n * height) > row:
                line.append(glyphs[min(8, int((n * height - row) * 8))], style=color)
            else:
                line.append(" ", style=THEME["dim"])
        rows.append(line)
    return Text("\n").join(rows)


def rssi_indicator(rssi) -> Text:
    try:
        rssi = int(rssi)
    except (TypeError, ValueError):
        rssi = 0
    if rssi == 0:
        return Text("── no link ──", style=THEME["dim"])
    if rssi >= -50:
        bars, label, color = 4, "excellent", THEME["ok"]
    elif rssi >= -60:
        bars, label, color = 3, "good", THEME["cpu"]
    elif rssi >= -70:
        bars, label, color = 2, "fair", THEME["warn"]
    else:
        bars, label, color = 1, "weak", THEME["danger"]
    meter = "".join("▮" if i < bars else "▯" for i in range(4))
    return Text.assemble((meter + " ", color), (f"{rssi} dBm ", THEME["fg"]), (label, THEME["dim"]))


def state_badge(state) -> Text:
    key = (state or "?").lower()
    color = STATE_COLORS.get(key, THEME["dim"])
    return Text(f" {(state or '?')[:10].ljust(10)} ", style=f"bold {color} on grey19")


def panel_title(icon: str, name: str, extra: str = "") -> str:
    text = f"[bold {THEME['fg']}]{icon}[/] [bold]{name}[/]"
    return text + (f"  [dim]{extra}[/]" if extra else "")


def task_summary(tasks) -> Text:
    counts: dict[str, int] = {}
    for task in tasks:
        state = task.get("state", "?")
        counts[state] = counts.get(state, 0) + 1
    if not counts:
        return Text("no tasks", style=THEME["dim"])
    return Text.assemble(*[
        (f"{state}:{n} ", STATE_COLORS.get(state.lower(), THEME["dim"]))
        for state, n in sorted(counts.items(), key=lambda item: -item[1])
    ])


def create_cpu_panel(data: dict) -> Panel:
    mhz = data.get("cpu_mhz", 0) or 0
    max_mhz = data.get("max_cpu_mhz", 240) or 240
    pct = (mhz / max_mhz) * 100 if max_mhz else 0
    core0 = data.get("cpu_core0", 0) or 0
    core1 = data.get("cpu_core1", 0) or 0
    grid = Table.grid(padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(width=8, justify="right")
    grid.add_row(Text.assemble(("clock ", THEME["dim"]), (str(mhz), THEME["accent"]), (" MHz", THEME["dim"])), Text(f"{pct:.0f}%", style=THEME["cpu"]))
    grid.add_row(progress_bar(pct, 28, THEME["cpu"]), "")
    grid.add_row(Text.assemble(("core0 ", THEME["dim"]), (f"{core0:.0f}%", "cyan")), "")
    grid.add_row(progress_bar(core0, 28, "cyan"), "")
    grid.add_row(Text.assemble(("core1 ", THEME["dim"]), (f"{core1:.0f}%", "bright_blue")), "")
    grid.add_row(progress_bar(core1, 28, "bright_blue"), "")
    body = Group(grid, Text(""), sparkline(cpu_history, color=THEME["cpu"]), Text.assemble(("uptime ", THEME["dim"]), (fmt_uptime(data.get("uptime_ms", 0)), THEME["fg"])))
    return Panel(body, title=panel_title("◉", "cpu", f"max {max_mhz} MHz"), box=box.ROUNDED, border_style=THEME["cpu"], title_align="left", padding=(0, 1))


def create_memory_panel(data: dict) -> Panel:
    total = data.get("total_heap", 327680) or 327680
    free = data.get("heap", 0) or 0
    used = max(0, total - free)
    pct = (used / total) * 100 if total else 0
    color = THEME["ok"] if pct < 55 else THEME["warn"] if pct < 80 else THEME["danger"]
    stats = Table.grid()
    stats.add_column(style=THEME["dim"], width=10)
    stats.add_column(justify="right", style=THEME["fg"])
    stats.add_row("total", fmt_size(total))
    stats.add_row("used", fmt_size(used))
    stats.add_row("free", fmt_size(free))
    stats.add_row("min free", fmt_size(data.get("min_heap", 0)))
    gauge = Table.grid()
    gauge.add_row(Text(f"{pct:.1f}% used", style=f"bold {color}"))
    gauge.add_row(progress_bar(pct, 22, color))
    gauge.add_row(Text(""))
    gauge.add_row(sparkline(heap_history, width=22, height=4, color=THEME["mem"]))
    return Panel(Columns([stats, gauge], expand=True), title=panel_title("▣", "mem", fmt_size(total)), box=box.ROUNDED, border_style=THEME["mem"], title_align="left", padding=(0, 1))


def create_network_panel(data: dict) -> Panel:
    down = data.get("rx_rate") or throughput_rate
    up = data.get("tx_rate", 0) or 0
    grid = Table.grid(padding=(0, 1))
    grid.add_column()
    grid.add_row(rssi_indicator(data.get("rssi", 0)))
    grid.add_row(Text(""))
    grid.add_row(Text.assemble(("▼ recv ", THEME["dim"]), (f"{down:6.1f}", THEME["net"]), (" KB/s", THEME["dim"])))
    grid.add_row(block_graph(download_history, color=THEME["net"], ceiling=50))
    grid.add_row(Text.assemble(("  total ", THEME["dim"]), (f"{total_download:.1f} KiB", THEME["fg"])))
    grid.add_row(Text.assemble(("▲ send ", THEME["dim"]), (f"{up:6.1f}", THEME["danger"]), (" KB/s", THEME["dim"])))
    grid.add_row(block_graph(upload_history, height=3, color=THEME["danger"], ceiling=20))
    grid.add_row(Text.assemble(("  total ", THEME["dim"]), (f"{total_upload:.1f} KiB", THEME["fg"])))
    return Panel(grid, title=panel_title("⇅", "net", "serial + wifi"), box=box.ROUNDED, border_style=THEME["net"], title_align="left", padding=(0, 1))


def create_hw_panel(data: dict) -> Panel:
    psram = data.get("psram") or 0
    psram_free = data.get("psram_free") or 0
    used = max(0, psram - psram_free) if psram else 0
    pct = (used / psram) * 100 if psram else 0
    temp = data.get("temp_c") or 0
    flash = data.get("flash") or 0
    grid = Table.grid(padding=(0, 1))
    grid.add_column(style=THEME["dim"], width=10)
    grid.add_column(style=THEME["fg"])
    grid.add_row("chip", str(data.get("chip") or "ESP32"))
    grid.add_row("temp", f"{temp:.1f} °C" if temp else "n/a")
    grid.add_row("flash", fmt_size(flash) if flash else "n/a")
    if psram:
        grid.add_row("psram", f"{fmt_size(used)} / {fmt_size(psram)}")
        grid.add_row("", progress_bar(pct, 22, THEME["hw"]))
    else:
        grid.add_row("gpu/psram", "none reported")
    return Panel(grid, title=panel_title("◈", "hw", "chip + memory"), box=box.ROUNDED, border_style=THEME["hw"], title_align="left", padding=(0, 1))


def create_detail_panel(data: dict) -> Panel:
    tasks = visible_tasks(data)
    with lock:
        idx = selected_index
    if not tasks:
        return Panel(Align.center(Text("select a task with ↑ ↓", style=THEME["dim"]), vertical="middle"), title=panel_title("›", "detail"), box=box.ROUNDED, border_style=THEME["dim"], padding=(0, 1))
    task = tasks[max(0, min(idx, len(tasks) - 1))]
    protected = is_protected(task)
    stack = task.get("stack_hwm", task.get("mem", 0))
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=THEME["dim"], width=9)
    grid.add_column(style=THEME["fg"])
    grid.add_column(style=THEME["dim"], width=8)
    grid.add_column(style=THEME["fg"])
    grid.add_row("pid", str(task.get("pid", "?")), "priority", str(task.get("priority", "?")))
    grid.add_row("name", str(task.get("name", "?")), "stack", fmt_size(stack))
    grid.add_row("state", str(task.get("state", "?")), "cpu", f"{task.get('cpu', 0)}%")
    grid.add_row("protected", "yes — blocked" if protected else "no — killable", "user", str(task.get("user", "?")))
    return Panel(grid, title=panel_title("›", "detail", str(task.get("name", ""))), box=box.ROUNDED, border_style=THEME["danger"] if protected else THEME["accent"], padding=(0, 1))


def kill_overlay() -> Panel | None:
    with lock:
        name, pid = pending_kill_name, pending_kill_pid
    if not name:
        return None
    body = Table.grid(padding=(0, 1))
    body.add_column(justify="center")
    body.add_row(Text("⚠  TERMINATE TASK", style=f"bold {THEME['danger']}"))
    body.add_row(Text(""))
    body.add_row(Text(str(name), style=f"bold {THEME['fg']}"))
    body.add_row(Text(f"pid {pid}", style=THEME["dim"]))
    body.add_row(Text(""))
    body.add_row(Text.assemble((" Y ", f"bold white on {THEME['danger']}"), (" confirm   ", THEME["dim"]), (" N ", "bold white on grey35"), (" cancel", THEME["dim"])))
    return Panel(Align.center(body, vertical="middle"), box=box.DOUBLE, border_style=THEME["danger"], width=44, padding=(1, 2))


def help_overlay() -> Panel:
    rows = [
        ("↑ ↓", "move through the task list"), ("PgUp / PgDn", "scroll the process pane"),
        ("A", "toggle user tasks / all tasks"), ("K then Y", "kill selected task after confirm"),
        ("N / Esc", "cancel a pending kill"), ("S", "pause or resume live graphs"),
        ("T", "cycle color theme"), ("H / ?", "toggle this help"), ("Q", "quit"),
    ]
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style=f"bold {THEME['accent']}", width=14)
    table.add_column(style=THEME["fg"])
    for key, desc in rows:
        table.add_row(key, desc)
    table.add_row("", Text("Protected system tasks cannot be killed.", style=THEME["dim"]))
    table.add_row("", Text(f"theme {THEME_NAME} · {PORT} @ {BAUD}", style=THEME["dim"]))
    return Panel(table, title=panel_title("?", "help", "keyboard"), box=box.DOUBLE, border_style=THEME["accent"], width=54, padding=(1, 2))


def create_tasks_panel(data: dict):
    all_tasks = data.get("tasks") or []
    shown = visible_tasks(data)
    count = data.get("task_count", len(all_tasks))
    with lock:
        sel = selected_index
        offset = scroll_offset
        confirm = kill_confirm
        pending_pid = pending_kill_pid
        help_on = show_help
    if not all_tasks:
        empty = Align.center(Group(Text("waiting for ESP32…", style=THEME["warn"]), Text("newline JSON @ serial", style=THEME["dim"])), vertical="middle")
        return Panel(empty, title=panel_title("☰", "proc", "0 tasks"), box=box.ROUNDED, border_style=THEME["proc"], padding=(1, 1))
    table = Table(show_header=True, header_style=f"bold {THEME['dim']}", expand=True, box=None, padding=(0, 1))
    table.add_column("", width=2, justify="center")
    table.add_column("PID", justify="right", style=THEME["accent"], width=5)
    table.add_column("NAME", style=THEME["fg"], min_width=12, max_width=16, no_wrap=True)
    table.add_column("STATE", width=12)
    table.add_column("PRIO", justify="right", width=4)
    table.add_column("STACK", justify="right", width=7)
    table.add_column("CPU", justify="right", width=4)
    table.add_column("", width=3)
    for local, task in enumerate(shown[offset: offset + VISIBLE_ROWS]):
        idx = offset + local
        pid = task.get("pid", 0)
        protected = is_protected(task)
        pending = pending_pid is not None and pid == pending_pid
        selected = idx == sel
        mark = Text("◌", style=f"blink {THEME['warn']}") if pending else Text("▸", style=f"bold {THEME['accent']}") if selected else Text(" ")
        style = f"bold {THEME['select_fg']} on {THEME['select_bg']}" if selected else (f"bold {THEME['warn']} on grey19" if pending else None)
        stack = task.get("stack_hwm", task.get("mem", 0)) or 0
        table.add_row(mark, str(pid), str(task.get("name", "?"))[:16], state_badge(task.get("state", "?")), str(task.get("priority", "?")), fmt_size(stack) if stack >= 1024 else f"{int(stack)}B", str(task.get("cpu", 0)), Text("🔒", style=THEME["dim"]) if protected else Text("  "), style=style)
    filt = "all" if show_all_tasks else "user"
    panel = Panel(table, title=panel_title("☰", "proc", f"{len(shown)}/{len(all_tasks)} · {filt} · {count} total"), subtitle=task_summary(all_tasks).plain, subtitle_align="left", box=box.ROUNDED, border_style=THEME["proc"], title_align="left", padding=(0, 0))
    extras = []
    if confirm:
        overlay = kill_overlay()
        if overlay:
            extras.append(Align.center(overlay))
    if help_on:
        extras.append(Align.center(help_overlay()))
    return Group(panel, *extras) if extras else panel


def create_header() -> Panel:
    with lock:
        is_paused = paused
        all_on = show_all_tasks
        msg = status_message
        until = status_until
    now = time.time()
    linked = bool(last_telemetry_at) and (now - last_telemetry_at) < 3.0
    left = Text.assemble(("  ◈ ", THEME["accent"]), ("ESP32", f"bold {THEME['fg']}"), (" MONITOR", THEME["dim"]))
    center = Text.assemble(("↑↓", THEME["fg"]), (" sel  ", THEME["dim"]), ("K", THEME["accent"]), (" kill  ", THEME["dim"]), ("A", THEME["accent"]), (f" {'ALL' if all_on else 'USER'}  ", THEME["dim"]), ("S", THEME["accent"]), (" pause  ", THEME["dim"]), ("H", THEME["accent"]), (" help  ", THEME["dim"]), ("Q", THEME["accent"]), (" quit", THEME["dim"]))
    right = Text.assemble((f" {'LINK' if linked else 'NO DATA'} ", THEME["ok"] if linked else THEME["danger"]), ("│ ", THEME["dim"]), (f"[{THEME['danger']}]● PAUSED[/]" if is_paused else f"[{THEME['ok']}]● LIVE[/]", ""), (" │ ", THEME["dim"]), (THEME_NAME, THEME["accent"]), (" │ ", THEME["dim"]), (time.strftime("%H:%M:%S"), THEME["accent"]))
    content: object = Columns([left, center, right], expand=True, equal=False)
    if msg and now < until:
        content = Group(content, Text(f"  › {msg}", style=THEME["fg"]))
    return Panel(content, box=box.HEAVY, style=f"{THEME['fg']} on {THEME['header_bg']}", padding=(0, 0))


def create_footer() -> Panel:
    age = f" │ last frame {time.time() - last_telemetry_at:.1f}s ago" if last_telemetry_at else ""
    return Panel(Text.assemble((f" {PORT}", THEME["dim"]), (" │ ", THEME["dim"]), (f"{BAUD} baud", THEME["dim"]), (" │ ", THEME["dim"]), (f"{throughput_rate:.2f} KB/s", THEME["net"]), (age, THEME["dim"]), (" │ ", THEME["dim"]), ("H help · T theme", THEME["dim"])), box=box.SQUARE, style=f"on {THEME['bg']}", padding=(0, 0))


def placeholder(title: str, color: str, message: str) -> Panel:
    return Panel(Align.center(Text(message, style=THEME["dim"]), vertical="middle"), title=panel_title("…", title), box=box.ROUNDED, border_style=color)


def build_layout(data: dict) -> Layout:
    layout = Layout(name="root")
    layout.split_column(Layout(name="header", size=4), Layout(name="body"), Layout(name="footer", size=1))
    layout["body"].split_row(Layout(name="left", ratio=5), Layout(name="right", ratio=6))
    layout["left"].split_column(Layout(name="cpu", size=15), Layout(name="mid", size=11), Layout(name="hw"))
    layout["mid"].split_row(Layout(name="mem"), Layout(name="net"))
    layout["right"].split_column(Layout(name="proc", ratio=3), Layout(name="detail", size=8))
    layout["header"].update(create_header())
    layout["footer"].update(create_footer())
    layout["right"]["proc"].update(create_tasks_panel(data))
    layout["right"]["detail"].update(create_detail_panel(data))
    with lock:
        is_paused = paused
    if is_paused:
        layout["left"]["cpu"].update(placeholder("cpu", THEME["cpu"], "⏸  PAUSED"))
        layout["mid"]["mem"].update(placeholder("mem", THEME["mem"], "⏸  PAUSED"))
        layout["mid"]["net"].update(placeholder("net", THEME["net"], "⏸  PAUSED"))
        layout["left"]["hw"].update(placeholder("hw", THEME["hw"], "⏸  PAUSED"))
    elif not data:
        layout["left"]["cpu"].update(placeholder("cpu", THEME["warn"], "waiting…"))
        layout["mid"]["mem"].update(placeholder("mem", THEME["dim"], "waiting…"))
        layout["mid"]["net"].update(placeholder("net", THEME["dim"], "waiting…"))
        layout["left"]["hw"].update(placeholder("hw", THEME["dim"], "waiting…"))
    else:
        layout["left"]["cpu"].update(create_cpu_panel(data))
        layout["mid"]["mem"].update(create_memory_panel(data))
        layout["mid"]["net"].update(create_network_panel(data))
        layout["left"]["hw"].update(create_hw_panel(data))
    return layout


def serial_worker(ser) -> None:
    global running, last_data, pending_kill_pid, pending_kill_name, kill_confirm
    while True:
        with lock:
            if not running:
                break
        try:
            while True:
                cmd = command_q.get_nowait()
                ser.write((json.dumps(cmd) + "\n").encode())
                ser.flush()
        except queue.Empty:
            pass
        try:
            raw = ser.readline()
        except serial.SerialException as exc:
            set_status(f"Serial error: {exc}")
            with lock:
                running = False
            break
        if not raw:
            continue
        try:
            payload = json.loads(raw.decode(errors="ignore"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("ack") == "kill":
            pid = payload.get("pid", "?")
            set_status(f"kill accepted — pid {pid}" if payload.get("ok") else f"kill rejected ({payload.get('reason', 'rejected')})", 6)
            with lock:
                pending_kill_pid = None
                pending_kill_name = None
                kill_confirm = False
            telemetry_q.put({"type": "ack", "data": payload})
            continue
        with lock:
            is_paused = paused
        if is_paused:
            continue
        payload = normalize_payload(payload)
        record_frame(len(raw), payload)
        with lock:
            last_data = payload
            clamp_selection(len(visible_tasks(payload)))
        telemetry_q.put({"type": "telemetry", "data": payload})


def move_selection(delta: int) -> None:
    global selected_index
    with lock:
        tasks = visible_tasks(last_data)
        if not tasks:
            return
        selected_index += delta
        clamp_selection(len(tasks))


def handle_key(ch) -> None:
    global running, paused, show_all_tasks, selected_index, show_help
    global kill_confirm, pending_kill_pid, pending_kill_name
    key = ch.lower() if isinstance(ch, str) and len(ch) == 1 else ch
    with lock:
        tasks = visible_tasks(last_data)
        confirm = kill_confirm
        pending_pid = pending_kill_pid
        pending_name = pending_kill_name
        help_on = show_help
    if confirm:
        if key == "y":
            if pending_pid is not None:
                command_q.put({"cmd": "kill", "pid": pending_pid})
                set_status(f"sending kill → {pending_name} (pid {pending_pid})…", 8)
            with lock:
                kill_confirm = False
        elif key in ("n", "q", "\x1b"):
            with lock:
                kill_confirm = False
                pending_kill_pid = None
                pending_kill_name = None
            set_status("kill cancelled")
        return
    if help_on and key in ("h", "?", "\x1b"):
        with lock:
            show_help = False
        return
    if key == "a":
        with lock:
            show_all_tasks = not show_all_tasks
            selected_index = 0
            clamp_selection(len(visible_tasks(last_data)))
    elif key == "s":
        with lock:
            paused = not paused
        set_status("paused" if paused else "live")
    elif key == "t":
        set_status(f"theme → {cycle_theme()}")
    elif key in ("h", "?"):
        with lock:
            show_help = not show_help
    elif key == "q":
        with lock:
            running = False
    elif key == "k":
        if not tasks:
            set_status("no task selected")
            return
        task = tasks[min(selected_index, len(tasks) - 1)]
        if is_protected(task):
            set_status(f"protected: {task.get('name')} — kill blocked")
            return
        with lock:
            pending_kill_pid = task.get("pid")
            pending_kill_name = task.get("name")
            kill_confirm = True
        set_status(f"confirm kill → {task.get('name')} (pid {task.get('pid')})", 10)


def keyboard_worker() -> None:
    if not sys.stdin.isatty():
        return
    if sys.platform == "win32":
        try:
            import msvcrt
        except ImportError:
            return
        while True:
            with lock:
                if not running:
                    break
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\xe0", "\x00"):
                    extra = msvcrt.getwch()
                    mapping = {"H": -1, "P": 1, "I": -8, "Q": 8}
                    if extra in mapping:
                        move_selection(mapping[extra])
                else:
                    handle_key(ch)
            else:
                time.sleep(0.04)
        return
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = None
    try:
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        while True:
            with lock:
                if not running:
                    break
            readable, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not readable:
                continue
            try:
                ch = sys.stdin.read(1)
            except OSError:
                continue
            if ch == "\x1b":
                seq = ""
                more, _, _ = select.select([sys.stdin], [], [], 0.04)
                if more:
                    seq = sys.stdin.read(1)
                    more2, _, _ = select.select([sys.stdin], [], [], 0.04)
                    if more2:
                        seq += sys.stdin.read(1)
                if seq == "[A":
                    move_selection(-1)
                elif seq == "[B":
                    move_selection(1)
                elif seq.startswith("[5"):
                    move_selection(-8)
                elif seq.startswith("[6"):
                    move_selection(8)
                else:
                    handle_key("\x1b")
                continue
            handle_key(ch)
    except Exception:
        pass
    finally:
        if old is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except Exception:
                pass


def discover_ports():
    return list(list_ports.comports())


def auto_port() -> str | None:
    preferred, others = [], []
    for info in discover_ports():
        blob = f"{info.description} {info.hwid}".lower()
        if "bluetooth" in blob:
            continue
        if any(tok in blob for tok in ("usb", "uart", "cp210", "ch340", "ch910", "ftdi", "wch", "esp")):
            preferred.append(info.device)
        else:
            others.append(info.device)
    return (preferred or others or [None])[0]


def load_ini(path: Path) -> dict:
    cfg = configparser.ConfigParser()
    cfg.read(path)
    out = {}
    if cfg.has_section("serial"):
        out["port"] = cfg.get("serial", "port", fallback=None)
        baud = cfg.get("serial", "baud", fallback=None)
        if baud:
            out["baud"] = int(baud)
    if cfg.has_section("ui"):
        out["theme"] = cfg.get("ui", "theme", fallback=None)
        refresh = cfg.get("ui", "refresh", fallback=None)
        if refresh:
            out["refresh"] = int(refresh)
        if cfg.has_option("ui", "show_all_tasks"):
            out["show_all_tasks"] = cfg.getboolean("ui", "show_all_tasks")
        history = cfg.get("ui", "history", fallback=None)
        if history:
            out["history"] = int(history)
    return {k: v for k, v in out.items() if v is not None}


def apply_settings(args) -> None:
    global PORT, BAUD, REFRESH, HISTORY, show_all_tasks
    global download_history, upload_history, cpu_history, heap_history
    merged = {"port": "auto", "baud": 115200, "theme": "default", "refresh": 12, "show_all_tasks": False, "history": 80}
    candidates = []
    if args.config:
        candidates.append(Path(args.config).expanduser())
    candidates.extend([Path("esp32-monitor.ini"), Path.home() / ".config/esp32-monitor/config.ini"])
    if os.environ.get("XDG_CONFIG_HOME"):
        candidates.append(Path(os.environ["XDG_CONFIG_HOME"]) / "esp32-monitor/config.ini")
    for path in candidates:
        if path.is_file():
            merged.update(load_ini(path))
            break
    if args.port:
        merged["port"] = args.port
    if args.baud:
        merged["baud"] = args.baud
    if args.theme:
        merged["theme"] = args.theme
    PORT = merged["port"]
    BAUD = int(merged["baud"])
    REFRESH = max(2, int(merged["refresh"]))
    HISTORY = max(20, int(merged["history"]))
    show_all_tasks = bool(merged["show_all_tasks"])
    apply_theme(merged["theme"])
    download_history = deque(maxlen=HISTORY)
    upload_history = deque(maxlen=HISTORY)
    cpu_history = deque(maxlen=HISTORY)
    heap_history = deque(maxlen=HISTORY)
    if not PORT or str(PORT).lower() == "auto":
        found = auto_port()
        if found:
            PORT = found


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="esp32-monitor", description="btop-style live ESP32 serial monitor")
    parser.add_argument("-p", "--port", help="serial device (default: auto)")
    parser.add_argument("-b", "--baud", type=int, help="baud rate (default: 115200)")
    parser.add_argument("-t", "--theme", choices=THEME_NAMES, help="color theme")
    parser.add_argument("-c", "--config", help="INI config file")
    parser.add_argument("--list-ports", action="store_true", help="list serial ports and exit")
    return parser.parse_args(argv)


def run_monitor() -> int:
    global running
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
    except serial.SerialException as exc:
        console.print(f"[red]serial open failed:[/] {exc}")
        console.print(f"[dim]tried:[/] {PORT}")
        ports = discover_ports()
        if ports:
            console.print("[dim]available:[/]")
            for info in ports:
                console.print(f"  {info.device}  {info.description}")
        return 1
    io_thread = threading.Thread(target=serial_worker, args=(ser,), daemon=True)
    kb_thread = threading.Thread(target=keyboard_worker, daemon=True)
    io_thread.start()
    kb_thread.start()
    try:
        with Live(build_layout(last_data), refresh_per_second=REFRESH, console=console, screen=True, transient=True) as live:
            while True:
                with lock:
                    if not running:
                        break
                    snapshot = dict(last_data)
                while True:
                    try:
                        item = telemetry_q.get_nowait()
                    except queue.Empty:
                        break
                    if item["type"] == "telemetry":
                        snapshot = normalize_payload(item["data"])
                live.update(build_layout(snapshot))
                time.sleep(max(0.02, 1.0 / (REFRESH * 2)))
    except KeyboardInterrupt:
        pass
    finally:
        with lock:
            running = False
        io_thread.join(timeout=1.0)
        try:
            ser.close()
        except Exception:
            pass
        console.print("[green]monitor closed[/]")
    return 0


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.list_ports:
        ports = discover_ports()
        if not ports:
            print("no serial ports found")
            raise SystemExit(1)
        for info in ports:
            print(f"{info.device}\t{info.description}")
        raise SystemExit(0)
    apply_settings(args)
    raise SystemExit(run_monitor())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user")
    except SystemExit:
        raise
    except Exception as exc:
        print(f"\nERROR: {exc}")
        import traceback
        traceback.print_exc()
        raise SystemExit(1) from exc
