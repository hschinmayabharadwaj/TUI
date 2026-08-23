#!/usr/bin/env python3
"""Test if the TUI layout renders with sample data"""

import json

# Sample telemetry data from your ESP32
sample_data = {
    "cpu_mhz": 240,
    "max_cpu_mhz": 240,
    "cpu_core0": 74,
    "cpu_core1": 95,
    "heap": 263448,
    "total_heap": 341928,
    "min_heap": 250000,
    "rssi": -55,
    "tx_rate": 2,
    "uptime_ms": 45000,
    "task_count": 8,
    "tasks": [
        {"pid":1,"name":"loopTask","state":"Running","priority":1,"stack_hwm":3584,"cmd":"loopTask","threads":1,"user":"system","mem":3584,"cpu":0,"protected":True},
        {"pid":2,"name":"IDLE0","state":"Ready","priority":0,"stack_hwm":1024,"cmd":"IDLE0","threads":1,"user":"system","mem":1024,"cpu":0,"protected":True},
        {"pid":3,"name":"IDLE1","state":"Ready","priority":0,"stack_hwm":1024,"cmd":"IDLE1","threads":1,"user":"system","mem":1024,"cpu":0,"protected":True},
        {"pid":4,"name":"wifi","state":"Blocked","priority":23,"stack_hwm":2048,"cmd":"wifi","threads":1,"user":"system","mem":2048,"cpu":0,"protected":True},
    ]
}

print("Testing TUI layout with sample data...")
print("=" * 70)
print()

# Import the TUI module
import esp32_tui

# Initialize some state
esp32_tui.last_data = sample_data
esp32_tui.cpu_history.append(50)
esp32_tui.download_history.append(2.5)
esp32_tui.upload_history.append(0.5)
esp32_tui.heap_history.append(60)

# Try to build the layout
try:
    layout = esp32_tui.build_btop_layout(sample_data)
    print("✓ Layout created successfully!")
    print()
    print("Layout structure:")
    print(f"  Type: {type(layout)}")
    print(f"  Has content: {layout is not None}")
    print()
    
    # Try to render it
    from rich.console import Console
    console = Console()
    console.print(layout)
    print()
    print("✓ Layout renders correctly!")
    
except Exception as e:
    print(f"✗ Error building layout: {e}")
    import traceback
    traceback.print_exc()
