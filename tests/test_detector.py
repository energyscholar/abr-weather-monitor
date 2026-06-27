"""
tests/test_detector.py — BaselineDetector Unit Tests
ABR Weather Station Monitor — Plan 0412, Phase 1

Tests detector behavior against synthetic timeseries:
flat signal, single spike, baseline-only spike, debounce,
topology guard, sigma floor.

Metatron Dynamics, Inc.
"""

import pytest
from datetime import datetime, timedelta
from src.prediction.detector import BaselineDetector, Detection


def make_timestamps(n=72):
    """Generate n hourly timestamps starting from a fixed time."""
    base = datetime(2026, 6, 25, 0, 0, 0)
    return [base + timedelta(hours=i) for i in range(n)]


def make_station_counts(n=72, value=25):
    """Generate uniform station counts."""
    return [value] * n


class TestFlatSignal:

    def test_no_detections_on_flat(self):
        """Flat signal produces no detections."""
        detector = BaselineDetector(k=2.0)
        dg = [1.0] * 72
        counts = make_station_counts()
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        assert len(detections) == 0

    def test_no_detections_on_zero(self):
        """All-zero signal produces no detections."""
        detector = BaselineDetector(k=2.0)
        dg = [0.0] * 72
        counts = make_station_counts()
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        assert len(detections) == 0


class TestSingleSpike:

    def test_spike_in_eval_window(self):
        """Single large spike at hour 60 should produce one detection."""
        detector = BaselineDetector(k=2.0)
        dg = [1.0] * 72
        dg[60] = 20.0  # well above any threshold from baseline of 1.0
        counts = make_station_counts()
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        assert len(detections) == 1
        assert detections[0].hour_index == 60
        assert detections[0].delta_gamma == 20.0
        assert detections[0].exceedance_ratio > 1.0

    def test_spike_in_baseline_window(self):
        """Spike at hour 30 (in baseline) should NOT produce detection."""
        detector = BaselineDetector(k=2.0)
        dg = [1.0] * 72
        dg[30] = 20.0
        counts = make_station_counts()
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        # No detection: the spike is in the baseline, and it raises
        # the baseline stats, but evaluation starts at hour 48
        # and there are no spikes there
        assert len(detections) == 0

    def test_detection_fields(self):
        """Detection namedtuple has correct field values."""
        detector = BaselineDetector(k=1.5)
        dg = [1.0] * 72
        dg[55] = 15.0
        counts = make_station_counts(value=30)
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts, b_variant="raw")
        assert len(detections) == 1
        det = detections[0]
        assert det.hour_index == 55
        assert det.b_variant == "raw"
        assert det.station_count == 30
        assert det.station_delta == 0
        assert det.threshold > 0


class TestDebounce:

    def test_two_spikes_within_debounce(self):
        """Two spikes 3 hours apart: only first detected (debounce=6)."""
        detector = BaselineDetector(k=2.0, debounce_hours=6)
        dg = [1.0] * 72
        dg[55] = 20.0
        dg[58] = 20.0
        counts = make_station_counts()
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        assert len(detections) == 1
        assert detections[0].hour_index == 55

    def test_two_spikes_outside_debounce(self):
        """Two spikes 8 hours apart: both detected (debounce=6)."""
        detector = BaselineDetector(k=2.0, debounce_hours=6)
        dg = [1.0] * 72
        dg[52] = 20.0
        dg[60] = 20.0
        counts = make_station_counts()
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        assert len(detections) == 2


class TestTopologyGuard:

    def test_station_delta_suppresses_detection(self):
        """Station count change >= station_delta_max suppresses detection."""
        detector = BaselineDetector(k=2.0, station_delta_max=2)
        dg = [1.0] * 72
        dg[60] = 20.0
        counts = make_station_counts(value=25)
        counts[60] = 27  # delta = 2, which is >= station_delta_max
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        assert len(detections) == 0

    def test_small_station_delta_allows_detection(self):
        """Station count change < station_delta_max allows detection."""
        detector = BaselineDetector(k=2.0, station_delta_max=2)
        dg = [1.0] * 72
        dg[60] = 20.0
        counts = make_station_counts(value=25)
        counts[60] = 26  # delta = 1, which is < station_delta_max
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        assert len(detections) == 1


class TestSigmaFloor:

    def test_zero_baseline_finite_threshold(self):
        """All-zero baseline still produces finite threshold via sigma floor."""
        detector = BaselineDetector(k=2.0, sigma_min_factor=0.1)
        # Baseline is all zeros, spike in eval window
        dg = [0.0] * 72
        dg[60] = 5.0
        counts = make_station_counts()
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        # With sigma_min_factor and zero mu, sigma gets floored to 1e-10
        # threshold = 0 + 2.0 * 1e-10 ~= 0
        # So the spike at 5.0 should be detected
        assert len(detections) == 1


class TestEdgeCases:

    def test_short_timeseries_no_crash(self):
        """Timeseries shorter than 49 hours returns empty list."""
        detector = BaselineDetector(k=2.0)
        dg = [1.0] * 30
        counts = [25] * 30
        ts = make_timestamps(n=30)
        detections = detector.evaluate(dg, counts, ts)
        assert len(detections) == 0

    def test_no_rising_edge(self):
        """Sustained high values (no rising edge) produce no detection."""
        detector = BaselineDetector(k=2.0)
        # Baseline low, but eval window is continuously high (no edge)
        dg = [1.0] * 48 + [20.0] * 24
        counts = make_station_counts()
        ts = make_timestamps()
        detections = detector.evaluate(dg, counts, ts)
        # Only hour 48 has a rising edge (prev=1.0, current=20.0)
        assert len(detections) == 1
        assert detections[0].hour_index == 48
