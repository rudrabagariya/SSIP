#!/usr/bin/env python3
"""
Continuous Weight Reader — reads calibrated weight in real-time.

Prerequisites:
    Run calibrate.py first to create calibration.json

Usage:
    sudo python3 read_weight.py
    sudo python3 read_weight.py --interval 0.5
    sudo python3 read_weight.py --raw        # Show raw ADC values too

Press Ctrl+C to stop.
"""

import argparse
import os
import sys
import time

from hx711 import HX711


import statistics
from collections import deque

def main():
    parser = argparse.ArgumentParser(description="HX711 Continuous Weight Reader")
    parser.add_argument("--dout", type=int, default=5,
                        help="GPIO pin for HX711 DOUT (default: 5)")
    parser.add_argument("--sck", type=int, default=6,
                        help="GPIO pin for HX711 PD_SCK (default: 6)")
    parser.add_argument("--gain", type=int, default=128, choices=[128, 64, 32],
                        help="Amplifier gain (default: 128)")
    parser.add_argument("--cal", type=str, default="calibration.json",
                        help="Calibration file path (default: calibration.json)")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="Seconds between console updates (default: 0.5)")
    parser.add_argument("--window", type=int, default=5,
                        help="Sliding window size for outlier rejection (default: 5)")
    parser.add_argument("--smooth", type=float, default=0.3,
                        help="EMA smoothing factor 0.05-1.0 (default: 0.3, lower = smoother)")
    parser.add_argument("--deadband", type=float, default=3.0,
                        help="Grams near zero to suppress to 0.0g (default: 3.0)")
    parser.add_argument("--raw", action="store_true",
                        help="Also display raw ADC values")
    parser.add_argument("--no-cal", action="store_true",
                        help="Run without calibration (raw mode only)")
    args = parser.parse_args()

    print("=" * 60)
    print("  HX711 Advanced Weight Reader (Median + EMA Filter)")
    print("=" * 60)

    try:
        hx = HX711(dout_pin=args.dout, pd_sck_pin=args.sck, gain=args.gain)
    except Exception as e:
        print(f"❌ Failed to initialize HX711: {e}")
        sys.exit(1)

    # Load calibration if available
    if not args.no_cal:
        if os.path.exists(args.cal):
            hx.load_calibration(args.cal)
        else:
            print(f"⚠️  Calibration file '{args.cal}' not found!")
            print("   Run 'sudo python3 calibrate.py' first.")
            print("   Continuing with uncalibrated raw values...\n")
            args.no_cal = True

    print()
    print(f"  Filter: Window={args.window}, Smooth={args.smooth} | Deadband: ±{args.deadband}g | Interval: {args.interval}s")
    print("  Press Ctrl+C to stop")
    print("-" * 60)
    print()

    try:
        reading_num = 0
        history = []
        last_printed_weight = -9999.0
        STABLE_THRESHOLD = 5.0  # Allow 5g of variance to be considered "stable"
        
        print("  Waiting for stable weight...")

        while True:
            reading_num += 1

            # Let the HX711 library handle the basic sampling
            weight = hx.read_weight(times=args.samples) if not args.no_cal else 0
            raw = hx.read_raw(times=args.samples) if (args.no_cal or args.raw) else 0
            
            if args.no_cal or args.raw:
                # If raw mode, just print everything so they can debug
                print(f"  #{reading_num:4d} | Raw: {raw:10d} | Weight: {weight:7.1f}g")
                time.sleep(0.5)
                continue

            # Add to history buffer for stability checking
            history.append(weight)
            if len(history) > 3:
                history.pop(0)

            # Check if we have enough readings and they are stable
            if len(history) == 3:
                variance = max(history) - min(history)
                
                if variance <= STABLE_THRESHOLD:
                    stable_weight = sum(history) / len(history)
                    
                    # Clean up near-zero noise
                    if abs(stable_weight) < args.deadband:
                        stable_weight = 0.0

                    # Only print if it's a NEW stable weight (don't spam the console)
                    if abs(stable_weight - last_printed_weight) > STABLE_THRESHOLD:
                        if stable_weight >= 1000:
                            print(f"\n✅ STABLE: {stable_weight/1000:6.3f} kg  ({stable_weight:7.1f} g)")
                        else:
                            print(f"\n✅ STABLE: {stable_weight:7.1f} g")
                        
                        last_printed_weight = stable_weight

    except KeyboardInterrupt:
        print("\n\n✅ Stopped.")
    finally:
        hx.cleanup()


if __name__ == "__main__":
    main()
