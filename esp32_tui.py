import json
import queue
import serial
import sys
import threading
import time
from collections import deque

from rich import box
from rich.align import Align
from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

PORT = "/dev/cu.usbserial-0001"
BAUD = 115200

console = Console()

# ── btop-inspired palette ────────────────────────────────────────────────────
THEME = {
    "bg": "grey11",
    "fg": "grey85",
    "dim": "grey50",
    "accent": "cyan",
    "cpu": "green",
    "mem": "magenta",
    "net": "bright_cyan",
    "proc": "yellow",
    "warn": "bright_yellow",
    "danger": "bright_red",
    "ok": "bright_green",
    "select_bg": "grey23",
    "select_fg": "white",
    "header_bg": "grey7",
}

STATE_COLORS = {
    "running": "bright_green",
    "ready": "bright_blue",
    "blocked": "yellow",
    "suspended": "bright_magenta",
    "deleted": "red",
    "invalid": "dim",
}

# Shared state
state_lock = threading.Lock()
running = True
paused = False
show_all_tasks = False
selected_index = 0
kill_confirm = False
pending_kill_pid = None
pending_kill_name = None
last_data = {}
status_message = ""
status_message_until = 0.0
last_telemetry_at = 0.0

telemetry_queue = queue.Queue()
command_queue = queue.Queue()

last_time = time.time()
throughput_rate = 0.0
download_history = deque(maxlen=80)
upload_history = deque(maxlen=80)
cpu_history = deque(maxlen=80)
heap_history = deque(maxlen=80)
total_download = 0.0
total_upload = 0.0

PROTECTED_TASKS = {
    "idle", "idle0", "idle1", "ipc0", "ipc1",
    "tmr svc", "wifi", "looptask", "esp_timer",
}


def is_protected_task(task):
    if task.get("protected"):
        return True
    return task.get("name", "").lower() in PROTECTED_TASKS


def calculate_throughput(raw_len):
    global last_time, throughput_rate, total_download, last_telemetry_at
    now = time.time()
    dt = max(now - last_time, 1e-6)
    last_time = now
    throughput_rate = raw_len / dt / 1024
    total_download += raw_len / 1024
    download_history.append(throughput_rate)
    last_telemetry_at = now
    return throughput_rate


def fmt_size(b):
    if b >= 1024 * 1024:
        return f"{b / 1024 / 1024:.1f} MiB"
    if b >= 1024:
        return f"{b / 1024:.1f} KiB"
    return f"{b} B"


