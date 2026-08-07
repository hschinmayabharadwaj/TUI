import json
import queue
import serial
import sys
import threading
import time
from collections import deque

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

PORT = "/dev/cu.usbserial-0001"
BAUD = 115200

console = Console()

# Shared state (main thread reads; keyboard/serial threads write via lock)
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

telemetry_queue = queue.Queue()
command_queue = queue.Queue()

last_time = time.time()
throughput_rate = 0.0
download_history = deque(maxlen=60)
upload_history = deque(maxlen=60)
cpu_history = deque(maxlen=50)
heap_history = deque(maxlen=50)
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
    global last_time, throughput_rate, total_download
    now = time.time()
    dt = max(now - last_time, 1e-6)
    last_time = now
    throughput_rate = raw_len / dt / 1024
    total_download += raw_len / 1024
    download_history.append(throughput_rate)
    return throughput_rate


def create_graph(data, width, height, color="green", max_val=None):
    if not data:
        return ["" for _ in range(height)]

    values = list(data)
    if max_val is None:
        max_val = max(values) if values else 1
    max_val = max(max_val, 0.001)

    if len(values) < width:
        values = [0] * (width - len(values)) + values
    else:
        values = values[-width:]

    blocks = " ▁▂▃▄▅▆▇█"
    lines = []

    for row in range(height - 1, -1, -1):
        line = ""
        for val in values:
            normalized = val / max_val
            block_height = int(normalized * height)
            if block_height > row:
                char_idx = min(8, int((normalized * height - row) * 8))
                line += f"[{color}]{blocks[char_idx]}[/]"
            else:
                line += " "
        lines.append(line)

    return lines


