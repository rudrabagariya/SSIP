"""
Scale Service — Background Qt Worker and Controller for HX711 Load Cell.

Features:
  - Asynchronous non-blocking QThread execution for smooth 60fps Qt UI.
  - Dual-stage signal processing: Olav Kallhovd outlier filter + Denys Sene 1D Kalman filter.
  - Statistical zero-tare with live progress reporting.
  - Event-driven settled weight detection (item placed / item removed).
  - Graceful hardware error handling.
"""

import math
import os
import sys
import time
from collections import deque
from threading import Lock

from PySide6.QtCore import QThread, Signal

# Ensure load_cell_test is in python path to load HX711 driver
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOAD_CELL_DIR = os.path.join(_BASE_DIR, "load_cell_test")
if _LOAD_CELL_DIR not in sys.path:
    sys.path.insert(0, _LOAD_CELL_DIR)

try:
    from hx711 import HX711
    HX711_AVAILABLE = True
except Exception as e:
    HX711 = None
    HX711_AVAILABLE = False
    print(f"[SCALE] Warning: HX711 module could not be loaded: {e}")

from config import (
    SCALE_CALIBRATION_FILE,
    SCALE_DOUT_PIN,
    SCALE_ENABLED,
    SCALE_SCK_PIN,
    SCALE_STABILITY_VARIANCE,
    SCALE_TARE_SAMPLES,
)


class SimpleKalmanFilter:
    """
    Denys Sene 1D Kalman Filter.
    Estimates the true state of a 1D linear system from noisy measurements.
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
        self._err_estimate = (1.0 - self._kalman_gain) * self._err_estimate + abs(
            self._last_estimate - self._current_estimate
        ) * self._q
        self._last_estimate = self._current_estimate
        return self._current_estimate


class KallhovdRollingFilter:
    """
    Olav Kallhovd median-trimmed rolling window despiker.
    Filters out extreme spikes and transient electrical bursts.
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
        s = sorted(self.buffer)
        n = len(s)
        if n < 4:
            return sum(s) / n
        # Discard the highest and lowest values
        return sum(s[1:-1]) / (n - 2)