def fmt_uptime(ms):
    s = ms // 1000
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}d {h:02d}:{m:02d}:{s:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def progress_bar(pct, width=24, fill=None, empty="░"):
    fill = fill or THEME["cpu"]
    filled = max(0, min(width, int(round(pct / 100 * width))))
    return f"[{fill}]{'█' * filled}[/][{THEME['dim']}]{empty * (width - filled)}[/]"


def braille_sparkline(values, width=48, height=8):
    """Render a smooth sparkline using Unicode braille (btop-style)."""
    if not values:
        return Text(" " * width, style=THEME["dim"])

    vals = list(values)
    if len(vals) < width:
        vals = [0.0] * (width - len(vals)) + vals
    else:
        vals = vals[-width:]

    peak = max(max(vals), 0.001)
    normalized = [v / peak for v in vals]

    lines = []
    for row in range(height - 1, -1, -1):
        chars = []
        threshold_lo = row / height
        threshold_hi = (row + 1) / height
        for val in normalized:
            if val >= threshold_hi:
                chars.append("⣿")
            elif val >= threshold_lo + (threshold_hi - threshold_lo) * 0.66:
                chars.append("⣷")
            elif val >= threshold_lo + (threshold_hi - threshold_lo) * 0.33:
                chars.append("⣯")
            elif val >= threshold_lo:
                chars.append("⣀")
            else:
                chars.append(" ")
        lines.append("".join(chars))

    return Text("\n".join(lines), style=THEME["cpu"])


def block_graph(values, width=40, height=6, color=THEME["net"], ceiling=None):
    if not values:
        return Text("", style=THEME["dim"])

    vals = list(values)
    if len(vals) < width:
        vals = [0.0] * (width - len(vals)) + vals
    else:
        vals = vals[-width:]

    peak = ceiling if ceiling else max(max(vals), 0.001)
    blocks = " ▁▂▃▄▅▆▇█"
    lines = []
    for row in range(height - 1, -1, -1):
        line = Text()
        for val in vals:
            norm = val / peak
            block_h = int(norm * height)
            if block_h > row:
                idx = min(8, int((norm * height - row) * 8))
                line.append(blocks[idx], style=color)
            else:
                line.append(" ", style=THEME["dim"])
        lines.append(line)
    return Text("\n").join(lines)


def rssi_indicator(rssi):
    """WiFi signal strength as bars + label."""
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

    bar = "".join("▮" if i < bars else "▯" for i in range(4))
    return Text.assemble(
        (bar + " ", color),
        (f"{rssi} dBm ", THEME["fg"]),
        (label, THEME["dim"]),
    )


def state_badge(state):
    key = (state or "?").lower()
    color = STATE_COLORS.get(key, THEME["dim"])
    label = (state or "?")[:10].ljust(10)
    return Text(f" {label} ", style=f"bold {color} on grey19")


def panel_title(icon, name, extra=""):
    parts = f"[bold {THEME['fg']}]{icon}[/] [bold {name}][/]"
    if extra:
        parts += f"  [dim]{extra}[/]"
    return parts


def visible_tasks(data):
    all_tasks = data.get("tasks", [])
    if show_all_tasks:
        return all_tasks
    return [t for t in all_tasks if not is_protected_task(t)]


def task_state_summary(tasks):
    counts = {}
    for t in tasks:
        s = t.get("state", "?")
        counts[s] = counts.get(s, 0) + 1
    if not counts:
        return Text("no tasks", style=THEME["dim"])
    parts = []
    for state, n in sorted(counts.items(), key=lambda x: -x[1]):
        color = STATE_COLORS.get(state.lower(), THEME["dim"])
        parts.append((f"{state}:{n} ", color))
    return Text.assemble(*parts)


def create_cpu_panel(data):
    cpu_mhz = data.get("cpu_mhz", 0)
    max_mhz = data.get("max_cpu_mhz", 240)
    cpu_pct = (cpu_mhz / max_mhz) * 100 if max_mhz else 0
    cpu_history.append(cpu_pct)

    core0 = data.get("cpu_core0", cpu_pct * 0.55)
    core1 = data.get("cpu_core1", cpu_pct * 0.45)
    uptime = fmt_uptime(data.get("uptime_ms", 0))

    spark = braille_sparkline(cpu_history, width=44, height=7)

    grid = Table.grid(padding=(0, 1))
    grid.add_column(ratio=1)
    grid.add_column(width=8, justify="right")

    grid.add_row(
        Text.assemble(("clock ", THEME["dim"]), (f"{cpu_mhz}", THEME["accent"]), (" MHz", THEME["dim"])),
        Text(f"{cpu_pct:.0f}%", style=THEME["cpu"]),
    )
    grid.add_row(progress_bar(cpu_pct, width=28, fill=THEME["cpu"]), "")
    grid.add_row("", "")
    grid.add_row(
        Text.assemble(("core0 ", THEME["dim"]), (f"{core0:.0f}%", "cyan")),
        "",
    )
    grid.add_row(progress_bar(core0, width=28, fill="cyan"), "")
    grid.add_row(
        Text.assemble(("core1 ", THEME["dim"]), (f"{core1:.0f}%", "bright_blue")),
        "",
    )
    grid.add_row(progress_bar(core1, width=28, fill="bright_blue"), "")

    body = Group(
        grid,
        Text(""),
        spark,
        Text.assemble(("uptime ", THEME["dim"]), (uptime, THEME["fg"])),
    )

    return Panel(
        body,
        title=panel_title("◉", "cpu", f"max {max_mhz} MHz"),
        box=box.ROUNDED,
        border_style=THEME["cpu"],
        title_align="left",
        padding=(0, 1),
    )


def create_memory_panel(data):
    total = data.get("total_heap", 327680)
    free = data.get("heap", 0)
    min_free = data.get("min_heap", 0)
    used = max(0, total - free)
    pct = (used / total) * 100 if total else 0
    heap_history.append(pct)

    if pct < 55:
        bar_color = THEME["ok"]
    elif pct < 80:
        bar_color = THEME["warn"]
    else:
        bar_color = THEME["danger"]

    spark = braille_sparkline(heap_history, width=28, height=5)
    spark.stylize(THEME["mem"])

    stats = Table.grid(padding=(0, 0))
    stats.add_column(style=THEME["dim"], width=10)
    stats.add_column(justify="right", style=THEME["fg"])
    stats.add_row("total", fmt_size(total))
    stats.add_row("used", fmt_size(used))
    stats.add_row("free", fmt_size(free))
    stats.add_row("min free", fmt_size(min_free))

    gauge = Table.grid(padding=(0, 0))
    gauge.add_row(Text(f"{pct:.1f}% used", style=f"bold {bar_color}"))
    gauge.add_row(progress_bar(pct, width=26, fill=bar_color))
    gauge.add_row(Text(""))
    gauge.add_row(spark)
    gauge.add_row(Text(""))

    content = Columns([stats, gauge], equal=False, expand=True)

    return Panel(
        content,
        title=panel_title("▣", "mem", fmt_size(total)),
        box=box.ROUNDED,
        border_style=THEME["mem"],
        title_align="left",
        padding=(0, 1),
    )


def create_network_panel(data):
    global total_upload

    rssi = data.get("rssi", 0)
    dl = throughput_rate
    ul = data.get("tx_rate", 0)
    upload_history.append(ul)
    total_upload += ul * 0.1

    dl_graph = block_graph(download_history, width=30, height=5, color=THEME["net"], ceiling=50)
    ul_graph = block_graph(upload_history, width=30, height=3, color=THEME["danger"], ceiling=20)

    grid = Table.grid(padding=(0, 1))
    grid.add_column()
    grid.add_row(rssi_indicator(rssi))
    grid.add_row(Text(""))
    grid.add_row(Text.assemble(("▼ down ", THEME["dim"]), (f"{dl:6.1f}", THEME["net"]), (" KB/s", THEME["dim"])))
    grid.add_row(dl_graph)
    grid.add_row(Text.assemble(("  total ", THEME["dim"]), (f"{total_download:.1f} KiB", THEME["fg"])))
    grid.add_row(Text(""))
    grid.add_row(Text.assemble(("▲ up   ", THEME["dim"]), (f"{ul:6.1f}", THEME["danger"]), (" KB/s", THEME["dim"])))
    grid.add_row(ul_graph)
    grid.add_row(Text.assemble(("  total ", THEME["dim"]), (f"{total_upload:.1f} KiB", THEME["fg"])))

    return Panel(
        grid,
        title=panel_title("⇅", "net", "serial telemetry"),
        box=box.ROUNDED,
        border_style=THEME["net"],
        title_align="left",
        padding=(0, 1),
    )


def selected_task_detail(data):
    tasks = visible_tasks(data)
    with state_lock:
        idx = selected_index

    if not tasks or idx >= len(tasks[:18]):
        return Panel(
            Align.center(Text("select a task with ↑ ↓", style=THEME["dim"]), vertical="middle"),
            title=panel_title("›", "detail"),
            box=box.ROUNDED,
            border_style=THEME["dim"],
            height=5,
            padding=(0, 1),
        )

    task = tasks[idx]
    protected = is_protected_task(task)
    stack = task.get("stack_hwm", task.get("mem", 0))

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=THEME["dim"], width=8)
    grid.add_column(style=THEME["fg"])
    grid.add_column(style=THEME["dim"], width=8)
    grid.add_column(style=THEME["fg"])

    grid.add_row("pid", str(task.get("pid", "?")), "priority", str(task.get("priority", "?")))
    grid.add_row("name", task.get("name", "?"), "stack", fmt_size(stack))
    grid.add_row("state", task.get("state", "?"), "user", task.get("user", "system"))
    grid.add_row(
        "protected",
        "yes — cannot kill" if protected else "no — killable",
        "mem",
        fmt_size(task.get("mem", stack)),
    )

    border = THEME["danger"] if protected else THEME["accent"]
    return Panel(
        grid,
        title=panel_title("›", "detail", task.get("name", "")),
        box=box.ROUNDED,
        border_style=border,
        height=7,
        padding=(0, 1),
    )


