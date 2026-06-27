"""
detector.py — Baseline Z-Score Detector for |DeltaGamma| Exceedance
ABR Weather Station Monitor — Plan 0412, Phase 1

Detects rising-edge exceedances in |DeltaGamma| above a z-score
threshold computed from the baseline (first 48 hours). Includes
topology change guard (station count delta) and debounce.

Metatron Dynamics, Inc.
"""

from collections import namedtuple


Detection = namedtuple("Detection", [
    "hour_index",
    "timestamp",
    "delta_gamma",
    "threshold",
    "exceedance_ratio",
    "b_variant",
    "station_count",
    "station_delta",
])


class BaselineDetector:
    """Z-score detector with topology guard and debounce.

    Uses hours 0-47 as baseline to compute mu and sigma.
    Evaluates hours 48-71 for rising-edge exceedances.

    Args:
        k: z-score threshold (default 2.0)
        sigma_min_factor: minimum sigma as fraction of mu (default 0.1)
        debounce_hours: minimum gap between predictions (default 6)
        station_delta_max: topology change guard (default 2)
    """

    def __init__(
        self,
        k: float = 2.0,
        sigma_min_factor: float = 0.1,
        debounce_hours: int = 6,
        station_delta_max: int = 2,
    ):
        self.k = k
        self.sigma_min_factor = sigma_min_factor
        self.debounce_hours = debounce_hours
        self.station_delta_max = station_delta_max

    def evaluate(
        self,
        dg_values: list,
        station_counts: list,
        timestamps: list,
        b_variant: str = "normalized",
    ) -> list:
        """Evaluate |DeltaGamma| timeseries for exceedance detections.

        Args:
            dg_values: list of |DeltaGamma| values (length 72)
            station_counts: list of station counts per hour
            timestamps: list of datetime objects
            b_variant: which B variant produced these values

        Returns:
            list of Detection namedtuples for rising-edge exceedances
            in the evaluation window (hours 48-71).
        """
        n = len(dg_values)
        if n < 49:
            return []

        # Baseline: hours 0-47
        baseline_end = min(48, n)
        baseline = [abs(v) for v in dg_values[:baseline_end]]

        mu = sum(baseline) / len(baseline)
        variance = sum((v - mu) ** 2 for v in baseline) / len(baseline)
        sigma = variance ** 0.5

        # Sigma floor: ensure finite threshold even for flat signals
        sigma = max(sigma, self.sigma_min_factor * mu) if mu > 0 else max(sigma, 1e-10)

        threshold = mu + self.k * sigma

        # Evaluate hours 48 through end
        detections = []
        last_detection_hour = -self.debounce_hours - 1

        eval_start = min(48, n - 1)
        for t in range(eval_start, n):
            dg_abs = abs(dg_values[t])

            # Rising edge: current exceeds threshold, previous did not
            prev_dg_abs = abs(dg_values[t - 1])
            if dg_abs <= threshold or prev_dg_abs > threshold:
                continue

            # Topology guard: station count change must be small
            station_delta = abs(station_counts[t] - station_counts[t - 1])
            if station_delta >= self.station_delta_max:
                continue

            # Debounce: skip if too close to previous detection
            if (t - last_detection_hour) < self.debounce_hours:
                continue

            exceedance_ratio = dg_abs / threshold if threshold > 0 else 0.0

            detections.append(Detection(
                hour_index=t,
                timestamp=timestamps[t],
                delta_gamma=dg_values[t],
                threshold=threshold,
                exceedance_ratio=exceedance_ratio,
                b_variant=b_variant,
                station_count=station_counts[t],
                station_delta=station_delta,
            ))
            last_detection_hour = t

        return detections
