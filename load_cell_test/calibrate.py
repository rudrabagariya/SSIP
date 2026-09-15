#!/usr/bin/env python3
"""
Step 1: Calibrate your HX711 + Load Cell setup.

Run this script ONCE to:
  1. Tare (zero) the empty platform
  2. Place a known weight and calculate the scale factor
  3. Save calibration data to calibration.json

Usage:
    sudo python3 calibrate.py
    sudo python3 calibrate.py --dout 5 --sck 6 --gain 128

After calibration, use read_weight.py for continuous measurements.
"""

import argparse
import sys
import time

from hx711 import HX711


def main():
    parser = argparse.ArgumentParser(
        description="HX711 Load Cell Calibration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Wiring Reference (BCM numbering):
  HX711 VCC  → Pi 3.3V (Pin 1)
  HX711 GND  → Pi GND  (Pin 6)
  HX711 DOUT → Pi GPIO 5  (Pin 29)
  HX711 SCK  → Pi GPIO 6  (Pin 31)

Calibration Steps:
  1. Remove everything from the load cell platform
  2. Script records the tare (zero) offset
  3. Place a known weight on the platform
  4. Script calculates the conversion factor
  5. Calibration is saved to calibration.json
        """,
    )
    parser.add_argument("--dout", type=int, default=5,
                        help="GPIO pin for HX711 DOUT (default: 5)")
    parser.add_argument("--sck", type=int, default=6,
                        help="GPIO pin for HX711 PD_SCK (default: 6)")
    parser.add_argument("--gain", type=int, default=128, choices=[128, 64, 32],
                        help="Amplifier gain (default: 128)")
    parser.add_argument("--samples", type=int, default=20,
                        help="Number of samples per measurement (default: 20)")
    parser.add_argument("--output", type=str, default="calibration.json",
                        help="Output calibration file (default: calibration.json)")
    args = parser.parse_args()

    print("=" * 60)
    print("  HX711 Load Cell Calibration Tool")
    print("=" * 60)
    print(f"  DOUT Pin : GPIO {args.dout}")
    print(f"  SCK Pin  : GPIO {args.sck}")
    print(f"  Gain     : {args.gain}")
    print(f"  Samples  : {args.samples}")
    print("=" * 60)
    print()

    try:
        hx = HX711(dout_pin=args.dout, pd_sck_pin=args.sck, gain=args.gain)
    except Exception as e:
        print(f"❌ Failed to initialize HX711: {e}")
        sys.exit(1)

    try:
        # ── Step 1: Read some raw values to verify the sensor is working ──
        print("📡 Testing connection — reading 5 raw values...")
        for i in range(5):
            raw = hx.read_raw(times=3)
            print(f"   Reading {i+1}: {raw}")
            time.sleep(0.2)

        if raw == 0:
            print("\n⚠️  All readings are zero. Possible issues:")
            print("    - Check HX711 VCC is connected to 3.3V")
            print("    - Check DOUT and SCK pins are correct")
            print("    - Check load cell wires (E+, E-, A+, A-)")
            sys.exit(1)

        print("\n✅ HX711 is responding!\n")

        # ── Step 2: Tare ──
        input("🔹 Step 1: Remove EVERYTHING from the load cell platform.\n"
              "   Press Enter when the platform is empty...")
        print()

        hx.tare(times=args.samples)
        print()

        # ── Step 3: Calibrate ──
        weight_str = input("🔹 Step 2: Enter the weight of your reference object in grams\n"
                           "   (e.g., 500 for a 500g bottle): ").strip()
        try:
            known_weight = float(weight_str)
        except ValueError:
            print(f"❌ Invalid weight: '{weight_str}'. Must be a number.")
            sys.exit(1)

        if known_weight <= 0:
            print("❌ Weight must be positive.")
            sys.exit(1)

        input(f"\n   Now place the {known_weight}g object on the platform.\n"
              f"   Press Enter when it's stable...")
        print()

        hx.calibrate(known_weight, times=args.samples)
        print()

        # ── Step 4: Verify ──
        print("📊 Verification — taking 10 readings with the weight still on:")
        print("-" * 40)
        readings = []
        for i in range(10):
            w = hx.read_weight(times=5)
            readings.append(w)
            print(f"   Reading {i+1:2d}: {w:8.1f} g")
            time.sleep(0.3)

        avg = sum(readings) / len(readings)
        error = abs(avg - known_weight)
        error_pct = (error / known_weight) * 100

        print("-" * 40)
        print(f"   Average  : {avg:.1f} g")
        print(f"   Expected : {known_weight:.1f} g")
        print(f"   Error    : {error:.1f} g ({error_pct:.1f}%)")
        print()

        if error_pct > 5:
            print("⚠️  Error is above 5%. Consider:")
            print("    - Ensuring the load cells are properly mounted")
            print("    - Using a more accurate reference weight")
            print("    - Running calibration again")
        else:
            print("✅ Calibration looks good!")

        # ── Step 5: Remove weight and verify tare ──
        print()
        input("🔹 Step 3: Remove the weight from the platform.\n"
              "   Press Enter when empty...")
        print()

        print("📊 Zero verification — should read close to 0g:")
        for i in range(5):
            w = hx.read_weight(times=5)
            print(f"   Reading {i+1}: {w:8.1f} g")
            time.sleep(0.3)

        # ── Step 6: Save ──
        print()
        hx.save_calibration(args.output)

        print()
        print("=" * 60)
        print("  ✅ CALIBRATION COMPLETE!")
        print("=" * 60)
        print(f"  Offset : {hx.offset}")
        print(f"  Scale  : {hx.scale:.4f} units/gram")
        print(f"  Saved  : {args.output}")
        print()
        print("  Next step: Run continuous weight readings with:")
        print("    sudo python3 read_weight.py")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n⚠️  Calibration interrupted by user.")
    except Exception as e:
        print(f"\n❌ Error during calibration: {e}")
        raise
    finally:
        hx.cleanup()


if __name__ == "__main__":
    main()