def create_kill_overlay():
    with state_lock:
        name = pending_kill_name
        pid = pending_kill_pid

    if not name:
        return None

    body = Table.grid(padding=(0, 1))
    body.add_column(justify="center")
    body.add_row(Text("⚠  TERMINATE TASK", style=f"bold {THEME['danger']}"))
    body.add_row(Text(""))
    body.add_row(Text(f"{name}", style=f"bold {THEME['fg']}"))
    body.add_row(Text(f"pid {pid}", style=THEME["dim"]))
    body.add_row(Text(""))
    body.add_row(
        Text.assemble(
            ("  ", THEME["dim"]),
            (" Y ", f"bold white on {THEME['danger']}"),
            (" confirm   ", THEME["dim"]),
            (" N ", "bold white on grey35"),
            (" cancel  ", THEME["dim"]),
        )
    )

    return Panel(
        Align.center(body, vertical="middle"),
        box=box.DOUBLE,
        border_style=THEME["danger"],
        padding=(1, 2),
        width=42,
    )


def create_tasks_panel(data):
    all_tasks = data.get("tasks", [])
    tasks_to_show = visible_tasks(data)
    task_count = data.get("task_count", len(all_tasks))

    with state_lock:
        sel = selected_index
        confirm = kill_confirm
        pending_pid = pending_kill_pid

    if not all_tasks:
        empty = Align.center(
            Group(
                Text("⏳ waiting for ESP32…", style=THEME["warn"]),
                Text("check serial port & baud 115200", style=THEME["dim"]),
            ),
            vertical="middle",
        )
        return Panel(
            empty,
            title=panel_title("☰", "proc", f"0 tasks"),
            box=box.ROUNDED,
            border_style=THEME["proc"],
            padding=(1, 1),
        )

    table = Table(
        show_header=True,
        header_style=f"bold {THEME['dim']}",
        expand=True,
        box=None,
        padding=(0, 1),
        row_styles=["", f"on {THEME['bg']}"],
    )
    table.add_column("", width=2, justify="center")
    table.add_column("PID", justify="right", style=THEME["accent"], width=5)
    table.add_column("NAME", style=THEME["fg"], min_width=14, max_width=18, no_wrap=True)
    table.add_column("STATE", width=12)
    table.add_column("PRIO", justify="right", width=4)
    table.add_column("STACK", justify="right", width=7)
    table.add_column("", width=4)

    max_rows = 18
    for idx, task in enumerate(tasks_to_show[:max_rows]):
        pid = task.get("pid", 0)
        name = task.get("name", "?")
        stack = task.get("stack_hwm", task.get("mem", 0))
        protected = is_protected_task(task)
        is_selected = idx == sel
        is_pending = pending_pid is not None and pid == pending_pid

        if is_pending:
            marker = Text("◌", style=f"blink {THEME['warn']}")
        elif is_selected:
            marker = Text("▸", style=f"bold {THEME['accent']}")
        else:
            marker = Text(" ", style=THEME["dim"])

        lock = Text("🔒", style=THEME["dim"]) if protected else Text("  ")

        row_style = None
        if is_selected:
            row_style = f"bold {THEME['select_fg']} on {THEME['select_bg']}"
        elif is_pending:
            row_style = f"bold {THEME['warn']} on grey19"

        table.add_row(
            marker,
            str(pid),
            name[:18],
            state_badge(task.get("state", "?")),
            str(task.get("priority", "?")),
            fmt_size(stack) if stack >= 1024 else f"{stack}B",
            lock,
            style=row_style,
        )

    summary = task_state_summary(all_tasks)
    filter_label = "all" if show_all_tasks else "user"
    title_extra = f"{len(tasks_to_show)}/{len(all_tasks)} shown · {filter_label} · {task_count} total"

    proc_body = Group(table, Text(""))

    panel = Panel(
        proc_body,
        title=panel_title("☰", "proc", title_extra),
        subtitle=Align.left(summary),
        box=box.ROUNDED,
        border_style=THEME["proc"],
        title_align="left",
        padding=(0, 0),
    )

    if confirm:
        overlay = create_kill_overlay()
        if overlay:
            return Group(
                panel,
                Align.center(overlay),
            )

    return panel