class ScaleWorker(QThread):
    """
    Background worker thread for continuous HX711 reading and event emission.
    """
    sig_weight_updated = Signal(float, bool)     # (live_weight, is_stable)
    sig_weight_settled = Signal(float, float)     # (delta_weight, total_weight)
    sig_tare_progress = Signal(int, str)          # (percent, status_message)
    sig_tare_completed = Signal(bool, str, float) # (success, message, offset)
    sig_status_changed = Signal(str)             # ("INITIALIZING", "TARING", "READY", "ERROR")
    sig_error = Signal(str)                      # (error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._lock = Lock()
        self._tare_requested = False
        self._tare_samples = SCALE_TARE_SAMPLES
        
        self._current_weight = 0.0
        self._is_stable = False
        self._last_settled_weight = 0.0
        
        self.hx = None
        self.outlier_filter = KallhovdRollingFilter(size=8)
        self.kalman_filter = SimpleKalmanFilter(mea_e=3.0, est_e=3.0, q=0.05)
        self.recent_estimates = deque(maxlen=15)

    def request_tare(self, samples=None):
        """Request a zero tare to be executed by the background thread."""
        with self._lock:
            self._tare_samples = samples or SCALE_TARE_SAMPLES
            self._tare_requested = True

    def get_current_weight(self):
        """Thread-safe accessor for the latest stable/smoothed weight."""
        with self._lock:
            return self._current_weight

    def stop(self):
        """Signal thread to stop and wait for exit."""
        self._running = False
        self.wait(2000)

    def run(self):
        self._running = True
        self.sig_status_changed.emit("INITIALIZING")

        if not SCALE_ENABLED or not HX711_AVAILABLE:
            err_msg = "Scale disabled or HX711 driver unavailable."
            print(f"[SCALE] {err_msg}")
            self.sig_error.emit(err_msg)
            self.sig_status_changed.emit("DISABLED")
            return

        try:
            self.hx = HX711(dout_pin=SCALE_DOUT_PIN, pd_sck_pin=SCALE_SCK_PIN)
            print(f"[SCALE] HX711 initialized on DOUT={SCALE_DOUT_PIN}, SCK={SCALE_SCK_PIN}")
        except Exception as e:
            err_msg = f"Failed to initialize HX711 GPIO: {e}"
            print(f"[SCALE] {err_msg}")
            self.sig_error.emit(err_msg)
            self.sig_status_changed.emit("ERROR")
            return

        # Load calibration factor
        if os.path.exists(SCALE_CALIBRATION_FILE):
            try:
                self.hx.load_calibration(SCALE_CALIBRATION_FILE)
                print(f"[SCALE] Calibration loaded from {SCALE_CALIBRATION_FILE} (scale: {self.hx.REFERENCE_UNIT:.2f})")
            except Exception as e:
                print(f"[SCALE] Warning loading calibration: {e}")
        else:
            print(f"[SCALE] Calibration file '{SCALE_CALIBRATION_FILE}' not found! Scale requires calibration.")

        self.sig_status_changed.emit("READY")

        while self._running:
            # Check if a tare was requested
            if self._tare_requested:
                self._perform_tare()
                with self._lock:
                    self._tare_requested = False

            # Normal continuous weight reading
            try:
                # Read raw ADC difference from offset
                raw_diff = self.hx.get_value(times=1)
                ref_unit = self.hx.REFERENCE_UNIT
                
                if ref_unit and ref_unit != 0:
                    raw_weight = raw_diff / ref_unit
                else:
                    raw_weight = 0.0

                # 1. Olav Kallhovd despiker
                self.outlier_filter.add(raw_weight)
                despiked = self.outlier_filter.get_smoothed()

                # 2. Denys Sene 1D Kalman filter
                filtered_weight = self.kalman_filter.update(despiked)

                # 3. Deadband snap
                # Snap very small near-zero values exactly to 0.0 to prevent micro-jitter, 
                # but DO NOT clamp large negative values to 0.0 (prevents deadzones when scale drifts)
                if abs(filtered_weight) < 2.0:
                    internal_weight = 0.0
                else:
                    internal_weight = filtered_weight

                # 4. Stability detection
                self.recent_estimates.append(filtered_weight)
                is_stable = False
                if len(self.recent_estimates) == self.recent_estimates.maxlen:
                    spread = max(self.recent_estimates) - min(self.recent_estimates)
                    is_stable = (spread <= SCALE_STABILITY_VARIANCE)

                with self._lock:
                    self._current_weight = internal_weight
                    self._is_stable = is_stable

                # Emit live weight (UI can clamp negative values for display, but logic uses true negative values)
                self.sig_weight_updated.emit(internal_weight, is_stable)

                # Check for settled item placement/removal events
                if is_stable:
                    delta = internal_weight - self._last_settled_weight
                    if abs(delta) >= 3.0: # Minimum 3g change to trigger settled event
                        self._last_settled_weight = internal_weight
                        self.sig_weight_settled.emit(delta, internal_weight)

            except Exception as e:
                print(f"[SCALE] Read error: {e}")
                time.sleep(0.1)

            time.sleep(0.04)

        # Cleanup on exit
        if self.hx:
            try:
                self.hx.cleanup()
            except Exception:
                pass
        print("[SCALE] Worker thread stopped.")

    def _perform_tare(self):
        """Execute robust high-precision zero tare."""
        self.sig_status_changed.emit("TARING")
        samples = self._tare_samples
        print(f"[SCALE] Starting robust zero tare ({samples} samples)...")

        # 1. Thermal & bridge stabilization warm-up (flush initial readings)
        self.sig_tare_progress.emit(0, "Stabilizing sensor bridge...")
        warmup_start = time.time()
        while time.time() - warmup_start < 2.0:
            if not self._running:
                return
            try:
                self.hx.read_long()
            except Exception:
                pass
            time.sleep(0.05)

        # 2. Collect tare samples with live progress updates
        collected = []
        for i in range(1, samples + 1):
            if not self._running:
                return
            try:
                val = self.hx.read_long()
                collected.append(val)
            except Exception as e:
                print(f"[SCALE] Tare sample error: {e}")

            if i % 5 == 0 or i == samples:
                pct = int((i / samples) * 100)
                self.sig_tare_progress.emit(pct, f"Sampling baseline ({i}/{samples})...")
            time.sleep(0.02)

        if not collected:
            self.sig_tare_completed.emit(False, "No samples collected during tare", 0.0)
            self.sig_status_changed.emit("ERROR")
            return

        # 3. Sort and trim top & bottom 20% outliers
        collected.sort()
        trim = max(1, int(len(collected) * 0.20))
        clean_samples = collected[trim:-trim] if len(collected) > 2 * trim else collected
        new_offset = sum(clean_samples) / len(clean_samples)

        # Calculate standard deviation
        mean = new_offset
        var = sum((x - mean) ** 2 for x in clean_samples) / len(clean_samples)
        std_dev = math.sqrt(var)

        self.hx.set_offset(new_offset)
        print(f"[SCALE] ✅ Tare completed: Offset={new_offset:.0f}, StdDev=±{std_dev:.1f} counts")

        # 4. Synchronize all filter buffers to clean 0.0g
        self.outlier_filter.clear()
        self.recent_estimates.clear()
        self.kalman_filter.set_initial(0.0)
        for _ in range(self.outlier_filter.buffer.maxlen):
            self.outlier_filter.add(0.0)
        for _ in range(self.recent_estimates.maxlen):
            self.recent_estimates.append(0.0)

        with self._lock:
            self._current_weight = 0.0
            self._last_settled_weight = 0.0
            self._is_stable = True

        self.sig_tare_progress.emit(100, "Tare complete! Scale zeroed.")
        self.sig_tare_completed.emit(True, f"Zero offset calibrated (±{std_dev:.1f} counts noise)", new_offset)
        self.sig_status_changed.emit("READY")
