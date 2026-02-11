import json
import serial
import time
import sys
import threading
from collections import deque
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich import box

PORT = "/dev/cu.usbserial-0001"
BAUD = 115200

console = Console()

# Global state
running = True
paused = False
show_all_tasks = False  # Toggle with 'A' key
last_data = {}
last_time = time.time()
throughput_rate = 0.0
download_history = deque(maxlen=60)  # For network graph
upload_history = deque(maxlen=60)
cpu_history = deque(maxlen=50)  # For CPU graph
heap_history = deque(maxlen=50)  # For memory graph
total_download = 0.0
total_upload = 0.0


def calculate_throughput(raw_len):
    """Calculate data throughput in KB/s"""
    global last_time, throughput_rate, total_download
    now = time.time()
    dt = max(now - last_time, 1e-6)
    last_time = now
    throughput_rate = raw_len / dt / 1024  # KB/s
    total_download += raw_len / 1024  # Total KB
    download_history.append(throughput_rate)
    return throughput_rate


def create_graph(data, width, height, color="green", max_val=None):
    """Create ASCII graph like btop"""
    if not data:
        return ["" for _ in range(height)]
    
    values = list(data)
    if max_val is None:
        max_val = max(values) if values else 1
    max_val = max(max_val, 0.001)
    
    # Pad or trim to width
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
    """Create CPU panel with graph (top-left like btop)"""
    cpu_mhz = data.get('cpu_mhz', 0)
    max_mhz = data.get('max_cpu_mhz', 240)  # Get from data or default ESP32 max
    cpu_percent = (cpu_mhz / max_mhz) * 100 if max_mhz else 0
    cpu_history.append(cpu_percent)
    
    uptime = data.get('uptime_ms', 0) // 1000
    days, remainder = divmod(uptime, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # Create mini graph
    graph_lines = create_graph(cpu_history, 40, 6, "green", 100)
    graph_text = "\n".join(graph_lines)
    
    # Get core usage from data (ESP32 has 2 cores)
    core0 = data.get('cpu_core0', cpu_percent * 0.5)
    core1 = data.get('cpu_core1', cpu_percent * 0.5)
    
    content = f"""[bold white]CPU[/] [green]{'█' * int(cpu_percent/5)}{'░' * (20-int(cpu_percent/5))}[/] {cpu_percent:.0f}%
[dim]C0[/]  [cyan]{'█' * int(core0/5)}{'░' * (20-int(core0/5))}[/] {core0:.0f}%
[dim]C1[/]  [cyan]{'█' * int(core1/5)}{'░' * (20-int(core1/5))}[/] {core1:.0f}%

{graph_text}

[dim]up[/] {days}d {hours:02d}:{minutes:02d}:{seconds:02d}"""
    
    return Panel(content, title="[bold]cpu[/]", box=box.ROUNDED, border_style="green", title_align="left")


def create_memory_panel(data):
    """Create memory panel (like btop's mem section)"""
    total_heap = data.get('total_heap', 327680)  # Get from data, default ESP32 SRAM
    free_heap = data.get('heap', 0)
    min_heap = data.get('min_heap', 0)
    used_heap = total_heap - free_heap if free_heap > 0 else 0
    heap_percent = (used_heap / total_heap) * 100 if total_heap else 0
    heap_history.append(heap_percent)
    
    # Format sizes
    def fmt_size(b):
        if b >= 1024*1024:
            return f"{b/1024/1024:.1f} MiB"
        elif b >= 1024:
            return f"{b/1024:.1f} KiB"
        return f"{b} B"
    
    used_bar = int(heap_percent / 5)
    free_bar = 20 - used_bar
    
    # Color based on usage
    color = "green" if heap_percent < 60 else "yellow" if heap_percent < 80 else "red"
    
    content = f"""[bold]Total:[/]       {fmt_size(total_heap):>12}
[bold]Used:[/]        {fmt_size(used_heap):>12}
  [{color}]{heap_percent:.0f}%[/]  [{color}]{'█' * used_bar}[/][dim]{'░' * free_bar}[/]

[bold]Available:[/]   {fmt_size(free_heap):>12}
  [green]{100-heap_percent:.0f}%[/]  [green]{'█' * free_bar}[/][dim]{'░' * used_bar}[/]

[bold]Min Free:[/]    {fmt_size(min_heap):>12}
  [dim]Watermark (lowest ever)[/]

[bold]Free:[/]        {fmt_size(free_heap):>12}
  [dim]1%[/]"""
    
    return Panel(content, title="[bold]mem[/]", box=box.ROUNDED, border_style="magenta", title_align="left")


def create_network_panel(data):
    """Create network panel with graph (like btop's net section)"""
    global total_upload
    
    rssi = data.get('rssi', 0)
    download_speed = throughput_rate
    upload_speed = data.get('tx_rate', 0)
    upload_history.append(upload_speed)
    total_upload += upload_speed * 0.1
    
    # Create download/upload graph
    graph_lines = create_graph(download_history, 35, 8, "cyan", 50)
    graph_text = "\n".join(graph_lines)
    
    content = f"""{graph_text}

[green]▼[/] {download_speed:.1f} KB/s     [dim](0 bitps)[/]
[green]▼[/] Top:     ({download_speed*8:.1f} Kibps)
[green]▼[/] Total:   {total_download:.2f} KiB

[red]▲[/] {upload_speed:.1f} KB/s     [dim](0 bitps)[/]
[red]▲[/] Top:     ({upload_speed*8:.1f} Kibps)
[red]▲[/] Total:   {total_upload:.2f} KiB
                       [bold]download                upload[/]"""
    
    return Panel(content, title=f"[bold]net[/] [dim]RSSI:{rssi}dBm[/]", box=box.ROUNDED, border_style="cyan", title_align="left")


def create_tasks_panel(data):
    """Create processes/tasks panel (like btop's proc section)"""
    task_count = data.get('task_count', 0)
    
    table = Table(show_header=True, header_style="bold", expand=True, box=None, padding=(0, 1))
    table.add_column("Pid:", style="cyan", width=6, justify="right")
    table.add_column("Program:", style="green", width=18)
    table.add_column("Command:", style="white", width=28)
    table.add_column("Threads:", width=8, justify="right")
    table.add_column("User:", style="yellow", width=10)
    table.add_column("MemB", width=8, justify="right")
    table.add_column("Cpu%", width=6, justify="right", style="green")
    
    # Get tasks from ESP32 data
    all_tasks = data.get('tasks', [])
    
    if not all_tasks:
        # No tasks data received
        return Panel(
            "[dim]Waiting for task data from ESP32...[/]\n\n[yellow]Send 'tasks' array in JSON[/]",
            title=f"[bold]proc[/] [dim]tasks: {task_count}[/]",
            box=box.ROUNDED,
            border_style="yellow",
            title_align="left"
        )
    
    # Show all tasks or filter based on 'A' toggle
    if show_all_tasks:
        tasks_to_show = all_tasks
    else:
        # Filter out idle and system tasks if not showing all
        tasks_to_show = [t for t in all_tasks if t.get("name", "").upper() not in ["IDLE0", "IDLE1", "IPC0", "IPC1"]]
    
    for task in tasks_to_show[:15]:  # Max rows that fit
        mem = task.get('mem', 0)
        table.add_row(
            str(task.get("pid", 0)),
            task.get("name", "unknown"),
            task.get("cmd", task.get("name", "")),
            str(task.get("threads", 1)),
            task.get("user", "system"),
            f"{mem//1024}K" if mem >= 1024 else f"{mem}B",
            f"{task.get('cpu', 0.0):.1f}"
        )
    
    # Filter bar at bottom
    filter_text = "[dim]↑ [/][bold]select[/] [dim]↓│[/][bold]info[/] [dim]↓↓[/][bold]terminate[/][dim]↓[/][bold]kill[/][dim]↓[/][bold]signals[/][dim]↓[/][bold]Nice↓[/]"
    
    return Panel(table, title=f"[bold]proc[/] [dim]filter[/]", box=box.ROUNDED, border_style="yellow", 
                 title_align="left", subtitle=f"[dim]{len(tasks_to_show)}/{len(all_tasks)}[/]", subtitle_align="right")


def create_header():
    """Create btop-style header bar"""
    status = "[green]●[/]" if not paused else "[red]●[/]"
    time_str = time.strftime("%H:%M:%S")
    
    keys = "[bold]C[/]:cpu [bold]M[/]:mem [bold]W[/]:wifi [bold]A[/]:alltasks [bold]S[/]:stop [bold]Q[/]:quit"
    all_tasks_status = "[green]ON[/]" if show_all_tasks else "[dim]OFF[/]"
    
    return Panel(
        f" {keys}  │  AllTasks:{all_tasks_status}  │  {status} {'PAUSED' if paused else 'RUNNING'}  │  [cyan]{time_str}[/]",
        box=box.HEAVY,
        style="white on black",
        title="[bold cyan]ESP32 Monitor[/]",
        title_align="left"
    )


def create_footer():
    """Create btop-style footer"""
    return Text.from_markup(
        f"[dim]Port: {PORT} │ Baud: {BAUD} │ Rate: {throughput_rate:.2f} KB/s[/]"
    )


def build_btop_layout(data):
    """Build the main btop-style layout showing all panels"""
    layout = Layout()
    
    # Main structure: header, body, footer
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )
    
    # Body split: left column (cpu+mem+net) and right column (proc)
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1),
    )
    
    # Left column: cpu on top, then mem and net side by side
    layout["left"].split_column(
        Layout(name="cpu", size=12),
        Layout(name="bottom_left"),
    )
    
    layout["bottom_left"].split_row(
        Layout(name="mem"),
        Layout(name="net"),
    )
    
    # Right column: processes/tasks
    layout["right"].update(create_tasks_panel(data))
    
    # Fill in panels
    layout["header"].update(create_header())
    
    if paused:
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