def create_header():
    with state_lock:
        is_paused = paused
        all_on = show_all_tasks
        msg = status_message
        msg_until = status_message_until

    now = time.time()
    linked = (now - last_telemetry_at) < 3.0 if last_telemetry_at else False
    link_style = THEME["ok"] if linked else THEME["danger"]
    link_label = "LINK" if linked else "NO DATA"

    status_dot = f"[{THEME['danger']}]● PAUSED[/]" if is_paused else f"[{THEME['ok']}]● LIVE[/]"
    tasks_mode = f"[{THEME['accent']}]ALL[/]" if all_on else f"[{THEME['dim']}]USER[/]"

    left = Text.assemble(
        ("  ◈ ", THEME["accent"]),
        ("ESP32", f"bold {THEME['fg']}"),
        (" MONITOR", THEME["dim"]),
    )

    center = Text.assemble(
        (" ↑↓ ", THEME["dim"]),
        ("sel", THEME["fg"]),
        (" │ ", THEME["dim"]),
        ("K", THEME["accent"]),
        (" kill ", THEME["dim"]),
        ("│ ", THEME["dim"]),
        ("A", THEME["accent"]),
        (f" {tasks_mode} ", THEME["dim"]),
        ("│ ", THEME["dim"]),
        ("S", THEME["accent"]),
        (" pause ", THEME["dim"]),
        ("│ ", THEME["dim"]),
        ("Q", THEME["accent"]),
        (" quit", THEME["dim"]),
    )

    right = Text.assemble(
        (f" {link_label} ", link_style),
        ("│ ", THEME["dim"]),
        (status_dot, ""),
        (" │ ", THEME["dim"]),
        (time.strftime("%H:%M:%S"), THEME["accent"]),
    )

    bar = Columns([left, center, right], expand=True, equal=False)

    content = bar
    if msg and now < msg_until:
        content = Group(bar, Text(f"  › {msg}", style=THEME["fg"]))

    return Panel(
        content,
        box=box.HEAVY,
        style=f"{THEME['fg']} on {THEME['header_bg']}",
        padding=(0, 0),
    )


