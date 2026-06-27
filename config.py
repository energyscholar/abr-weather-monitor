"""
config.py — ABR Weather Prediction System Configuration
ABR Weather Station Monitor — Plan 0412, Phase 2

Central configuration for regions, detector parameters,
and prediction windows.

Metatron Dynamics, Inc.
"""

from datetime import timedelta

REGIONS = [
    {
        "name": "CA-SoCal",
        "state": "CA",
        "bbox": (33.5, 36.0, -121.0, -117.0),
        "proximity_km": 150.0,
        "comp_topo": "all_pairs",
    },
]

RHO_BASE = 0.1
DETECTOR_K = 1.5  # Calibration report: best F1=0.667 at k=1.5 B=normalized
DEBOUNCE_HOURS = 6
STATION_DELTA_MAX = 2
SIGMA_MIN_FACTOR = 0.1
PREDICTION_WINDOW = (timedelta(hours=4), timedelta(hours=10))
CALIBRATION_END = "2026-07-15T00:00:00Z"  # 2 weeks from approximate launch
PREDICTIONS_PATH = "data/predictions.jsonl"
