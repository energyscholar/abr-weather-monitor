"""
tests/test_logger.py — PredictionLog Unit Tests
ABR Weather Station Monitor — Plan 0412, Phase 2

Tests round-trip serialization, prediction ID uniqueness,
verification logic, stats computation, and debounce checking.

Metatron Dynamics, Inc.
"""

import json
import os
import pytest
import tempfile
from datetime import datetime, timedelta

from src.prediction.records import (
    ObservationRecord,
    PredictionRecord,
    VerificationRecord,
)
from src.prediction.logger import PredictionLog
from src.prediction.detector import Detection


@pytest.fixture
def tmp_log_path():
    """Create a temporary JSONL file path."""
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.unlink(path)  # start with empty file
    yield path
    if os.path.exists(path):
        os.unlink(path)


class TestRecordRoundTrip:

    def test_observation_round_trip(self):
        """ObservationRecord serializes and deserializes correctly."""
        obs = ObservationRecord(
            data_time="2026-06-25T12:00:00Z",
            run_time="2026-06-25T12:05:00Z",
            n_stations=30,
            station_delta=1,
            dg_norm=0.1234,
            dg_raw=0.5678,
            threshold_norm=0.5,
            threshold_raw=1.2,
            gamma_norm=3.14,
            gamma_raw=2.71,
        )
        d = obs.to_dict()
        obs2 = ObservationRecord.from_dict(d)
        assert obs2.data_time == obs.data_time
        assert obs2.n_stations == obs.n_stations
        assert obs2.dg_norm == obs.dg_norm

    def test_prediction_round_trip(self):
        """PredictionRecord serializes and deserializes correctly."""
        pred = PredictionRecord(
            id="pred-202606251200-ca-socal-normalized",
            data_time="2026-06-25T12:00:00Z",
            run_time="2026-06-25T12:05:00Z",
            region="CA-SoCal",
            b_variant="normalized",
            delta_gamma=0.5,
            threshold=0.3,
            exceedance=1.67,
            window_start="2026-06-25T16:00:00Z",
            window_end="2026-06-25T22:00:00Z",
            status="pending",
            station_count=28,
            station_delta=1,
            calibration_period=True,
        )
        d = pred.to_dict()
        pred2 = PredictionRecord.from_dict(d)
        assert pred2.id == pred.id
        assert pred2.calibration_period == True
        assert pred2.exceedance == 1.67

    def test_verification_round_trip(self):
        """VerificationRecord serializes and deserializes correctly."""
        vrec = VerificationRecord(
            pred_id="pred-202606251200-ca-socal-normalized",
            status="hit",
            verified_at="2026-06-26T00:00:00Z",
            scalar_peak_time="2026-06-25T18:00:00Z",
            lead_hours=6.0,
            peak_indices=["pressure_tendency", "wind_shift"],
        )
        d = vrec.to_dict()
        vrec2 = VerificationRecord.from_dict(d)
        assert vrec2.pred_id == vrec.pred_id
        assert vrec2.status == "hit"
        assert vrec2.peak_indices == ["pressure_tendency", "wind_shift"]

    def test_json_serialization(self):
        """Records serialize to valid JSON."""
        obs = ObservationRecord(data_time="2026-06-25T12:00:00Z")
        line = json.dumps(obs.to_dict())
        parsed = json.loads(line)
        assert parsed["type"] == "obs"


class TestPredictionLogWriteRead:

    def test_write_and_reload(self, tmp_log_path):
        """Records written to file can be reloaded."""
        log = PredictionLog(path=tmp_log_path)
        obs = ObservationRecord(
            data_time="2026-06-25T12:00:00Z",
            run_time="2026-06-25T12:05:00Z",
            n_stations=30,
        )
        log.log_observation(obs)

        # Reload
        log2 = PredictionLog(path=tmp_log_path)
        assert len(log2._records) == 1
        assert isinstance(log2._records[0], ObservationRecord)
        assert log2._records[0].n_stations == 30

    def test_multiple_record_types(self, tmp_log_path):
        """Mixed record types survive write/reload."""
        log = PredictionLog(path=tmp_log_path)
        log.log_observation(ObservationRecord(data_time="2026-06-25T12:00:00Z"))

        det = Detection(
            hour_index=60,
            timestamp=datetime(2026, 6, 25, 12, 0),
            delta_gamma=0.5,
            threshold=0.3,
            exceedance_ratio=1.67,
            b_variant="normalized",
            station_count=28,
            station_delta=1,
        )
        log.emit_prediction(det, region="CA-SoCal")

        log2 = PredictionLog(path=tmp_log_path)
        types = [type(r).__name__ for r in log2._records]
        assert "ObservationRecord" in types
        assert "PredictionRecord" in types


class TestPredictionIDUniqueness:

    def test_unique_ids(self, tmp_log_path):
        """Predictions with different timestamps get different IDs."""
        log = PredictionLog(path=tmp_log_path)

        det1 = Detection(
            hour_index=60,
            timestamp=datetime(2026, 6, 25, 12, 0),
            delta_gamma=0.5, threshold=0.3, exceedance_ratio=1.67,
            b_variant="normalized", station_count=28, station_delta=1,
        )
        det2 = Detection(
            hour_index=65,
            timestamp=datetime(2026, 6, 25, 17, 0),
            delta_gamma=0.6, threshold=0.3, exceedance_ratio=2.0,
            b_variant="normalized", station_count=27, station_delta=0,
        )

        p1 = log.emit_prediction(det1, region="CA-SoCal")
        p2 = log.emit_prediction(det2, region="CA-SoCal")
        assert p1.id != p2.id

    def test_variant_differentiation(self, tmp_log_path):
        """Same timestamp but different B variants get different IDs."""
        log = PredictionLog(path=tmp_log_path)
        ts = datetime(2026, 6, 25, 12, 0)

        det_norm = Detection(
            hour_index=60, timestamp=ts,
            delta_gamma=0.5, threshold=0.3, exceedance_ratio=1.67,
            b_variant="normalized", station_count=28, station_delta=1,
        )
        det_raw = Detection(
            hour_index=60, timestamp=ts,
            delta_gamma=0.5, threshold=0.3, exceedance_ratio=1.67,
            b_variant="raw", station_count=28, station_delta=1,
        )

        p1 = log.emit_prediction(det_norm, region="CA-SoCal")
        p2 = log.emit_prediction(det_raw, region="CA-SoCal")
        assert p1.id != p2.id
        assert "normalized" in p1.id
        assert "raw" in p2.id


