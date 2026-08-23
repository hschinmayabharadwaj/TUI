#!/usr/bin/env python3
"""Simple serial test - just read and print JSON lines from ESP32"""

import serial
import sys
import time

PORT = "/dev/cu.usbserial-0001"
BAUD = 115200

print("=" * 70)
print("ESP32 Serial Test")
print("=" * 70)
print(f"Port: {PORT}")
print(f"Baud: {BAUD}")
print()

try:
    ser = serial.Serial(PORT, BAUD, timeout=1.0)
    print("✓ Serial port opened successfully")
    print()
    print("Reading data (Ctrl+C to stop)...")
    print("-" * 70)
    
    line_count = 0
    start_time = time.time()
    
    while True:
        try:
            raw = ser.readline()
            if raw:
                line_count += 1
                elapsed = time.time() - start_time
                
                try:
                    text = raw.decode('utf-8', errors='ignore').strip()
                    print(f"[{elapsed:6.2f}s] Line {line_count}: {text[:100]}")
                    
                    # Try to parse as JSON
                    if text.startswith('{'):
                        import json
                        data = json.loads(text)
                        print(f"           JSON keys: {', '.join(data.keys())}")
                        if 'heap' in data:
                            print(f"           Heap: {data['heap']} bytes")
                        if 'rssi' in data:
                            print(f"           RSSI: {data['rssi']} dBm")
                except Exception as e:
                    print(f"           Parse error: {e}")
                
                print()
            else:
                # No data received
                if time.time() - start_time > 5 and line_count == 0:
                    print("⚠️  No data received after 5 seconds")
                    print("Check:")
                    print("  1. Is the firmware uploaded?")
                    print("  2. Is the ESP32 powered on?")
                    print("  3. Press the RST button on ESP32")
                    break
                    
        except KeyboardInterrupt:
            print("\n" + "-" * 70)
            print(f"✓ Received {line_count} lines in {time.time() - start_time:.1f} seconds")
            break
            
except serial.SerialException as e:
    print(f"✗ Serial error: {e}")
    sys.exit(1)
finally:
    if 'ser' in locals():
        ser.close()
        print("✓ Serial port closed")