def create_footer():
    age = ""
    if last_telemetry_at:
        age = f" │ last frame {time.time() - last_telemetry_at:.1f}s ago"

    return Panel(
        Text.assemble(
            (f" {PORT}", THEME["dim"]),
            (" │ ", THEME["dim"]),
            (f"{BAUD} baud", THEME["dim"]),
            (" │ ", THEME["dim"]),
            (f"{throughput_rate:.2f} KB/s", THEME["net"]),
            (age, THEME["dim"]),
            (" │ ", THEME["dim"]),
            ("rich tui", THEME["dim"]),
        ),
        box=box.SQUARE,
        style=f"on {THEME['bg']}",
        padding=(0, 0),
    )


def build_btop_layout(data):
    layout = Layout(name="root")
    layout.split_column(
        Layout(name="header", size=4),
        Layout(name="body"),
        Layout(name="footer", size=1),
    )

    layout["body"].split_row(
        Layout(name="left", ratio=5),
        Layout(name="right", ratio=6),
    )

    layout["left"].split_column(
        Layout(name="cpu", size=16),
        Layout(name="bottom_left"),
    )

    layout["bottom_left"].split_row(
        Layout(name="mem", ratio=1),
        Layout(name="net", ratio=1),
    )

    layout["right"].split_column(
        Layout(name="proc", ratio=3),
        Layout(name="detail", size=7),
    )

    layout["header"].update(create_header())
    layout["footer"].update(create_footer())
    layout["right"]["proc"].update(create_tasks_panel(data))
    layout["right"]["detail"].update(selected_task_detail(data))

    with state_lock:
        is_paused = paused

    if is_paused:
        paused_panel = lambda t, c: Panel(
            Align.center(Text("⏸  PAUSED", style=f"bold {THEME['danger']}"), vertical="middle"),
            title=panel_title("⏸", t),
            box=box.ROUNDED,
            border_style=c,
        )
        layout["left"]["cpu"].update(paused_panel("cpu", THEME["cpu"]))
        layout["left"]["mem"].update(paused_panel("mem", THEME["mem"]))
        layout["left"]["net"].update(paused_panel("net", THEME["net"]))
    elif not data:
        waiting = lambda t, c: Panel(
            Align.center(Text("waiting…", style=THEME["dim"]), vertical="middle"),
            title=panel_title("…", t),
            box=box.ROUNDED,
            border_style=c,
        )
        layout["left"]["cpu"].update(waiting("cpu", THEME["warn"]))
        layout["left"]["mem"].update(waiting("mem", THEME["dim"]))
        layout["left"]["net"].update(waiting("net", THEME["dim"]))
    else:
        layout["left"]["cpu"].update(create_cpu_panel(data))
        layout["left"]["mem"].update(create_memory_panel(data))
        layout["left"]["net"].update(create_network_panel(data))

    return layout


