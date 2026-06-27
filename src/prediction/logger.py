"""
logger.py — Prediction Log Manager
ABR Weather Station Monitor — Plan 0412, Phase 2

Manages the JSONL prediction log: appending observations,
emitting predictions, verifying outcomes, computing stats.

Metatron Dynamics, Inc.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Optional

from src.prediction.records import (
    ObservationRecord,
    PredictionRecord,
    VerificationRecord,
)


class PredictionLog:
    """Manages the JSONL prediction log file.

    All records are appended to a single JSONL file.
    Records are typed: obs, pred, verify.

    Args:
        path: path to the JSONL log file
    """

    def __init__(self, path: str = "data/predictions.jsonl"):
        self.path = path
        self._records = []
        self._load()

    def _load(self):
        """Load existing records from file."""
        self._records = []
        if not os.path.exists(self.path):
            return
        with open(self.path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    rtype = d.get("type", "")
                    if rtype == "obs":
                        self._records.append(ObservationRecord.from_dict(d))
                    elif rtype == "pred":
                        self._records.append(PredictionRecord.from_dict(d))
                    elif rtype == "verify":
                        self._records.append(VerificationRecord.from_dict(d))
                except (json.JSONDecodeError, KeyError):
                    continue

    def _append(self, record):
        """Append a record to both memory and file."""
        self._records.append(record)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(record.to_dict()) + "\n")

    def log_observation(self, obs: ObservationRecord):
        """Append an observation record."""
        self._append(obs)

    def emit_prediction(
        self,
        detection,
        region: str,
        calibration_period: bool = False,
        window_hours: tuple = (4, 10),
    ) -> PredictionRecord:
        """Create and log a prediction from a Detection.

        Args:
            detection: Detection namedtuple from BaselineDetector
            region: region name (e.g. "CA-SoCal")
            calibration_period: whether we're in calibration phase
            window_hours: (start_offset, end_offset) in hours

        Returns:
            the PredictionRecord that was emitted
        """
        data_time = detection.timestamp
        data_time_str = data_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        run_time_str = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        # Unique ID
        pred_id = (
            f"pred-{data_time.strftime('%Y%m%d%H%M')}"
            f"-{region.lower().replace(' ', '-')}"
            f"-{detection.b_variant}"
        )

        window_start = data_time + timedelta(hours=window_hours[0])
        window_end = data_time + timedelta(hours=window_hours[1])

        pred = PredictionRecord(
            type="pred",
            id=pred_id,
            data_time=data_time_str,
            run_time=run_time_str,
            region=region,
            b_variant=detection.b_variant,
            delta_gamma=detection.delta_gamma,
            threshold=detection.threshold,
            exceedance=detection.exceedance_ratio,
            window_start=window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            window_end=window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            status="pending",
            station_count=detection.station_count,
            station_delta=detection.station_delta,
            calibration_period=calibration_period,
        )

        self._append(pred)
        return pred

    def get_pending_verifications(self, current_time: datetime) -> list:
        """Return predictions whose windows have closed but are still pending.

        Args:
            current_time: current UTC time

        Returns:
            list of PredictionRecord with status="pending" and
            window_end < current_time
        """
        pending = []
        for r in self._records:
            if not isinstance(r, PredictionRecord):
                continue
            if r.status != "pending":
                continue
            try:
                window_end = datetime.strptime(r.window_end, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
            if current_time > window_end:
                pending.append(r)
        return pending

    def verify_prediction(
        self,
        pred_id: str,
        scalar_data: list,
        observation_data: list,
    ) -> Optional[VerificationRecord]:
        """Verify a prediction against scalar data within its window.

        Checks if any scalar index exceeded 2-sigma within the
        prediction window. Updates the prediction status and
        appends a verification record.

        Args:
            pred_id: prediction ID to verify
            scalar_data: list of scalar index dicts (from compute_scalar_indices)
            observation_data: list of DeclaredField objects (for timestamps)

        Returns:
            VerificationRecord or None if prediction not found
        """
        # Find the prediction
        pred = None
        for r in self._records:
            if isinstance(r, PredictionRecord) and r.id == pred_id:
                pred = r
                break
        if pred is None:
            return None

        try:
            window_start = datetime.strptime(pred.window_start, "%Y-%m-%dT%H:%M:%SZ")
            window_end = datetime.strptime(pred.window_end, "%Y-%m-%dT%H:%M:%SZ")
            data_time = datetime.strptime(pred.data_time, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return None

        # Compute scalar baseline stats
        keys = [
            "pressure_tendency", "temp_change", "humidity_change",
            "wind_shift", "dewpoint_depression_change",
        ]
        stats = {}
        for key in keys:
            vals = [r[key] for r in scalar_data if r[key] is not None]
            if len(vals) < 3:
                continue
            mu = sum(vals) / len(vals)
            var = sum((v - mu) ** 2 for v in vals) / len(vals)
            sigma = var ** 0.5
            stats[key] = (mu, sigma)

        # Check for scalar exceedance within window
        hit = False
        peak_time = None
        peak_indices = []
        best_lead = None

        for sr in scalar_data:
            ts = sr["timestamp"]
            if ts < window_start or ts > window_end:
                continue
            for key in keys:
                if key not in stats or sr[key] is None:
                    continue
                mu, sigma = stats[key]
                if sigma > 0 and sr[key] > mu + 2.0 * sigma:
                    hit = True
                    if peak_time is None or sr[key] > stats[key][0]:
                        peak_time = ts
                    if key not in peak_indices:
                        peak_indices.append(key)

        # Compute lead time
        lead_hours = 0.0
        if hit and peak_time is not None:
            lead_hours = (peak_time - data_time).total_seconds() / 3600.0

        status = "hit" if hit else "false_alarm"
        pred.status = status

        vrec = VerificationRecord(
            type="verify",
            pred_id=pred_id,
            status=status,
            verified_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            scalar_peak_time=peak_time.strftime("%Y-%m-%dT%H:%M:%SZ") if peak_time else "",
            lead_hours=lead_hours,
            peak_indices=peak_indices,
        )

        self._append(vrec)
        return vrec

    def find_unpredicted_events(
        self,
        scalar_data: list,
        observation_data: list,
        current_time: datetime,
    ) -> list:
        """Find scalar spikes > 3-sigma not preceded by a prediction.

        Args:
            scalar_data: list of scalar index dicts
            observation_data: list of DeclaredField objects
            current_time: current UTC time

        Returns:
            list of (timestamp, indices_exceeded) for unpredicted events
        """
        keys = [
            "pressure_tendency", "temp_change", "humidity_change",
            "wind_shift", "dewpoint_depression_change",
        ]

        # Compute baseline stats
        stats = {}
        for key in keys:
            vals = [r[key] for r in scalar_data if r[key] is not None]
            if len(vals) < 3:
                continue
            mu = sum(vals) / len(vals)
            var = sum((v - mu) ** 2 for v in vals) / len(vals)
            sigma = var ** 0.5
            stats[key] = (mu, sigma)

        # Find >3-sigma scalar events
        events = []
        for sr in scalar_data:
            ts = sr["timestamp"]
            exceeded = []
            for key in keys:
                if key not in stats or sr[key] is None:
                    continue
                mu, sigma = stats[key]
                if sigma > 0 and sr[key] > mu + 3.0 * sigma:
                    exceeded.append(key)
            if exceeded:
                events.append((ts, exceeded))

        # Check each event: was it preceded by a prediction?
        predictions = [
            r for r in self._records if isinstance(r, PredictionRecord)
        ]
        unpredicted = []
        for ev_ts, ev_indices in events:
            preceded = False
            for pred in predictions:
                try:
                    pred_data_time = datetime.strptime(
                        pred.data_time, "%Y-%m-%dT%H:%M:%SZ"
                    )
                except ValueError:
                    continue
                # Was this prediction within 10h before the event?
                offset = (ev_ts - pred_data_time).total_seconds() / 3600.0
                if 0 < offset <= 10:
                    preceded = True
                    break
            if not preceded:
                unpredicted.append((ev_ts, ev_indices))

        return unpredicted

    def stats(self, exclude_calibration: bool = True) -> dict:
        """Compute precision, recall, F1, and mean lead time.

        Args:
            exclude_calibration: if True, exclude predictions marked
                as calibration_period

        Returns:
            dict with hits, false_alarms, misses, precision, recall,
            f1, mean_lead_hours
        """
        verifications = [
            r for r in self._records if isinstance(r, VerificationRecord)
        ]

        if exclude_calibration:
            cal_ids = set()
            for r in self._records:
                if isinstance(r, PredictionRecord) and r.calibration_period:
                    cal_ids.add(r.id)
            verifications = [
                v for v in verifications if v.pred_id not in cal_ids
            ]

        hits = sum(1 for v in verifications if v.status == "hit")
        false_alarms = sum(1 for v in verifications if v.status == "false_alarm")
        misses = sum(1 for v in verifications if v.status == "miss")

        precision = hits / (hits + false_alarms) if (hits + false_alarms) > 0 else 0.0
        recall = hits / (hits + misses) if (hits + misses) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else 0.0)

        lead_times = [v.lead_hours for v in verifications if v.status == "hit"]
        mean_lead = sum(lead_times) / len(lead_times) if lead_times else 0.0

        return {
            "hits": hits,
            "false_alarms": false_alarms,
            "misses": misses,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "mean_lead_hours": mean_lead,
            "total_verifications": len(verifications),
        }

    def last_observation_time(self) -> Optional[datetime]:
        """Return timestamp of most recent observation record."""
        last = None
        for r in self._records:
            if isinstance(r, ObservationRecord) and r.data_time:
                try:
                    t = datetime.strptime(r.data_time, "%Y-%m-%dT%H:%M:%SZ")
                    if last is None or t > last:
                        last = t
                except ValueError:
                    continue
        return last

    def recent_predictions(self, hours: int = 6) -> list:
        """Return predictions emitted within the last N hours.

        Args:
            hours: lookback window in hours

        Returns:
            list of PredictionRecord
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        recent = []
        for r in self._records:
            if not isinstance(r, PredictionRecord):
                continue
            try:
                t = datetime.strptime(r.data_time, "%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                continue
            if t >= cutoff:
                recent.append(r)
        return recent
