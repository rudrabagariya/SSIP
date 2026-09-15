#!/usr/bin/env python3
"""
HX711 Continuous Weight Reader with Robust Tare and Live Calibration Tuning.

Features:
  - 25-sample outlier-trimmed robust tare at startup and on-demand
  - Dual-stage filtering: Olav Kallhovd outlier rejection + Denys Sene 1D Kalman filter
  - Live keyboard tuning:
      [t] Re-tare to 0.0g (25-sample trimmed mean)
      [c] Live calibrate with known weight on the scale
      [+] Nudge scale factor +1%      [-] Nudge scale factor -1%
      [>] Fine-tune scale factor +0.1% [<] Fine-tune scale factor -0.1%
      [s] Save calibration to calibration.json
      [q] Quit
"""

import argparse
import json
import os
import select
import sys
import termios
import time
import tty
from collections import deque

from hx711 import HX711


class KeyListener:
    """Non-blocking keyboard reader for interactive terminal sessions."""
    def __init__(self):
        self.is_tty = sys.stdin.isatty()
        self.old_settings = None
        if self.is_tty:
            try:
                self.old_settings = termios.tcgetattr(sys.stdin)
                tty.setcbreak(sys.stdin.fileno())
            except Exception:
                self.is_tty = False

    def get_key(self):
        if not self.is_tty:
            return None
        rlist, _, _ = select.select([sys.stdin], [], [], 0)
        if rlist:
            try:
                return sys.stdin.read(1)
            except Exception:
                return None
        return None

    def restore(self):
        if self.is_tty and self.old_settings:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass


