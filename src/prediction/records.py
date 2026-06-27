"""
records.py — Prediction System Data Records
ABR Weather Station Monitor — Plan 0412, Phase 2

Dataclasses for observation, prediction, and verification records.
All serialize to/from JSON for JSONL logging.

Metatron Dynamics, Inc.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class ObservationRecord:
    """Hourly observation summary for the prediction log."""
    type: str = "obs"
    data_time: str = ""
    run_time: str = ""
    n_stations: int = 0
    station_delta: int = 0
    dg_norm: float = 0.0
    dg_raw: float = 0.0
    threshold_norm: float = 0.0
    threshold_raw: float = 0.0
    gamma_norm: float = 0.0
    gamma_raw: float = 0.0

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data_time": self.data_time,
            "run_time": self.run_time,
            "n_stations": self.n_stations,
            "station_delta": self.station_delta,
            "dg_norm": self.dg_norm,
            "dg_raw": self.dg_raw,
            "threshold_norm": self.threshold_norm,
            "threshold_raw": self.threshold_raw,
            "gamma_norm": self.gamma_norm,
            "gamma_raw": self.gamma_raw,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ObservationRecord":
        return cls(
            type=d.get("type", "obs"),
            data_time=d.get("data_time", ""),
            run_time=d.get("run_time", ""),
            n_stations=d.get("n_stations", 0),
            station_delta=d.get("station_delta", 0),
            dg_norm=d.get("dg_norm", 0.0),
            dg_raw=d.get("dg_raw", 0.0),
            threshold_norm=d.get("threshold_norm", 0.0),
            threshold_raw=d.get("threshold_raw", 0.0),
            gamma_norm=d.get("gamma_norm", 0.0),
            gamma_raw=d.get("gamma_raw", 0.0),
        )


@dataclass
class PredictionRecord:
    """A prediction of upcoming weather change."""
    type: str = "pred"
    id: str = ""
    data_time: str = ""
    run_time: str = ""
    region: str = ""
    b_variant: str = ""
    delta_gamma: float = 0.0
    threshold: float = 0.0
    exceedance: float = 0.0
    window_start: str = ""
    window_end: str = ""
    status: str = "pending"
    station_count: int = 0
    station_delta: int = 0
    calibration_period: bool = False

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "id": self.id,
            "data_time": self.data_time,
            "run_time": self.run_time,
            "region": self.region,
            "b_variant": self.b_variant,
            "delta_gamma": self.delta_gamma,
            "threshold": self.threshold,
            "exceedance": self.exceedance,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "status": self.status,
            "station_count": self.station_count,
            "station_delta": self.station_delta,
            "calibration_period": self.calibration_period,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PredictionRecord":
        return cls(
            type=d.get("type", "pred"),
            id=d.get("id", ""),
            data_time=d.get("data_time", ""),
            run_time=d.get("run_time", ""),
            region=d.get("region", ""),
            b_variant=d.get("b_variant", ""),
            delta_gamma=d.get("delta_gamma", 0.0),
            threshold=d.get("threshold", 0.0),
            exceedance=d.get("exceedance", 0.0),
            window_start=d.get("window_start", ""),
            window_end=d.get("window_end", ""),
            status=d.get("status", "pending"),
            station_count=d.get("station_count", 0),
            station_delta=d.get("station_delta", 0),
            calibration_period=d.get("calibration_period", False),
        )


@dataclass
class VerificationRecord:
    """Verification outcome for a prediction."""
    type: str = "verify"
    pred_id: str = ""
    status: str = ""  # hit, false_alarm, miss
    verified_at: str = ""
    scalar_peak_time: str = ""
    lead_hours: float = 0.0
    peak_indices: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "pred_id": self.pred_id,
            "status": self.status,
            "verified_at": self.verified_at,
            "scalar_peak_time": self.scalar_peak_time,
            "lead_hours": self.lead_hours,
            "peak_indices": self.peak_indices,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VerificationRecord":
        return cls(
            type=d.get("type", "verify"),
            pred_id=d.get("pred_id", ""),
            status=d.get("status", ""),
            verified_at=d.get("verified_at", ""),
            scalar_peak_time=d.get("scalar_peak_time", ""),
            lead_hours=d.get("lead_hours", 0.0),
            peak_indices=d.get("peak_indices", []),
        )
