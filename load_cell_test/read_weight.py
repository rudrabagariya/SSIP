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
from collections import deque

from hx711 import HX711


class SimpleKalmanFilter:
    """
    1D Kalman Filter implementation for single variable models.
    Based on Denys Sene's SimpleKalmanFilter (used in Arduino/ESP/Pi digital scales).
    """
    def __init__(self, mea_e=3.0, est_e=3.0, q=0.05):
        """
        mea_e: Measurement Uncertainty (noise standard deviation, e.g. ±3g)
        est_e: Estimation Uncertainty (how much to trust initial state)
        q: Process Noise (how fast true weight can change, smaller = smoother)
        """
        self._err_measure = mea_e
        self._err_estimate = est_e
        self._q = q
        self._current_estimate = 0.0
        self._last_estimate = 0.0
        self._kalman_gain = 0.0

    def set_initial(self, val):
        self._current_estimate = val
        self._last_estimate = val

    def update(self, mea):
        self._kalman_gain = self._err_estimate / (self._err_estimate + self._err_measure)
        self._current_estimate = self._last_estimate + self._kalman_gain * (mea - self._last_estimate)
        self._err_estimate = (1.0 - self._kalman_gain) * self._err_estimate + abs(self._last_estimate - self._current_estimate) * self._q
        self._last_estimate = self._current_estimate
        return self._current_estimate


class KallhovdRollingFilter:
    """
    Rolling dataset with Outlier Rejection.
    Based on Olav Kallhovd's HX711_ADC library (smoothedData algorithm).
    Discards the highest and lowest spikes, averages the rest.
    """
    def __init__(self, size=8):
        self.buffer = deque(maxlen=size)

    def add(self, val):
        self.buffer.append(val)

    def get_smoothed(self):
        if not self.buffer:
            return 0.0
        if len(self.buffer) < 3:
            return sum(self.buffer) / len(self.buffer)
        
        # Kallhovd algorithm: sum all, subtract min, subtract max, divide by (N - 2)
        total = sum(self.buffer)
        low = min(self.buffer)
        high = max(self.buffer)
        return (total - low - high) / (len(self.buffer) - 2)


def main():
    parser = argparse.ArgumentParser(description="HX711 Stable Weight Reader for Small Products")
    parser.add_argument("--dout", type=int, default=5,
                        help="GPIO pin for HX711 DOUT (default: 5)")
    parser.add_argument("--sck", type=int, default=6,
                        help="GPIO pin for HX711 PD_SCK (default: 6)")
    parser.add_argument("--gain", type=int, default=128, choices=[128, 64, 32],
                        help="Amplifier gain (default: 128)")
    parser.add_argument("--cal", type=str, default="calibration.json",
                        help="Calibration file path (default: calibration.json)")
    parser.add_argument("--deadband", type=float, default=2.0,
                        help="Grams near zero to snap to 0.0g (default: 2.0g)")
    parser.add_argument("--stability-variance", type=float, default=1.5,
                        help="Max gram difference in 1 sec to declare STABLE (default: 1.5g)")
    parser.add_argument("--no-tare", action="store_true",
                        help="Skip automatic zero tare at startup")
    parser.add_argument("--tare-samples", type=int, default=15,
                        help="Number of samples to average for tare (default: 15)")
    parser.add_argument("--raw", action="store_true",
                        help="Also display raw ADC values")
    parser.add_argument("--no-cal", action="store_true",
                        help="Run without calibration (raw mode only)")
    args = parser.parse_args()

    print("=" * 60)
    print("  HX711 Dual-Stage Filter (Kallhovd Trimmed Mean + Kalman)")
    print("  Tuned for: 50kg scale measuring 30-40g items")
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
            print(f"✅ Calibration loaded from '{args.cal}'")
        else:
            print(f"⚠️  Calibration file '{args.cal}' not found!")
            print("   Run 'sudo python3 calibrate.py' first.")
            print("   Continuing with uncalibrated raw values...\n")
            args.no_cal = True

    # Automatic zero tare at startup
    if not args.no_cal and not args.no_tare:
        print("⚖️  Auto-taring scale (please leave platform empty)...")
        hx.tare(times=args.tare_samples)
        print("✅ Zero tare complete — scale is at 0.0g!\n")

    print(f"  Stability window: ±{args.stability_variance}g | Zero deadband: ±{args.deadband}g")
    print("  Press Ctrl+C to stop")
    print("-" * 60)
    print("  Reading weight...\n")

    # Initialize Filters
    outlier_filter = KallhovdRollingFilter(size=8)
    kalman_filter = SimpleKalmanFilter(mea_e=3.0, est_e=3.0, q=0.05)
    
    recent_estimates = deque(maxlen=6)
    last_reported_weight = None
    is_stable = False
    reading_count = 0

    try:
        # Pre-seed filters with initial zeroed state
        kalman_filter.set_initial(0.0)

        while True:
            reading_count += 1
            
            # 1. Acquire single fast reading from HX711
            if args.no_cal:
                raw_sample = hx.read_long()
                print(f"  #{reading_count:4d} | Raw: {raw_sample}")
                time.sleep(0.1)
                continue

            raw_val = hx.get_value(times=1)
            raw_weight = raw_val / hx.REFERENCE_UNIT if hx.REFERENCE_UNIT else 0.0

            # 2. Stage 1: Kallhovd Outlier Rejection (removes transient spikes)
            outlier_filter.add(raw_weight)
            despiked_weight = outlier_filter.get_smoothed()

            # 3. Stage 2: 1D Kalman Filter (locks still values, fast response on load)
            filtered_weight = kalman_filter.update(despiked_weight)

            # Snap deadband around 0
            if abs(filtered_weight) < args.deadband:
                filtered_weight = 0.0

            # 4. Stability Detection Window
            recent_estimates.append(filtered_weight)
            
            if len(recent_estimates) == recent_estimates.maxlen:
                spread = max(recent_estimates) - min(recent_estimates)
                
                # Check if readings have settled within stability threshold
                if spread <= args.stability_variance:
                    current_stable = round(sum(recent_estimates) / len(recent_estimates), 1)
                    
                    # Snap deadband
                    if abs(current_stable) < args.deadband:
                        current_stable = 0.0
                    
                    # If this is a new stable weight or state change
                    if last_reported_weight is None or abs(current_stable - last_reported_weight) >= 1.0:
                        last_reported_weight = current_stable
                        is_stable = True
                        
                        if current_stable == 0.0:
                            print(f"🟢 [STABLE] Platform empty  -->  0.0 g")
                        else:
                            print(f"🟢 [STABLE] Weight: {current_stable:5.1f} g  (variance: {spread:.2f}g)")
                else:
                    # Weight is moving / being placed
                    if is_stable:
                        print(f"⏳ Settling... (live: {filtered_weight:5.1f} g)", end="\r")
                        is_stable = False

            # Brief pause to align with HX711 update cycle (~10Hz)
            time.sleep(0.08)

    except KeyboardInterrupt:
        print("\n\n✅ Stopped.")
    finally:
        hx.cleanup()


if __name__ == "__main__":
    main()