def set_status(message, duration=4.0):
    global status_message, status_message_until
    with state_lock:
        status_message = message
        status_message_until = time.time() + duration


def serial_worker(ser):
    global running, last_data, pending_kill_pid, pending_kill_name, kill_confirm

    while True:
        with state_lock:
            if not running:
                break

        try:
            while True:
                cmd = command_queue.get_nowait()
                ser.write((json.dumps(cmd) + "\n").encode())
        except queue.Empty:
            pass

        try:
            raw = ser.readline()
        except serial.SerialException as exc:
            set_status(f"[{THEME['danger']}]Serial error: {exc}[/]")
            with state_lock:
                running = False
            break

        if not raw:
            continue

        try:
            payload = json.loads(raw.decode(errors="ignore"))
        except json.JSONDecodeError:
            continue

        if payload.get("ack") == "kill":
            pid = payload.get("pid", "?")
            if payload.get("ok"):
                set_status(f"[{THEME['ok']}]✓ killed pid {pid}[/]", duration=5)
            else:
                reason = payload.get("reason", "rejected")
                set_status(f"[{THEME['danger']}]✗ kill rejected ({reason})[/]", duration=6)
            with state_lock:
                pending_kill_pid = None
                pending_kill_name = None
                kill_confirm = False
            telemetry_queue.put({"type": "ack", "data": payload})
            continue

        calculate_throughput(len(raw))
        with state_lock:
            last_data = payload
        telemetry_queue.put({"type": "telemetry", "data": payload})


