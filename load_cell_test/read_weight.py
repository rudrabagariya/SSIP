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
        smoothed_weight = None
        stable_weight = 0
        stable_count = 0
        STABLE_THRESHOLD = 2.0  # grams — readings within this range are "stable"
        STEP_THRESHOLD = 20.0   # grams — sudden delta resets smoothing instantly
        
        # Sliding window for outlier rejection
        window_buffer = deque(maxlen=args.window)

        while True:
            reading_num += 1

            # Read 1 fast sample from HX711
            weight_instant = hx.read_weight(times=1) if not args.no_cal else 0
            raw = hx.read_raw(times=1) if (args.no_cal or args.raw) else 0
            
            # 1. Outlier Rejection (Sliding Median)
            window_buffer.append(weight_instant)
            median_weight = statistics.median(window_buffer)

            # 2. Adaptive Exponential Moving Average (EMA)
            if smoothed_weight is None:
                smoothed_weight = median_weight
            else:
                # If user placed or removed an item suddenly, snap immediately
                if abs(median_weight - smoothed_weight) > STEP_THRESHOLD:
                    smoothed_weight = median_weight
                else:
                    smoothed_weight = (args.smooth * median_weight) + ((1.0 - args.smooth) * smoothed_weight)

            # 3. Auto-zero deadband near 0
            if abs(smoothed_weight) < args.deadband:
                display_weight = 0.0
            else:
                display_weight = smoothed_weight

            # Stability detection
            if abs(display_weight - stable_weight) < STABLE_THRESHOLD:
                stable_count += 1
            else:
                stable_weight = display_weight
                stable_count = 0

            stability = "📌 STABLE" if stable_count >= 3 else "⏳ settling..."

            if args.no_cal or args.raw:
                print(f"  #{reading_num:4d}  |  Raw: {raw:10d}  |  Instant: {weight_instant:7.1f}g  |  Smooth: {display_weight:7.1f}g  |  {stability}")
            else:
                if display_weight >= 1000:
                    print(f"  #{reading_num:4d}  |  {display_weight/1000:6.3f} kg  ({display_weight:7.1f} g)  |  {stability}")
                else:
                    print(f"  #{reading_num:4d}  |  {display_weight:7.1f} g  |  {stability}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\n✅ Stopped. Final reading: {:.1f} g".format(weight if not args.no_cal else 0))
    finally:
        hx.cleanup()


if __name__ == "__main__":
    main()
