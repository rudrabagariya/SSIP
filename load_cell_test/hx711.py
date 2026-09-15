"""
HX711 Load Cell Amplifier Driver for Raspberry Pi
Pure RPi.GPIO implementation — no external HX711 library needed.

Wiring:
    HX711 VCC  → Raspberry Pi 3.3V (Pin 1)
    HX711 GND  → Raspberry Pi GND  (Pin 6)
    HX711 DOUT → Raspberry Pi GPIO 5  (Pin 29)  [Data]
    HX711 SCK  → Raspberry Pi GPIO 6  (Pin 31)  [Clock]
"""

import time
import statistics
import RPi.GPIO as GPIO


class HX711:
    """
    Driver for the HX711 24-bit ADC used with load cells.

    Supports:
        - Channel A at gain 128 (default) or 64
        - Channel B at gain 32
        - Tare (zero offset)
        - Calibration with a known weight
        - Median / mean filtering over multiple readings
    """

    # Number of clock pulses determines channel & gain for the NEXT reading
    _GAIN_PULSES = {128: 25, 64: 27, 32: 26}

    def __init__(self, dout_pin=5, pd_sck_pin=6, gain=128):
        """
        Args:
            dout_pin:   GPIO pin connected to HX711 DOUT (BCM numbering)
            pd_sck_pin: GPIO pin connected to HX711 PD_SCK (BCM numbering)
            gain:       Amplifier gain — 128 or 64 for Channel A, 32 for Channel B
        """
        if gain not in self._GAIN_PULSES:
            raise ValueError(f"Gain must be 128, 64, or 32. Got: {gain}")

        self.dout_pin = dout_pin
        self.pd_sck_pin = pd_sck_pin
        self.gain = gain
        self._pulses = self._GAIN_PULSES[gain]

        # Calibration state
        self.offset = 0        # Raw tare offset (subtracted from every reading)
        self.scale = 1.0       # Conversion factor: grams = (raw - offset) / scale

        # Setup GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pd_sck_pin, GPIO.OUT)
        GPIO.setup(self.dout_pin, GPIO.IN)

        # Ensure the chip is awake
        GPIO.output(self.pd_sck_pin, GPIO.LOW)
        time.sleep(0.1)

        # Throw away the first reading to set the gain register
        self._read_raw()

    # ─── Low-Level Protocol ─────────────────────────────────────────

    def _is_ready(self):
        """HX711 signals data-ready by pulling DOUT LOW."""
        return GPIO.input(self.dout_pin) == 0

    def _wait_ready(self, timeout=5.0):
        """Block until DOUT goes LOW or timeout expires."""
        start = time.time()
        while not self._is_ready():
            if time.time() - start > timeout:
                raise TimeoutError(
                    "HX711 not responding. Check wiring:\n"
                    f"  DOUT → GPIO {self.dout_pin}  |  SCK → GPIO {self.pd_sck_pin}\n"
                    "  VCC → 3.3V  |  GND → GND"
                )
            time.sleep(0.001)

    def _read_raw(self):
        """
        Read one raw 24-bit signed value from the HX711.
        Returns an integer in the range [-8388608, 8388607].
        """
        # Ensure SCK is LOW before read
        GPIO.output(self.pd_sck_pin, GPIO.LOW)
        self._wait_ready()

        # Read 24 data bits (MSB first)
        # DO NOT time.sleep() here — RPi.GPIO C call overhead is ~1-2µs, which is within HX711 spec.
        raw = 0
        for _ in range(24):
            GPIO.output(self.pd_sck_pin, GPIO.HIGH)
            GPIO.output(self.pd_sck_pin, GPIO.LOW)
            raw = (raw << 1) | GPIO.input(self.dout_pin)

        # Send extra pulses to set gain for the NEXT conversion
        for _ in range(self._pulses - 24):
            GPIO.output(self.pd_sck_pin, GPIO.HIGH)
            GPIO.output(self.pd_sck_pin, GPIO.LOW)

        # Convert from 24-bit two's complement
        if raw & 0x800000:
            raw -= 0x1000000

        return raw

    # ─── High-Level API ─────────────────────────────────────────────

    def read_raw(self, times=5):
        """
        Take multiple raw readings and return the median (outlier-resistant).
        """
        readings = [self._read_raw() for _ in range(times)]
        return int(statistics.median(readings))

    def read_weight(self, times=5):
        """
        Read weight in grams (after tare and calibration).
        Returns float grams.
        """
        raw = self.read_raw(times)
        return (raw - self.offset) / self.scale

    def tare(self, times=15):
        """
        Zero the scale. Call with nothing on the platform.
        Takes `times` samples for accuracy.
        """
        print("⏳ Taring... keep the platform empty.")
        readings = [self._read_raw() for _ in range(times)]
        self.offset = int(statistics.median(readings))
        print(f"✅ Tare complete. Offset = {self.offset}")
        return self.offset

    def calibrate(self, known_weight_grams, times=15):
        """
        Calibrate the scale using a known reference weight.
        Must call tare() first with an empty platform.

        Args:
            known_weight_grams: Weight of the reference object in grams
            times: Number of samples to average
        """
        print(f"⏳ Calibrating with {known_weight_grams}g reference weight...")
        readings = [self._read_raw() for _ in range(times)]
        raw_value = int(statistics.median(readings))
        delta = raw_value - self.offset

        if abs(delta) < 100:
            print("⚠️  Warning: Very small signal delta. Check that:")
            print("    - The reference weight is on the platform")
            print("    - Load cell wiring is correct (E+, E-, A+, A-)")
            print("    - HX711 is powered from 3.3V")

        self.scale = delta / known_weight_grams
        print(f"✅ Calibration complete.")
        print(f"   Raw delta  = {delta}")
        print(f"   Scale      = {self.scale:.2f} units/gram")
        return self.scale

    def power_down(self):
        """Put HX711 into low-power sleep mode."""
        GPIO.output(self.pd_sck_pin, GPIO.LOW)
        GPIO.output(self.pd_sck_pin, GPIO.HIGH)
        time.sleep(0.0001)

    def power_up(self):
        """Wake HX711 from sleep mode."""
        GPIO.output(self.pd_sck_pin, GPIO.LOW)
        time.sleep(0.5)
        # Throw away first reading after wake-up
        self._read_raw()

    def cleanup(self):
        """Release GPIO resources."""
        GPIO.cleanup()

    # ─── Calibration Persistence ────────────────────────────────────

    def save_calibration(self, filepath="calibration.json"):
        """Save offset and scale to a JSON file."""
        import json
        data = {
            "offset": self.offset,
            "scale": self.scale,
            "gain": self.gain,
            "dout_pin": self.dout_pin,
            "pd_sck_pin": self.pd_sck_pin,
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"💾 Calibration saved to {filepath}")

    def load_calibration(self, filepath="calibration.json"):
        """Load offset and scale from a previously saved JSON file."""
        import json
        with open(filepath, "r") as f:
            data = json.load(f)
        self.offset = data["offset"]
        self.scale = data["scale"]
        print(f"📂 Calibration loaded from {filepath}")
        print(f"   Offset = {self.offset}")
        print(f"   Scale  = {self.scale:.2f} units/gram")
