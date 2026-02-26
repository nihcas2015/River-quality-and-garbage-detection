"""
Time-series anomaly detector for river sensor data.

Uses Exponential Weighted Moving Average (EWMA) and sliding-window
statistics (Z-score) to detect:
  1. Threshold violations  — value outside absolute safe range
  2. Sudden spikes/drops  — large rate-of-change between readings
  3. Statistical outliers  — Z-score exceeds adaptive threshold
  4. Trend drift           — EWMA deviates from long-term baseline

Runs entirely on the Pi4 edge node with zero extra dependencies
(only numpy, already required for YOLOv8).
"""

import logging
from collections import deque
import numpy as np
import config

log = logging.getLogger(__name__)


class _ChannelTracker:
    """Tracks one sensor channel (e.g. temperature or pH)."""

    def __init__(self, name, abs_min, abs_max, window, z_thresh, spike_thresh, ewma_alpha):
        self.name = name
        self.abs_min = abs_min
        self.abs_max = abs_max
        self.z_thresh = z_thresh
        self.spike_thresh = spike_thresh
        self.alpha = ewma_alpha

        self.history = deque(maxlen=window)
        self.ewma = None
        self.prev_value = None

    # ── core ──────────────────────────────────────────────────

    def update(self, value):
        """Feed a new reading and return a list of anomaly dicts (may be empty)."""
        anomalies = []

        # 1. Absolute-threshold check
        if value < self.abs_min or value > self.abs_max:
            anomalies.append({
                "type": "threshold",
                "sensor": self.name,
                "severity": "critical",
                "message": f"{self.name} = {value:.2f} outside safe range "
                           f"[{self.abs_min}, {self.abs_max}]",
                "value": round(value, 3),
            })

        # 2. Spike / sudden-change detection
        if self.prev_value is not None:
            delta = abs(value - self.prev_value)
            if delta > self.spike_thresh:
                anomalies.append({
                    "type": "spike",
                    "sensor": self.name,
                    "severity": "high",
                    "message": f"{self.name} changed by {delta:.2f} in one reading "
                               f"(threshold {self.spike_thresh})",
                    "value": round(value, 3),
                    "delta": round(delta, 3),
                })

        # 3. Z-score outlier (needs ≥5 history points)
        if len(self.history) >= 5:
            arr = np.array(self.history)
            mean = arr.mean()
            std = arr.std()
            if std > 1e-6:
                z = abs(value - mean) / std
                if z > self.z_thresh:
                    anomalies.append({
                        "type": "zscore",
                        "sensor": self.name,
                        "severity": "high",
                        "message": f"{self.name} Z-score = {z:.2f} "
                                   f"(mean {mean:.2f}, std {std:.2f})",
                        "value": round(value, 3),
                        "z_score": round(z, 2),
                    })

        # 4. EWMA drift (needs ≥10 history points)
        if self.ewma is not None and len(self.history) >= 10:
            arr = np.array(self.history)
            long_mean = arr.mean()
            drift = abs(self.ewma - long_mean)
            drift_threshold = max(arr.std() * 1.5, 0.5)
            if drift > drift_threshold:
                anomalies.append({
                    "type": "drift",
                    "sensor": self.name,
                    "severity": "medium",
                    "message": f"{self.name} trend drifting — EWMA {self.ewma:.2f} "
                               f"vs baseline {long_mean:.2f} (Δ {drift:.2f})",
                    "value": round(value, 3),
                    "ewma": round(self.ewma, 3),
                })

        # Update state
        self.history.append(value)
        self.prev_value = value
        if self.ewma is None:
            self.ewma = value
        else:
            self.ewma = self.alpha * value + (1 - self.alpha) * self.ewma

        return anomalies


class AnomalyDetector:
    """
    Time-series anomaly detector for temperature + pH + turbidity.

    Usage:
        ad = AnomalyDetector()
        result = ad.update(temperature=24.5, ph=7.1, turbidity=45.0)
        # result = {
        #   "anomaly_detected": True/False,
        #   "anomaly_list": [...],       # list of anomaly dicts
        #   "temperature": True/False,   # backward-compatible flag
        #   "ph": True/False,
        #   "turbidity": True/False,
        #   "stats": { ... },            # rolling statistics
        # }
    """

    def __init__(self):
        window = getattr(config, "ANOMALY_WINDOW", 30)
        z_thresh = getattr(config, "ANOMALY_Z_THRESHOLD", 2.5)
        temp_spike = getattr(config, "ANOMALY_TEMP_SPIKE", 5.0)
        ph_spike = getattr(config, "ANOMALY_PH_SPIKE", 1.0)
        turb_spike = getattr(config, "ANOMALY_TURB_SPIKE", 200.0)
        ewma_alpha = getattr(config, "ANOMALY_EWMA_ALPHA", 0.3)

        self.temp_tracker = _ChannelTracker(
            name="temperature",
            abs_min=config.TEMP_MIN, abs_max=config.TEMP_MAX,
            window=window, z_thresh=z_thresh,
            spike_thresh=temp_spike, ewma_alpha=ewma_alpha,
        )
        self.ph_tracker = _ChannelTracker(
            name="ph",
            abs_min=config.PH_MIN, abs_max=config.PH_MAX,
            window=window, z_thresh=z_thresh,
            spike_thresh=ph_spike, ewma_alpha=ewma_alpha,
        )
        self.turb_tracker = _ChannelTracker(
            name="turbidity",
            abs_min=config.TURBIDITY_MIN, abs_max=config.TURBIDITY_MAX,
            window=window, z_thresh=z_thresh,
            spike_thresh=turb_spike, ewma_alpha=ewma_alpha,
        )
        self.total_anomalies = 0
        log.info("AnomalyDetector initialised (window=%d, z=%.1f, ewma_α=%.2f)",
                 window, z_thresh, ewma_alpha)

    def update(self, temperature, ph, turbidity):
        """Process new sensor values and return anomaly report."""
        all_anomalies = []
        all_anomalies.extend(self.temp_tracker.update(temperature))
        all_anomalies.extend(self.ph_tracker.update(ph))
        all_anomalies.extend(self.turb_tracker.update(turbidity))

        temp_flag = any(a["sensor"] == "temperature" for a in all_anomalies)
        ph_flag = any(a["sensor"] == "ph" for a in all_anomalies)
        turb_flag = any(a["sensor"] == "turbidity" for a in all_anomalies)

        if all_anomalies:
            self.total_anomalies += len(all_anomalies)
            for a in all_anomalies:
                log.warning("ANOMALY [%s] %s — %s", a["severity"], a["type"], a["message"])

        # Rolling stats for dashboard display
        def _stats(tracker):
            if len(tracker.history) < 2:
                return None
            arr = np.array(tracker.history)
            return {
                "mean": round(float(arr.mean()), 3),
                "std": round(float(arr.std()), 3),
                "min": round(float(arr.min()), 3),
                "max": round(float(arr.max()), 3),
                "ewma": round(float(tracker.ewma), 3) if tracker.ewma else None,
                "samples": len(tracker.history),
            }

        return {
            # backward-compatible boolean flags
            "temperature": temp_flag,
            "ph": ph_flag,
            "turbidity": turb_flag,
            # rich detail
            "anomaly_detected": bool(all_anomalies),
            "anomaly_list": all_anomalies,
            "total_anomalies": self.total_anomalies,
            "stats": {
                "temperature": _stats(self.temp_tracker),
                "ph": _stats(self.ph_tracker),
                "turbidity": _stats(self.turb_tracker),
            },
        }
