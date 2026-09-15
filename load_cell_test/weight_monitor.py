#!/usr/bin/env python3
"""
Weight Change Monitor — detects when items are placed/removed.

This demonstrates the core logic needed for kiosk integration:
    - Detects when weight increases (item placed)
    - Detects when weight decreases (item removed)
    - Filters out noise and settling vibrations
    - Reports stable weight with event type

Useful for testing before integrating with ui_main.py.

Usage:
    sudo python3 weight_monitor.py
"""

import argparse
import os
import sys
import time

from hx711 import HX711


def main():
    parser = argparse.ArgumentParser(description="Weight Change Monitor")
    parser.add_argument("--dout", type=int, default=5)
    parser.add_argument("--sck", type=int, default=6)
    parser.add_argument("--cal", type=str, default="calibration.json")
    parser.add_argument("--threshold", type=float, default=5.0,
                        help="Minimum weight change to trigger event (grams, default: 5)")
    parser.add_argument("--settle-time", type=float, default=1.0,
                        help="Seconds to wait for weight to stabilize (default: 1.0)")
    args = parser.parse_args()

    print("=" * 60)
    print("  Weight Change Monitor")
    print("  (Detects item placement and removal)")
    print("=" * 60)
    print()

    hx = HX711(dout_pin=args.dout, pd_sck_pin=args.sck)

    if os.path.exists(args.cal):
        hx.load_calibration(args.cal)
    else:
        print(f"❌ Calibration file '{args.cal}' not found!")
        print("   Run 'sudo python3 calibrate.py' first.")
        hx.cleanup()
        sys.exit(1)

    print()
    print(f"  Change threshold : {args.threshold} g")
    print(f"  Settle time      : {args.settle_time} s")
    print()

    # Initial tare
    print("⏳ Taring the platform...")
    hx.tare(times=20)
    print()
    print("✅ Ready! Place or remove items on the platform.")
    print("   Press Ctrl+C to stop.")
    print("-" * 60)
    print()

    last_stable_weight = 0.0
    event_count = 0

    try:
        while True:
            current_weight = hx.read_weight(times=7)

            # Check if weight changed beyond threshold
            weight_change = current_weight - last_stable_weight

            if abs(weight_change) > args.threshold:
                # Wait for the weight to settle
                time.sleep(args.settle_time)

                # Take a more accurate reading after settling
                settled_weight = hx.read_weight(times=10)
                settled_change = settled_weight - last_stable_weight

                # Verify the change is still significant after settling
                if abs(settled_change) > args.threshold:
                    event_count += 1
                    timestamp = time.strftime("%H:%M:%S")

                    if settled_change > 0:
                        print(f"  [{timestamp}] 📦 ITEM PLACED   | "
                              f"Change: +{settled_change:7.1f} g | "
                              f"Total: {settled_weight:8.1f} g")
                    else:
                        print(f"  [{timestamp}] 📤 ITEM REMOVED  | "
                              f"Change: {settled_change:7.1f} g | "
                              f"Total: {settled_weight:8.1f} g")

                    last_stable_weight = settled_weight

            time.sleep(0.2)

    except KeyboardInterrupt:
        print(f"\n\n✅ Stopped. Total events detected: {event_count}")
        print(f"   Final platform weight: {last_stable_weight:.1f} g")
    finally:
        hx.cleanup()


if __name__ == "__main__":
    main()
