#!/usr/bin/env python3
"""Debug wrapper for esp32_tui.py - shows what's happening"""

import sys
import traceback

print("=" * 70)
print("ESP32 Monitor TUI - Debug Mode")
print("=" * 70)
print()

try:
    # Import and run the main TUI
    import esp32_tui
    esp32_tui.main()
except KeyboardInterrupt:
    print("\n✓ Stopped by user (Ctrl+C)")
    sys.exit(0)
except Exception as e:
    print("\n" + "=" * 70)
    print("ERROR: TUI crashed")
    print("=" * 70)
    print(f"\nException type: {type(e).__name__}")
    print(f"Exception message: {e}")
    print("\nFull traceback:")
    traceback.print_exc()
    print("\n" + "=" * 70)
    sys.exit(1)