def keyboard_listener():
    """Listen for keyboard input in a separate thread"""
    global running, paused, show_all_tasks
    
    import tty
    import termios
    
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    
    try:
        tty.setcbreak(fd)
        while running:
            ch = sys.stdin.read(1).lower()
            if ch == 'a':
                show_all_tasks = not show_all_tasks
            elif ch == 's':
                paused = not paused
            elif ch == 'q':
                running = False
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def main():
    global last_data, running, throughput_rate
    
    try:
        ser = serial.Serial(PORT, BAUD, timeout=0.1)
    except serial.SerialException as e:
        console.print(f"[red]Error opening serial port: {e}[/]")
        console.print(f"[yellow]Make sure the ESP32 is connected to {PORT}[/]")
        return
    
    # Start keyboard listener thread
    kb_thread = threading.Thread(target=keyboard_listener, daemon=True)
    kb_thread.start()
    
    console.clear()
    
    try:
        with Live(build_btop_layout(last_data), refresh_per_second=10, console=console, screen=True) as live:
            while running:
                if not paused:
                    raw = ser.readline()
                    if raw:
                        try:
                            data = json.loads(raw.decode(errors="ignore"))
                            last_data = data
                            calculate_throughput(len(raw))
                        except json.JSONDecodeError:
                            pass
                
                live.update(build_btop_layout(last_data))
                time.sleep(0.05)
    
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        console.clear()
        console.print("[green]ESP32 Monitor closed.[/]")


if __name__ == "__main__":
    main()