def create_cpu_panel(data):
    cpu_mhz = data.get("cpu_mhz", 0)
    max_mhz = data.get("max_cpu_mhz", 240)
    cpu_percent = (cpu_mhz / max_mhz) * 100 if max_mhz else 0
    cpu_history.append(cpu_percent)

    uptime = data.get("uptime_ms", 0) // 1000
    days, remainder = divmod(uptime, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    graph_lines = create_graph(cpu_history, 40, 6, "green", 100)
    graph_text = "\n".join(graph_lines)

    core0 = data.get("cpu_core0", cpu_percent * 0.5)
    core1 = data.get("cpu_core1", cpu_percent * 0.5)

    content = f"""[bold white]CPU[/] [green]{'█' * int(cpu_percent / 5)}{'░' * (20 - int(cpu_percent / 5))}[/] {cpu_percent:.0f}%
[dim]C0[/]  [cyan]{'█' * int(core0 / 5)}{'░' * (20 - int(core0 / 5))}[/] {core0:.0f}%
[dim]C1[/]  [cyan]{'█' * int(core1 / 5)}{'░' * (20 - int(core1 / 5))}[/] {core1:.0f}%

{graph_text}

[dim]up[/] {days}d {hours:02d}:{minutes:02d}:{seconds:02d}"""

    return Panel(content, title="[bold]cpu[/]", box=box.ROUNDED, border_style="green", title_align="left")


def create_memory_panel(data):
    total_heap = data.get("total_heap", 327680)
    free_heap = data.get("heap", 0)
    min_heap = data.get("min_heap", 0)
    used_heap = total_heap - free_heap if free_heap > 0 else 0
    heap_percent = (used_heap / total_heap) * 100 if total_heap else 0
    heap_history.append(heap_percent)

    def fmt_size(b):
        if b >= 1024 * 1024:
            return f"{b / 1024 / 1024:.1f} MiB"
        if b >= 1024:
            return f"{b / 1024:.1f} KiB"
        return f"{b} B"

    used_bar = int(heap_percent / 5)
    free_bar = 20 - used_bar
    color = "green" if heap_percent < 60 else "yellow" if heap_percent < 80 else "red"

    content = f"""[bold]Total:[/]       {fmt_size(total_heap):>12}
[bold]Used:[/]        {fmt_size(used_heap):>12}
  [{color}]{heap_percent:.0f}%[/]  [{color}]{'█' * used_bar}[/][dim]{'░' * free_bar}[/]

[bold]Available:[/]   {fmt_size(free_heap):>12}
  [green]{100 - heap_percent:.0f}%[/]  [green]{'█' * free_bar}[/][dim]{'░' * used_bar}[/]

[bold]Min Free:[/]    {fmt_size(min_heap):>12}
  [dim]Watermark (lowest ever)[/]

[bold]Free:[/]        {fmt_size(free_heap):>12}
  [dim]1%[/]"""

    return Panel(content, title="[bold]mem[/]", box=box.ROUNDED, border_style="magenta", title_align="left")


def create_network_panel(data):
    global total_upload

    rssi = data.get("rssi", 0)
    download_speed = throughput_rate
    upload_speed = data.get("tx_rate", 0)
    upload_history.append(upload_speed)
    total_upload += upload_speed * 0.1

    graph_lines = create_graph(download_history, 35, 8, "cyan", 50)
    graph_text = "\n".join(graph_lines)

    content = f"""{graph_text}

[green]▼[/] {download_speed:.1f} KB/s     [dim](0 bitps)[/]
[green]▼[/] Top:     ({download_speed * 8:.1f} Kibps)
[green]▼[/] Total:   {total_download:.2f} KiB

[red]▲[/] {upload_speed:.1f} KB/s     [dim](0 bitps)[/]
[red]▲[/] Top:     ({upload_speed * 8:.1f} Kibps)
[red]▲[/] Total:   {total_upload:.2f} KiB
                       [bold]download                upload[/]"""

    return Panel(content, title=f"[bold]net[/] [dim]RSSI:{rssi}dBm[/]", box=box.ROUNDED, border_style="cyan", title_align="left")


def visible_tasks(data):
    all_tasks = data.get("tasks", [])
    if show_all_tasks:
        return all_tasks
    return [t for t in all_tasks if not is_protected_task(t)]


def create_tasks_panel(data):
    task_count = data.get("task_count", 0)
    all_tasks = data.get("tasks", [])
    tasks_to_show = visible_tasks(data)

    table = Table(show_header=True, header_style="bold", expand=True, box=None, padding=(0, 1))
    table.add_column("", width=1)
    table.add_column("Pid:", style="cyan", width=6, justify="right")
    table.add_column("Program:", style="green", width=16)
    table.add_column("State:", style="white", width=10)
    table.add_column("Prio:", width=5, justify="right")
    table.add_column("Stack:", width=8, justify="right")
    table.add_column("MemB", width=8, justify="right")
    table.add_column("User:", style="yellow", width=8)

    if not all_tasks:
        return Panel(
            "[dim]Waiting for task data from ESP32...[/]",
            title=f"[bold]proc[/] [dim]tasks: {task_count}[/]",
            box=box.ROUNDED,
            border_style="yellow",
            title_align="left",
        )

    with state_lock:
        sel = selected_index
        confirm = kill_confirm
        pending_pid = pending_kill_pid
        pending_name = pending_kill_name

    for idx, task in enumerate(tasks_to_show[:15]):
        mem = task.get("mem", task.get("stack_hwm", 0))
        stack = task.get("stack_hwm", mem)
        pid = task.get("pid", 0)
        name = task.get("name", "unknown")
        protected = is_protected_task(task)

        marker = " "
        row_style = None
        if idx == sel:
            marker = "▶"
            row_style = "bold reverse"
        if pending_pid is not None and pid == pending_pid:
            marker = "⏳"
            row_style = "bold yellow"

        state_str = task.get("state", "?")
        prio = task.get("priority", "?")
        user = task.get("user", "system")
        if protected:
            user = "[dim]system[/]"

        table.add_row(
            marker,
            str(pid),
            name,
            state_str,
            str(prio),
            f"{stack // 1024}K" if stack >= 1024 else f"{stack}B",
            f"{mem // 1024}K" if mem >= 1024 else f"{mem}B",
            user,
            style=row_style,
        )

    subtitle_parts = [f"{len(tasks_to_show)}/{len(all_tasks)}"]
    if confirm and pending_name:
        subtitle_parts.append(f"[bold red]Kill {pending_name} (pid {pending_pid})? [Y] confirm [N/Esc] cancel[/]")
    elif pending_pid is not None and not confirm:
        subtitle_parts.append(f"[yellow]pending kill pid {pending_pid}…[/]")

    return Panel(
        table,
        title="[bold]proc[/] [dim]↑↓ select │ K kill │ A all │ S pause │ Q quit[/]",
        box=box.ROUNDED,
        border_style="yellow",
        title_align="left",
        subtitle=" │ ".join(subtitle_parts),
        subtitle_align="right",
    )


def create_header():
    with state_lock:
        is_paused = paused
        all_tasks_on = show_all_tasks
        msg = status_message
        msg_until = status_message_until

    status = "[green]●[/]" if not is_paused else "[red]●[/]"
    time_str = time.strftime("%H:%M:%S")
    all_tasks_status = "[green]ON[/]" if all_tasks_on else "[dim]OFF[/]"

    status_line = ""
    if msg and time.time() < msg_until:
        status_line = f"  │  {msg}"

    return Panel(
        f" [bold]↑↓[/] select [bold]K[/] kill [bold]Y[/] confirm [bold]A[/] alltasks [bold]S[/] pause [bold]Q[/] quit"
        f"  │  AllTasks:{all_tasks_status}  │  {status} {'PAUSED' if is_paused else 'RUNNING'}"
        f"  │  [cyan]{time_str}[/]{status_line}",
        box=box.HEAVY,
        style="white on black",
        title="[bold cyan]ESP32 Monitor[/]",
        title_align="left",
    )


def build_btop_layout(data):
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=1),
    )

    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1),
    )

    layout["left"].split_column(
        Layout(name="cpu", size=12),
        Layout(name="bottom_left"),
    )

    layout["bottom_left"].split_row(
        Layout(name="mem"),
        Layout(name="net"),
    )

    layout["right"].update(create_tasks_panel(data))
    layout["header"].update(create_header())
    layout["footer"].update(
        Text.from_markup(f"[dim]Port: {PORT} │ Baud: {BAUD} │ Rate: {throughput_rate:.2f} KB/s[/]")
    )

    with state_lock:
        is_paused = paused

    if is_paused:
        layout["cpu"].update(Panel("[bold red]⏸ PAUSED[/] - Press S to resume", title="cpu", box=box.ROUNDED, border_style="red"))
        layout["mem"].update(Panel("[dim]Paused[/]", title="mem", box=box.ROUNDED, border_style="dim"))
        layout["net"].update(Panel("[dim]Paused[/]", title="net", box=box.ROUNDED, border_style="dim"))
    elif not data:
        layout["cpu"].update(Panel("[yellow]Waiting for ESP32...[/]", title="cpu", box=box.ROUNDED, border_style="yellow"))
        layout["mem"].update(Panel("[dim]No data[/]", title="mem", box=box.ROUNDED, border_style="dim"))
        layout["net"].update(Panel("[dim]No data[/]", title="net", box=box.ROUNDED, border_style="dim"))
    else:
        layout["cpu"].update(create_cpu_panel(data))
        layout["mem"].update(create_memory_panel(data))
        layout["net"].update(create_network_panel(data))

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
            set_status(f"[red]Serial error: {exc}[/]")
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
                set_status(f"[green]Kill ack: pid {pid} deleted[/]")
            else:
                reason = payload.get("reason", "rejected")
                set_status(f"[red]Kill rejected pid {pid}: {reason}[/]")
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
            set_status("[yellow]Keyboard input unavailable on this platform[/]")
            return

        while True:
            with state_lock:
                if not running:
                    break
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                _handle_key(ch, msvcrt)
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
        selected_index = max(0, min(selected_index + delta, len(tasks[:15]) - 1))


