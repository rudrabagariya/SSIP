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
    parser.add_argument("--interval", type=float, default=0.3,
                        help="Seconds between readings (default: 0.3)")
    parser.add_argument("--samples", type=int, default=5,
                        help="Samples per reading for median filter (default: 5)")
    parser.add_argument("--raw", action="store_true",
                        help="Also display raw ADC values")
    parser.add_argument("--no-cal", action="store_true",
                        help="Run without calibration (raw mode only)")
    args = parser.parse_args()

    print("=" * 60)
    print("  HX711 Continuous Weight Reader")
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
    print("  Press Ctrl+C to stop")
    print("-" * 60)
    print()

    try:
        reading_num = 0
        stable_weight = 0
        stable_count = 0
        STABLE_THRESHOLD = 2.0  # grams — readings within this range are "stable"

        while True:
            reading_num += 1

            raw = hx.read_raw(times=args.samples)
            weight = hx.read_weight(times=args.samples) if not args.no_cal else 0

            # Stability detection
            if abs(weight - stable_weight) < STABLE_THRESHOLD:
                stable_count += 1
            else:
                stable_weight = weight
                stable_count = 0

            stability = "📌 STABLE" if stable_count >= 3 else "⏳ settling..."

            if args.no_cal or args.raw:
                print(f"  #{reading_num:4d}  |  Raw: {raw:10d}  |  Weight: {weight:8.1f} g  |  {stability}")
            else:
                # Clean display
                if weight < 0 and abs(weight) < 5:
                    display_weight = 0.0  # Suppress noise near zero
                else:
                    display_weight = weight

                if display_weight >= 1000:
                    print(f"  #{reading_num:4d}  |  {display_weight/1000:6.3f} kg  |  {display_weight:8.1f} g  |  {stability}")
                else:
                    print(f"  #{reading_num:4d}  |  {display_weight:8.1f} g   |  {stability}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n\n✅ Stopped. Final reading: {:.1f} g".format(weight if not args.no_cal else 0))
    finally:
        hx.cleanup()


if __name__ == "__main__":
    main()