class SimpleKalmanFilter:
    """
    1D Kalman Filter for single-variable ADC smoothing.
    Based on Denys Sene's SimpleKalmanFilter.
    """
    def __init__(self, mea_e=3.0, est_e=3.0, q=0.05):
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
    Based on Olav Kallhovd's HX711_ADC (smoothedData algorithm).
    Discards the highest and lowest spikes, averages the rest.
    """
    def __init__(self, size=8):
        self.buffer = deque(maxlen=size)

    def add(self, val):
        self.buffer.append(val)

    def clear(self):
        self.buffer.clear()

    def get_smoothed(self):
        if not self.buffer:
            return 0.0
        if len(self.buffer) < 3:
            return sum(self.buffer) / len(self.buffer)
        
        total = sum(self.buffer)
        low = min(self.buffer)
        high = max(self.buffer)
        return (total - low - high) / (len(self.buffer) - 2)


def robust_tare(hx, samples=25):
    """
    Perform a high-accuracy tare by taking multiple samples,
    trimming the top & bottom 25% outliers, and averaging the rest.
    """
    # 1. Warm-up reads to flush any stale ADC buffers
    for _ in range(3):
        hx.read_long()
        time.sleep(0.02)

    # 2. Collect samples
    collected = []
    for _ in range(samples):
        collected.append(hx.read_long())
        time.sleep(0.04)

    # 3. Sort and trim outer 25%
    collected.sort()
    trim = max(1, int(len(collected) * 0.25))
    clean_samples = collected[trim:-trim]

    # 4. Average clean samples
    new_offset = sum(clean_samples) / len(clean_samples)
    spread = max(clean_samples) - min(clean_samples)
    
    hx.set_offset(new_offset)
    return new_offset, spread


def prompt_live_calibration(hx, key_listener, cal_file):
    """Temporarily restore normal terminal mode to prompt for known weight."""
    key_listener.restore()
    try:
        print("\n" + "=" * 55)
        print("  🎯 LIVE CALIBRATION MODE")
        print("=" * 55)
        print("  Place your known reference weight on the scale.")
        val_str = input("  Enter known weight in grams (or press Enter to cancel): ").strip()
        
        if not val_str:
            print("  ❌ Cancelled.")
            return

        known_weight = float(val_str)
        if known_weight <= 0:
            print("  ❌ Weight must be greater than 0.")
            return

        print(f"  Sampling 20 readings with {known_weight}g on platform...")
        samples = []
        for _ in range(20):
            samples.append(hx.get_value(times=1))
            time.sleep(0.05)
        
        samples.sort()
        trim = max(1, int(len(samples) * 0.2))
        clean = samples[trim:-trim]
        raw_diff = sum(clean) / len(clean)

        new_scale = raw_diff / known_weight
        if new_scale == 0:
            new_scale = 1.0

        hx.set_reference_unit(new_scale)
        print(f"  ✅ New Scale Factor: {new_scale:.2f}")
        
        save = input(f"  Save to '{cal_file}' right now? (y/n): ").strip().lower()
        if save == 'y':
            hx.save_calibration(cal_file)
            print(f"  💾 Calibration saved to '{cal_file}'.")
        print("=" * 55)
        print("  Resuming live monitoring...\n")
    except Exception as e:
        print(f"  ❌ Calibration error: {e}")
    finally:
        # Re-enable cbreak for live key listener
        if key_listener.is_tty:
            try:
                tty.setcbreak(sys.stdin.fileno())
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="HX711 Stable Weight Reader with Live Calibration")
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
    parser.add_argument("--tare-samples", type=int, default=25,
                        help="Samples to use for robust zero tare (default: 25)")
    parser.add_argument("--no-tare", action="store_true",
                        help="Skip automatic zero tare at startup")
    parser.add_argument("--raw", action="store_true",
                        help="Also display raw ADC values")
    parser.add_argument("--no-cal", action="store_true",
                        help="Run without calibration (raw mode only)")
    args = parser.parse_args()

    print("=" * 65)
    print("  HX711 Robust Reader & Live Calibration (50kg / 30-40g Tuning)")
    print("=" * 65)

    try:
        hx = HX711(dout_pin=args.dout, pd_sck_pin=args.sck, gain=args.gain)
    except Exception as e:
        print(f"❌ Failed to initialize HX711: {e}")
        sys.exit(1)

    # Load calibration if available
    if not args.no_cal:
        if os.path.exists(args.cal):
            hx.load_calibration(args.cal)
            print(f"  ✅ Calibration loaded: Scale Factor = {hx.REFERENCE_UNIT:.2f}")
        else:
            print(f"  ⚠️  Calibration file '{args.cal}' not found!")
            print("     You can press [c] anytime to calibrate live.\n")
            args.no_cal = True

    # 1. High-accuracy 25-sample tare at startup
    if not args.no_cal and not args.no_tare:
        print(f"  ⚖️  Auto-taring with {args.tare_samples} samples (leave platform empty)...")
        offset, spread = robust_tare(hx, samples=args.tare_samples)
        print(f"  ✅ Tared cleanly to 0.0g (Offset: {offset:.0f}, Noise Spread: {spread} counts)\n")

    print("  Keyboard Commands (Live):")
    print("    [t] Re-tare to 0.0g (25 samples)")
    print("    [c] Calibrate live with known weight on scale")
    print("    [+] Scale +1%      [-] Scale -1%")
    print("    [>] Scale +0.1%    [<] Scale -0.1%")
    print("    [s] Save calibration to file")
    print("    [q] Quit")
    print("-" * 65)
    print("  Monitoring scale...\n")

    # Filters
    outlier_filter = KallhovdRollingFilter(size=8)
    kalman_filter = SimpleKalmanFilter(mea_e=3.0, est_e=3.0, q=0.05)
    kalman_filter.set_initial(0.0)

    recent_estimates = deque(maxlen=6)
    last_reported_weight = None
    is_stable = False
    reading_count = 0

    key_listener = KeyListener()

    try:
        while True:
            # ── Check Keyboard Input ──
            key = key_listener.get_key()
            if key:
                if key in ('q', 'Q'):
                    print("\n  Quitting...")
                    break
                elif key in ('t', 'T'):
                    print("\n  ⚖️  Re-taring (25 samples)... please keep platform empty...")
                    offset, spread = robust_tare(hx, samples=args.tare_samples)
                    outlier_filter.clear()
                    kalman_filter.set_initial(0.0)
                    recent_estimates.clear()
                    last_reported_weight = None
                    is_stable = False
                    print(f"  ✅ Zero confirmed: 0.0g (Offset: {offset:.0f})\n")
                elif key in ('+', '='):
                    cur = hx.REFERENCE_UNIT or 1.0
                    hx.set_reference_unit(cur * 1.01)
                    print(f"\n  🔧 Scale Factor adjusted: {cur:.2f} ➔ {hx.REFERENCE_UNIT:.2f} (+1.0%)")
                elif key in ('-', '_'):
                    cur = hx.REFERENCE_UNIT or 1.0
                    hx.set_reference_unit(cur * 0.99)
                    print(f"\n  🔧 Scale Factor adjusted: {cur:.2f} ➔ {hx.REFERENCE_UNIT:.2f} (-1.0%)")
                elif key in ('>', '.'):
                    cur = hx.REFERENCE_UNIT or 1.0
                    hx.set_reference_unit(cur * 1.001)
                    print(f"\n  🔧 Scale Factor adjusted: {cur:.2f} ➔ {hx.REFERENCE_UNIT:.2f} (+0.1%)")
                elif key in ('<', ','):
                    cur = hx.REFERENCE_UNIT or 1.0
                    hx.set_reference_unit(cur * 0.999)
                    print(f"\n  🔧 Scale Factor adjusted: {cur:.2f} ➔ {hx.REFERENCE_UNIT:.2f} (-0.1%)")
                elif key in ('c', 'C'):
                    prompt_live_calibration(hx, key_listener, args.cal)
                    outlier_filter.clear()
                    recent_estimates.clear()
                    last_reported_weight = None
                elif key in ('s', 'S'):
                    hx.save_calibration(args.cal)
                    print(f"\n  💾 Saved to '{args.cal}' (Scale: {hx.REFERENCE_UNIT:.2f}, Offset: {hx.OFFSET:.0f})")

            reading_count += 1

            if args.no_cal:
                raw_sample = hx.read_long()
                print(f"  #{reading_count:4d} | Raw: {raw_sample}")
                time.sleep(0.1)
                continue

            # 1. Single sample read
            raw_val = hx.get_value(times=1)
            raw_weight = raw_val / hx.REFERENCE_UNIT if hx.REFERENCE_UNIT else 0.0

            # 2. Kallhovd Outlier Rejection
            outlier_filter.add(raw_weight)
            despiked = outlier_filter.get_smoothed()

            # 3. Kalman Filter
            filtered = kalman_filter.update(despiked)

            # Snap deadband around zero (both positive and negative)
            if abs(filtered) < args.deadband:
                filtered = 0.0

            # 4. Stability Detection
            recent_estimates.append(filtered)

            if len(recent_estimates) == recent_estimates.maxlen:
                spread = max(recent_estimates) - min(recent_estimates)

                if spread <= args.stability_variance:
                    current_stable = round(sum(recent_estimates) / len(recent_estimates), 1)

                    if abs(current_stable) < args.deadband:
                        current_stable = 0.0

                    if last_reported_weight is None or abs(current_stable - last_reported_weight) >= 1.0:
                        last_reported_weight = current_stable
                        is_stable = True

                        if current_stable == 0.0:
                            print(f"🟢 [STABLE] Platform empty  -->   0.0 g  (Scale: {hx.REFERENCE_UNIT:.2f})")
                        elif current_stable < 0:
                            print(f"🟡 [STABLE] Negative: {current_stable:5.1f} g  (Press [t] to re-tare)")
                        else:
                            print(f"🟢 [STABLE] Weight:   {current_stable:5.1f} g  (Scale: {hx.REFERENCE_UNIT:.2f})")
                else:
                    if is_stable:
                        print(f"⏳ Settling... (live: {filtered:5.1f} g)", end="\r")
                        is_stable = False

            time.sleep(0.08)

    except KeyboardInterrupt:
        print("\n\n✅ Stopped.")
    finally:
        key_listener.restore()
        hx.cleanup()


if __name__ == "__main__":
    main()