def keyboard_worker():
    global running, paused, show_all_tasks, selected_index
    global kill_confirm, pending_kill_pid, pending_kill_name

    if not sys.stdin.isatty():
        return

    if sys.platform == "win32":
        try:
            import msvcrt
        except ImportError:
            set_status(f"[{THEME['warn']}]Keyboard unavailable on this platform[/]")
            return

        while True:
            with state_lock:
                if not running:
                    break
            if msvcrt.kbhit():
                _handle_key(msvcrt.getwch())
            else:
                time.sleep(0.05)
        return

    import termios
    import tty

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)
        while True:
            with state_lock:
                if not running:
                    break

            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    _move_selection(-1)
                elif seq == "[B":
                    _move_selection(1)
                continue
            _handle_key(ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _move_selection(delta):
    global selected_index
    with state_lock:
        tasks = visible_tasks(last_data)
        if not tasks:
            return
        selected_index = max(0, min(selected_index + delta, len(tasks[:18]) - 1))


def _handle_key(ch):
    global running, paused, show_all_tasks, selected_index
    global kill_confirm, pending_kill_pid, pending_kill_name

    key = ch.lower() if isinstance(ch, str) and len(ch) == 1 else ch

    with state_lock:
        tasks = visible_tasks(last_data)
        confirm = kill_confirm
        pending_pid = pending_kill_pid
        pending_name = pending_kill_name

    if confirm:
        if key in ("y", "Y"):
            if pending_pid is not None:
                command_queue.put({"cmd": "kill", "pid": pending_pid})
                set_status(
                    f"[{THEME['warn']}]sending kill → {pending_name} (pid {pending_pid})…[/]",
                    duration=8,
                )
            with state_lock:
                kill_confirm = False
        elif key in ("n", "\x1b") or key == "q":
            with state_lock:
                kill_confirm = False
                pending_kill_pid = None
                pending_kill_name = None
            set_status(f"[{THEME['dim']}]kill cancelled[/]")
        return

    if key == "a":
        with state_lock:
            show_all_tasks = not show_all_tasks
            selected_index = 0
    elif key == "s":
        with state_lock:
            paused = not paused
    elif key == "q":
        with state_lock:
            running = False
    elif key == "k":
        if not tasks:
            set_status(f"[{THEME['warn']}]no task selected[/]")
            return
        idx = min(selected_index, len(tasks[:18]) - 1)
        task = tasks[idx]
        if is_protected_task(task):
            set_status(f"[{THEME['danger']}]protected: {task.get('name')}[/]")
            return
        with state_lock:
            pending_kill_pid = task.get("pid")
            pending_kill_name = task.get("name")
            kill_confirm = True
        set_status(
            f"[{THEME['warn']}]confirm kill → {task.get('name')} (pid {task.get('pid')})[/]",
            duration=10,
        )


def main():
    global running, last_data

    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
    except serial.SerialException as exc:
        console.print(f"[{THEME['danger']}]serial open failed:[/] {exc}")
        console.print(f"[{THEME['dim']}]expected device:[/] {PORT}")
        return

    io_thread = threading.Thread(target=serial_worker, args=(ser,), daemon=True)
    kb_thread = threading.Thread(target=keyboard_worker, daemon=True)
    io_thread.start()
    kb_thread.start()

    console.clear()

    try:
        with Live(
            build_btop_layout(last_data),
            refresh_per_second=15,
            console=console,
            screen=True,
            transient=False,
        ) as live:
            while True:
                with state_lock:
                    if not running:
                        break
                    snapshot = last_data

                while True:
                    try:
                        item = telemetry_queue.get_nowait()
                    except queue.Empty:
                        break
                    if item["type"] == "telemetry":
                        snapshot = item["data"]

                live.update(build_btop_layout(snapshot))
                time.sleep(0.04)
    except KeyboardInterrupt:
        pass
    finally:
        with state_lock:
            running = False
        io_thread.join(timeout=1.0)
        ser.close()
        console.clear()
        console.print(f"[{THEME['ok']}]monitor closed[/]")