def _handle_key(ch, msvcrt_mod=None):
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
                set_status(f"[yellow]Sending kill for pid {pending_pid} ({pending_name})…[/]", duration=8.0)
            with state_lock:
                kill_confirm = False
        elif key in ("n", "q", "\x1b") or key.lower() == "n":
            with state_lock:
                kill_confirm = False
                pending_kill_pid = None
                pending_kill_name = None
            set_status("[dim]Kill cancelled[/]")
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
    elif key in ("k", "K"):
        if not tasks:
            set_status("[yellow]No task selected[/]")
            return
        idx = min(selected_index, len(tasks[:15]) - 1)
        task = tasks[idx]
        if is_protected_task(task):
            set_status(f"[red]Cannot kill protected task: {task.get('name')}[/]")
            return
        task_pid = task.get("pid")
        task_name = task.get("name")
        with state_lock:
            pending_kill_pid = task_pid
            pending_kill_name = task_name
            kill_confirm = True
        set_status(f"[bold yellow]Confirm kill {task_name} (pid {task_pid})? Press Y[/]")


def main():
    global running, last_data

    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
    except serial.SerialException as exc:
        console.print(f"[red]Error opening serial port: {exc}[/]")
        console.print(f"[yellow]Make sure the ESP32 is connected to {PORT}[/]")
        return

    io_thread = threading.Thread(target=serial_worker, args=(ser,), daemon=True)
    kb_thread = threading.Thread(target=keyboard_worker, daemon=True)
    io_thread.start()
    kb_thread.start()

    console.clear()

    try:
        with Live(build_btop_layout(last_data), refresh_per_second=10, console=console, screen=True) as live:
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
                time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        with state_lock:
            running = False
        io_thread.join(timeout=1.0)
        ser.close()
        console.clear()
        console.print("[green]ESP32 Monitor closed.[/]")


if __name__ == "__main__":
    main()