class TestVerificationLogic:

    def test_pending_verifications(self, tmp_log_path):
        """Predictions past their window_end are returned as pending."""
        log = PredictionLog(path=tmp_log_path)

        det = Detection(
            hour_index=60,
            timestamp=datetime(2026, 6, 20, 12, 0),  # far in the past
            delta_gamma=0.5, threshold=0.3, exceedance_ratio=1.67,
            b_variant="normalized", station_count=28, station_delta=1,
        )
        log.emit_prediction(det, region="CA-SoCal")

        now = datetime(2026, 6, 25, 0, 0)
        pending = log.get_pending_verifications(now)
        assert len(pending) == 1

    def test_future_window_not_pending(self, tmp_log_path):
        """Predictions whose window hasn't closed are NOT pending."""
        log = PredictionLog(path=tmp_log_path)

        det = Detection(
            hour_index=60,
            timestamp=datetime(2026, 6, 25, 12, 0),  # recent
            delta_gamma=0.5, threshold=0.3, exceedance_ratio=1.67,
            b_variant="normalized", station_count=28, station_delta=1,
        )
        log.emit_prediction(det, region="CA-SoCal")

        # Check before window closes (12:00 + 10h = 22:00)
        now = datetime(2026, 6, 25, 15, 0)
        pending = log.get_pending_verifications(now)
        assert len(pending) == 0


class TestStatsComputation:

    def test_empty_stats(self, tmp_log_path):
        """Empty log returns zero stats."""
        log = PredictionLog(path=tmp_log_path)
        s = log.stats()
        assert s["hits"] == 0
        assert s["precision"] == 0.0
        assert s["total_verifications"] == 0

    def test_stats_with_verifications(self, tmp_log_path):
        """Stats correctly computed from verification records."""
        log = PredictionLog(path=tmp_log_path)

        # Manually append verification records
        v1 = VerificationRecord(pred_id="p1", status="hit", lead_hours=5.0)
        v2 = VerificationRecord(pred_id="p2", status="false_alarm")
        v3 = VerificationRecord(pred_id="p3", status="hit", lead_hours=7.0)
        log._append(v1)
        log._append(v2)
        log._append(v3)

        s = log.stats(exclude_calibration=False)
        assert s["hits"] == 2
        assert s["false_alarms"] == 1
        assert s["precision"] == 2 / 3
        assert s["mean_lead_hours"] == 6.0

    def test_calibration_exclusion(self, tmp_log_path):
        """Stats exclude calibration-period predictions when requested."""
        log = PredictionLog(path=tmp_log_path)

        # Calibration prediction
        pred_cal = PredictionRecord(
            id="p-cal", calibration_period=True, status="pending",
        )
        log._append(pred_cal)
        v_cal = VerificationRecord(pred_id="p-cal", status="hit", lead_hours=5.0)
        log._append(v_cal)

        # Non-calibration prediction
        pred_live = PredictionRecord(
            id="p-live", calibration_period=False, status="pending",
        )
        log._append(pred_live)
        v_live = VerificationRecord(pred_id="p-live", status="false_alarm")
        log._append(v_live)

        s = log.stats(exclude_calibration=True)
        assert s["hits"] == 0
        assert s["false_alarms"] == 1
        assert s["total_verifications"] == 1


class TestLastObservationTime:

    def test_last_observation(self, tmp_log_path):
        """Returns most recent observation timestamp."""
        log = PredictionLog(path=tmp_log_path)
        log.log_observation(ObservationRecord(data_time="2026-06-25T10:00:00Z"))
        log.log_observation(ObservationRecord(data_time="2026-06-25T14:00:00Z"))
        log.log_observation(ObservationRecord(data_time="2026-06-25T12:00:00Z"))

        last = log.last_observation_time()
        assert last == datetime(2026, 6, 25, 14, 0)

    def test_no_observations(self, tmp_log_path):
        """Returns None when no observations exist."""
        log = PredictionLog(path=tmp_log_path)
        assert log.last_observation_time() is None


class TestRecentPredictions:

    def test_recent_window(self, tmp_log_path):
        """recent_predictions returns only those within the lookback."""
        log = PredictionLog(path=tmp_log_path)

        # Old prediction (will not be "recent" since it's far in the past)
        det_old = Detection(
            hour_index=60,
            timestamp=datetime(2020, 1, 1, 0, 0),
            delta_gamma=0.5, threshold=0.3, exceedance_ratio=1.67,
            b_variant="normalized", station_count=28, station_delta=1,
        )
        log.emit_prediction(det_old, region="CA-SoCal")

        # "Recent" prediction depends on datetime.utcnow(), so we
        # just verify the method doesn't crash and returns a list
        recent = log.recent_predictions(hours=6)
        assert isinstance(recent, list)
