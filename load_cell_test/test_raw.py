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
    """Read one raw 24-bit value from HX711."""
    # Ensure SCK is LOW before waiting
    GPIO.output(sck_pin, GPIO.LOW)

    # Wait for DOUT to go LOW (data ready)
    timeout = time.time() + 3.0
    while GPIO.input(dout_pin) == 1:
        if time.time() > timeout:
            return None  # Sensor not responding
        time.sleep(0.0005)

    # Read 24 bits
    # IMPORTANT: DO NOT use time.sleep() inside this loop!
    # On Linux, time.sleep() yields to the OS scheduler and sleeps for 60-100+ microseconds.
    # The HX711 datasheet states that holding SCK HIGH for > 60µs forces the chip into
    # POWER DOWN mode, which causes DOUT to go HIGH and return all 1s (raw value -1).
    # In Python, the RPi.GPIO C call overhead itself is ~1-2 µs, which is ideal timing.
    raw = 0
    for _ in range(24):
        GPIO.output(sck_pin, GPIO.HIGH)
        GPIO.output(sck_pin, GPIO.LOW)
        raw = (raw << 1) | GPIO.input(dout_pin)

    # Extra pulses for gain setting (25 pulses = Gain 128 on Channel A)
    for _ in range(gain_pulses - 24):
        GPIO.output(sck_pin, GPIO.HIGH)
        GPIO.output(sck_pin, GPIO.LOW)

    # Convert 24-bit two's complement to signed integer
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

        if all(v == -1 for v in values):
            print("❌ All readings are -1 (0xFFFFFF — all 24 bits were 1)!")
            print("   This means DOUT stayed HIGH during the entire clocking sequence.")
            print()
            print("   Check these 3 common causes:")
            print("   1. PHYSICAL PIN VS BCM NUMBER:")
            print(f"      You ran with GPIO {args.dout} and GPIO {args.sck}.")
            print(f"      - DOUT must be connected to Physical Pin {_bcm_to_board(args.dout)} (GPIO {args.dout})")
            print(f"      - SCK  must be connected to Physical Pin {_bcm_to_board(args.sck)} (GPIO {args.sck})")
            print("      NOTE: Physical Pin 6 is GND! If you plugged SCK into Pin 6, it is connected to GND!")
            print("   2. VCC VOLTAGE (Why it worked on Arduino):")
            print("      Arduinos provide 5V. Many HX711 boards have an on-board 4.3V regulator that fails")
            print("      if given 3.3V. If your HX711 has an LED that is dim/off on 3.3V, it needs 5V.")
            print("   3. SWAPPED WIRES:")
            print("      Try running with pins swapped: sudo python3 test_raw.py --dout 6 --sck 5")
        elif all(v == 0 for v in values):
            print("⚠️  All values are zero — load cell bridge may not be connected to HX711")
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
