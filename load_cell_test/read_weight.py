#!/usr/bin/env python3
"""
HX711 Continuous Weight Reader with High-Precision Tare and Multi-Sample Verification.

Features:
  - 500-sample outlier-trimmed robust tare with animated progress bar
  - Multi-sample calibration with statistical verification report (Error, StdDev, Pass/Fail)
  - Dual-stage filtering: Olav Kallhovd outlier rejection + Denys Sene 1D Kalman filter
  - Live keyboard tuning:
      [t] Re-tare to 0.0g (500 samples with progress bar)
      [c] Multi-sample calibration with statistical confirmation
      [+] Nudge scale factor +1%      [-] Nudge scale factor -1%
      [>] Fine-tune scale factor +0.1% [<] Fine-tune scale factor -0.1%
      [s] Save calibration to calibration.json
      [q] Quit
"""

import argparse
import json
import math
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
        self._err_estimate = self._err_measure

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


def robust_tare(hx, samples=500, show_progress=True):
    """
    High-precision tare taking `samples` readings, trimming top & bottom 20%
    outliers, and computing clean zero baseline with an animated progress bar.
    Prints a full diagnostic report of the sample distribution.
    """
    # 1. Thermal & excitation warm-up reads to flush bridge drift
    sys.stdout.write("  🔌 Stabilizing bridge excitation & thermal drift...")
    sys.stdout.flush()
    warmup_start = time.time()
    while time.time() - warmup_start < 2.5:
        hx.read_long()
        time.sleep(0.05)
    sys.stdout.write(" ready.\n")
    sys.stdout.flush()

    collected = []
    start_time = time.time()
    
    for i in range(1, samples + 1):
        val = hx.read_long()
        collected.append(val)
        
        if show_progress and (i % 5 == 0 or i == samples):
            pct = int(i / samples * 100)
            bar_len = 25
            filled = int(bar_len * i // samples)
            bar = '█' * filled + '░' * (bar_len - filled)
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 10
            remaining = (samples - i) / rate if rate > 0 else 0
            sys.stdout.write(f"\r  [{bar}] {pct:3d}% ({i}/{samples}) | ADC: {val:8d} | {remaining:4.1f}s left ")
            sys.stdout.flush()

    if show_progress:
        sys.stdout.write("\n")
        sys.stdout.flush()

    elapsed_total = time.time() - start_time

    # Sort and trim top & bottom 20%
    collected.sort()
    trim = max(1, int(len(collected) * 0.20))
    discarded_low = collected[:trim]
    discarded_high = collected[-trim:]
    clean_samples = collected[trim:-trim]

    new_offset = sum(clean_samples) / len(clean_samples)
    
    mean = new_offset
    variance = sum((x - mean) ** 2 for x in clean_samples) / len(clean_samples)
    std_dev = math.sqrt(variance)

    # Diagnostic report
    print(f"  ┌─────────────── TARE DIAGNOSTIC ───────────────┐")
    print(f"  │ Total samples collected : {samples:6d}               │")
    print(f"  │ Time taken              : {elapsed_total:6.1f}s              │")
    print(f"  │ Discarded (bottom 20%)  : {len(discarded_low):6d} samples        │")
    print(f"  │   Range: {min(discarded_low):10.0f} to {max(discarded_low):10.0f}       │")
    print(f"  │ Discarded (top 20%)     : {len(discarded_high):6d} samples        │")
    print(f"  │   Range: {min(discarded_high):10.0f} to {max(discarded_high):10.0f}       │")
    print(f"  │ KEPT (clean middle 60%) : {len(clean_samples):6d} samples        │")
    print(f"  │   Min:   {min(clean_samples):10.0f}                    │")
    print(f"  │   Max:   {max(clean_samples):10.0f}                    │")
    print(f"  │   Spread:{max(clean_samples) - min(clean_samples):10.0f} counts             │")
    print(f"  │   StdDev:    ±{std_dev:8.1f} counts             │")
    print(f"  │ ─────────────────────────────────────────────  │")
    print(f"  │ ✅ OFFSET SET TO: {new_offset:10.0f}                  │")
    print(f"  └────────────────────────────────────────────────┘")

    hx.set_offset(new_offset)
    return new_offset, std_dev


def sync_filters_to_current(hx, outlier_filter, kalman_filter, recent_estimates, samples=5):
    """
    Immediately synchronize all filter states (Kalman, Kallhovd rolling, stability buffer)
    to the sensor's CURRENT physical reading.
    Eliminates filter lag, creeping values, and stale state transitions.
    """
    outlier_filter.clear()
    recent_estimates.clear()

    sys.stdout.write("  🔄 Syncing filters to current weight...")
    sys.stdout.flush()

    # Take a few fast readings to sample current steady weight
    readings = []
    for _ in range(samples):
        val = hx.get_value(times=1)
        w = val / hx.REFERENCE_UNIT if hx.REFERENCE_UNIT else 0.0
        readings.append(w)
        time.sleep(0.02)

    readings.sort()
    current_weight = readings[len(readings) // 2] if readings else 0.0

    # Initialize Kalman filter directly to current weight
    kalman_filter.set_initial(current_weight)

    # Pre-fill rolling filter buffer with this median weight
    for _ in range(outlier_filter.buffer.maxlen):
        outlier_filter.add(current_weight)
    
    # Pre-fill stability queue so user gets an immediate accurate reading
    for _ in range(recent_estimates.maxlen):
        recent_estimates.append(current_weight)

    print(f" done! (Current reading: {current_weight:+.1f} g)")


def prompt_live_calibration(hx, key_listener, cal_file, samples=100, verify_samples=30):
    """
    Multi-sample calibration with statistical verification and confirmation test.
    """
    key_listener.restore()
    old_scale = hx.REFERENCE_UNIT

    try:
        print("\n" + "=" * 62)
        print("  🎯 MULTI-SAMPLE CALIBRATION & VERIFICATION")
        print("=" * 62)
        print("  Note: Platform should have been tared (empty) beforehand.")
        val_str = input("  Enter known weight in grams (e.g. 500, 1160) [or Enter to cancel]: ").strip()
        
        if not val_str:
            print("  ❌ Cancelled.")
            return False

        try:
            known_weight = float(val_str)
        except ValueError:
            print(f"  ❌ Invalid number: '{val_str}'")
            return False

        if known_weight <= 0:
            print("  ❌ Weight must be greater than 0.")
            return False

        input(f"\n  👉 Place the {known_weight}g object on the platform.\n"
              f"     Press Enter when it is placed and completely still...")
        print()

        # ── Phase 1: Reference Acquisition ──
        print(f"  [Phase 1/2] Sampling {samples} readings with {known_weight}g on scale...")
        raw_diffs = []
        for i in range(1, samples + 1):
            diff = hx.get_value(times=1)
            raw_diffs.append(diff)
            if i % 5 == 0 or i == samples:
                pct = int(i / samples * 100)
                bar = '█' * (25 * i // samples) + '░' * (25 - (25 * i // samples))
                sys.stdout.write(f"\r  [{bar}] {pct:3d}% ({i}/{samples}) | Diff: {diff:7.0f} ")
                sys.stdout.flush()
        sys.stdout.write("\n")

        raw_diffs.sort()
        trim = max(1, int(len(raw_diffs) * 0.20))
        clean = raw_diffs[trim:-trim]
        avg_diff = sum(clean) / len(clean)

        if abs(avg_diff) < 50:
            print(f"  ❌ Error: No significant weight change detected (diff={avg_diff:.0f}).")
            print("     Make sure the platform was empty during tare and weight is placed properly.")
            return False

        tentative_scale = avg_diff / known_weight
        hx.set_reference_unit(tentative_scale)

        # ── Phase 2: Live Verification Confirmation Test ──
        print(f"\n  [Phase 2/2] Running Confirmation Test ({verify_samples} verification samples)...")
        test_weights = []
        for i in range(1, verify_samples + 1):
            v = hx.get_weight(times=1)
            test_weights.append(v)
            if i % 3 == 0 or i == verify_samples:
                pct = int(i / verify_samples * 100)
                bar = '█' * (25 * i // verify_samples) + '░' * (25 - (25 * i // verify_samples))
                sys.stdout.write(f"\r  [{bar}] {pct:3d}% ({i}/{verify_samples}) | Measured: {v:5.1f}g ")
                sys.stdout.flush()
        sys.stdout.write("\n")

        test_weights.sort()
        trim_v = max(1, int(len(test_weights) * 0.15))
        clean_test = test_weights[trim_v:-trim_v]
        
        measured_mean = sum(clean_test) / len(clean_test)
        error_g = measured_mean - known_weight
        error_pct = (error_g / known_weight) * 100.0
        
        v_variance = sum((x - measured_mean) ** 2 for x in clean_test) / len(clean_test)
        v_std = math.sqrt(v_variance)
        min_w = min(clean_test)
        max_w = max(clean_test)

        if abs(error_pct) < 1.0:
            status = "EXCELLENT (PASS) ✅"
        elif abs(error_pct) < 3.0:
            status = "ACCEPTABLE ⚠️"
        else:
            status = "POOR (FAIL) ❌"

        print("-" * 62)
        print("  📊 CALIBRATION CONFIRMATION REPORT:")
        print(f"     Expected Weight : {known_weight:7.2f} g")
        print(f"     Tested Average  : {measured_mean:7.2f} g")
        print(f"     Accuracy Error  : {error_g:+7.2f} g  ({error_pct:+.2f}%)")
        print(f"     Noise (StdDev)  : ±{v_std:5.2f} g")
        print(f"     Tested Range    : {min_w:.1f} g  to  {max_w:.1f} g")
        print(f"     Old Scale Factor: {old_scale:.2f}")
        print(f"     New Scale Factor: {tentative_scale:.2f}")
        print(f"     Quality Grade   : {status}")
        print("-" * 62)

        confirm = input(f"  Accept and save this calibration to '{cal_file}'? [Y/n]: ").strip().lower()
        if confirm in ('y', 'yes', ''):
            hx.save_calibration(cal_file)
            print(f"  ✅ Saved to '{cal_file}' and applied! Scale Factor = {tentative_scale:.2f}")
            print("=" * 62)
            print("  Resuming live monitoring...\n")
            return True
        else:
            hx.set_reference_unit(old_scale)
            print(f"  ↩️  Reverted back to previous scale factor ({old_scale:.2f}).")
            print("=" * 62)
            print("  Resuming live monitoring...\n")
            return False
    except Exception as e:
        hx.set_reference_unit(old_scale)
        print(f"  ❌ Calibration error: {e}")
        return False
    finally:
        if key_listener.is_tty:
            try:
                tty.setcbreak(sys.stdin.fileno())
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="HX711 Stable Weight Reader with High-Precision Tare")
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
    parser.add_argument("--tare-samples", type=int, default=200,
                        help="Samples to use for high-precision tare (default: 200)")
    parser.add_argument("--no-tare", action="store_true",
                        help="Skip automatic zero tare at startup")
    parser.add_argument("--raw", action="store_true",
                        help="Also display raw ADC values")
    parser.add_argument("--no-cal", action="store_true",
                        help="Run without calibration (raw mode only)")
    args = parser.parse_args()

    print("=" * 65)
    print("  HX711 High-Precision Weight Reader & Multi-Sample Calibrator")
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
            print("     Running with uncalibrated scale (press [c] to calibrate live).\n")
            # We do NOT set args.no_cal = True here, so the user can tare and then calibrate

    # Filters (create BEFORE tare so warmup can use them)
    outlier_filter = KallhovdRollingFilter(size=8)
    kalman_filter = SimpleKalmanFilter(mea_e=3.0, est_e=3.0, q=0.05)
    kalman_filter.set_initial(0.0)
    recent_estimates = deque(maxlen=6)
    last_reported_weight = None
    is_stable = False
    reading_count = 0

    # 1. High-accuracy 500-sample tare at startup
    if not args.no_cal and not args.no_tare:
        print(f"  ⚖️  Performing high-precision zero tare ({args.tare_samples} samples)...")
        print("     Please leave platform completely empty and do not touch wires.")
        offset, std = robust_tare(hx, samples=args.tare_samples)
        # Sync filters so first reported value is clean 0.0g
        sync_filters_to_current(hx, outlier_filter, kalman_filter, recent_estimates)
        print()

    print("  Keyboard Commands (Live):")
    print(f"    [t] Re-tare to 0.0g ({args.tare_samples} samples with progress bar)")
    print("    [c] Multi-sample calibration with confirmation test")
    print("    [+] Scale +1%      [-] Scale -1%")
    print("    [>] Scale +0.1%    [<] Scale -0.1%")
    print("    [s] Save calibration to file")
    print("    [q] Quit")
    print("-" * 65)
    print("  Monitoring scale...\n")

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
                    print(f"\n  ⚖️  Re-taring ({args.tare_samples} samples)... please keep platform empty...")
                    offset, std = robust_tare(hx, samples=args.tare_samples)
                    sync_filters_to_current(hx, outlier_filter, kalman_filter, recent_estimates)
                    last_reported_weight = None
                    is_stable = False
                    print()
                elif key in ('+', '='):
                    cur = hx.REFERENCE_UNIT or 1.0
                    hx.set_reference_unit(cur * 1.01)
                    print(f"\n  🔧 Scale Factor: {cur:.2f} ➔ {hx.REFERENCE_UNIT:.2f} (+1.0%)")
                    sync_filters_to_current(hx, outlier_filter, kalman_filter, recent_estimates)
                    last_reported_weight = None
                    is_stable = False
                elif key in ('-', '_'):
                    cur = hx.REFERENCE_UNIT or 1.0
                    hx.set_reference_unit(cur * 0.99)
                    print(f"\n  🔧 Scale Factor: {cur:.2f} ➔ {hx.REFERENCE_UNIT:.2f} (-1.0%)")
                    sync_filters_to_current(hx, outlier_filter, kalman_filter, recent_estimates)
                    last_reported_weight = None
                    is_stable = False
                elif key in ('>', '.'):
                    cur = hx.REFERENCE_UNIT or 1.0
                    hx.set_reference_unit(cur * 1.001)
                    print(f"\n  🔧 Scale Factor: {cur:.2f} ➔ {hx.REFERENCE_UNIT:.2f} (+0.1%)")
                    sync_filters_to_current(hx, outlier_filter, kalman_filter, recent_estimates)
                    last_reported_weight = None
                    is_stable = False
                elif key in ('<', ','):
                    cur = hx.REFERENCE_UNIT or 1.0
                    hx.set_reference_unit(cur * 0.999)
                    print(f"\n  🔧 Scale Factor: {cur:.2f} ➔ {hx.REFERENCE_UNIT:.2f} (-0.1%)")
                    sync_filters_to_current(hx, outlier_filter, kalman_filter, recent_estimates)
                    last_reported_weight = None
                    is_stable = False
                elif key in ('c', 'C'):
                    if prompt_live_calibration(hx, key_listener, args.cal):
                        args.no_cal = False
                    sync_filters_to_current(hx, outlier_filter, kalman_filter, recent_estimates)
                    last_reported_weight = None
                    is_stable = False
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
