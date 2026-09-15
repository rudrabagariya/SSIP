#!/usr/bin/env python3
"""
Raw Diagnostic Tool — tests HX711 wiring and basic communication.

Run this FIRST if you're unsure whether the HX711 is wired correctly.
It does NOT need calibration — it just reads raw ADC values and checks
that the sensor is alive and responding to weight changes.

Usage:
    sudo python3 test_raw.py
    sudo python3 test_raw.py --dout 5 --sck 6
"""

import argparse
import sys
import time

import RPi.GPIO as GPIO


def read_hx711_raw(dout_pin, sck_pin, gain_pulses=25):
    """Read one raw 24-bit value from HX711 — minimal implementation."""
    # Wait for DOUT to go LOW (data ready)
    timeout = time.time() + 5
    while GPIO.input(dout_pin) == 1:
        if time.time() > timeout:
            return None  # Sensor not responding
        time.sleep(0.001)

    # Read 24 bits
    raw = 0
    for _ in range(24):
        GPIO.output(sck_pin, GPIO.HIGH)
        time.sleep(0.000001)
        raw = (raw << 1) | GPIO.input(dout_pin)
        GPIO.output(sck_pin, GPIO.LOW)
        time.sleep(0.000001)

    # Extra pulses for gain setting
    for _ in range(gain_pulses - 24):
        GPIO.output(sck_pin, GPIO.HIGH)
        time.sleep(0.000001)
        GPIO.output(sck_pin, GPIO.LOW)
        time.sleep(0.000001)

    # Two's complement
    if raw & 0x800000:
        raw -= 0x1000000

    return raw


def main():
    parser = argparse.ArgumentParser(description="HX711 Raw Diagnostic Test")
    parser.add_argument("--dout", type=int, default=5,
                        help="GPIO pin for HX711 DOUT (default: 5)")
    parser.add_argument("--sck", type=int, default=6,
                        help="GPIO pin for HX711 PD_SCK (default: 6)")
    args = parser.parse_args()

    print("=" * 60)
    print("  HX711 Raw Diagnostic Test")
    print("=" * 60)
    print()
    print("  Wiring Check:")
    print(f"    HX711 DOUT → GPIO {args.dout}  (Pi Pin {_bcm_to_board(args.dout)})")
    print(f"    HX711 SCK  → GPIO {args.sck}  (Pi Pin {_bcm_to_board(args.sck)})")
    print(f"    HX711 VCC  → 3.3V (Pi Pin 1)")
    print(f"    HX711 GND  → GND  (Pi Pin 6)")
    print()

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(args.sck, GPIO.OUT)
    GPIO.setup(args.dout, GPIO.IN)
    GPIO.output(args.sck, GPIO.LOW)
    time.sleep(0.1)

    # ── Test 1: Check if DOUT pin is readable ──
    print("Test 1: Checking DOUT pin state...")
    dout_state = GPIO.input(args.dout)
    print(f"  DOUT = {'HIGH (waiting/not ready)' if dout_state else 'LOW (data ready)'}")

    if dout_state == 1:
        print("  → HX711 is HIGH (normal idle state). Attempting to read...")
    print()

    # ── Test 2: Read raw values ──
    print("Test 2: Reading 20 raw values (takes ~10 seconds)...")
    print("-" * 60)

    values = []
    errors = 0

    for i in range(20):
        raw = read_hx711_raw(args.dout, args.sck)
        if raw is None:
            print(f"  #{i+1:2d}: ❌ TIMEOUT — sensor not responding")
            errors += 1
        else:
            values.append(raw)
            print(f"  #{i+1:2d}: {raw:10d}")
        time.sleep(0.3)

    print("-" * 60)
    print()

    # ── Analysis ──
    if errors == 20:
        print("❌ RESULT: HX711 is NOT responding at all!")
        print()
        print("   Troubleshooting:")
        print("   1. Check VCC is connected to 3.3V (NOT 5V)")
        print("   2. Check GND is connected")
        print("   3. Double-check DOUT and SCK pin numbers")
        print("   4. Verify the HX711 board LED is lit")
        print("   5. Try swapping DOUT and SCK (common mistake)")
    elif errors > 0:
        print(f"⚠️  RESULT: {errors}/20 timeouts — intermittent connection")
        print("   Check for loose wires or poor solder joints")
    else:
        print("✅ RESULT: HX711 is communicating!")
        print()

        avg = sum(values) / len(values)
        min_val = min(values)
        max_val = max(values)
        spread = max_val - min_val

        print(f"   Average : {avg:.0f}")
        print(f"   Min     : {min_val}")
        print(f"   Max     : {max_val}")
        print(f"   Spread  : {spread}")
        print()

        if all(v == 0 for v in values):
            print("⚠️  All values are zero — load cell may not be connected to HX711")
            print("   Check E+, E-, A+, A- wiring from load cells to HX711")
        elif all(v == values[0] for v in values):
            print("⚠️  All values identical — sensor might be stuck")
            print("   Try power-cycling the HX711 (disconnect/reconnect VCC)")
        elif spread < 500:
            print("✅ Readings are stable (low noise) — ready for calibration!")
            print()
            print("   Next step:")
            print("     sudo python3 calibrate.py")
        elif spread < 5000:
            print("✅ Readings have moderate noise — acceptable for calibration")
            print("   Consider shorter wires or shielded cable for better results")
            print()
            print("   Next step:")
            print("     sudo python3 calibrate.py")
        else:
            print("⚠️  High noise detected. Possible causes:")
            print("   - Long or unshielded wires between load cell and HX711")
            print("   - Vibration or unstable mounting")
            print("   - Electrical interference from motors or power supply")

    print()
    print("=" * 60)
    GPIO.cleanup()


def _bcm_to_board(bcm_pin):
    """Approximate BCM → Board pin mapping for common pins."""
    mapping = {
        2: 3, 3: 5, 4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21,
        10: 19, 11: 23, 12: 32, 13: 33, 14: 8, 15: 10, 16: 36,
        17: 11, 18: 12, 19: 35, 20: 38, 21: 40, 22: 15, 23: 16,
        24: 18, 25: 22, 26: 37, 27: 13,
    }
    return mapping.get(bcm_pin, "?")


if __name__ == "__main__":
    main()
