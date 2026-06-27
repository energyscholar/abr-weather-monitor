"""
calibrate.py — Detector Calibration Against Scalar Baselines
ABR Weather Station Monitor — Plan 0412, Phase 1

Runs BaselineDetector across a range of k values against the
current 72h dataset. For each detection, checks whether any
scalar index exceeded 2-sigma within 4-10 hours after.

Produces a calibration report with GO/NO-GO gate decision.

Usage: python -m src.prediction.calibrate

Metatron Dynamics, Inc.
"""

import json
import sys
from datetime import datetime

sys.path.insert(0, ".")

from src.data.noaa_pipeline import run_pipeline
from src.data.measurement_mapping import map_all_snapshots
from src.operators.weather_abr import process_all_timesteps
from src.analysis.gamma_analysis import compute_delta_gamma
from src.analysis.scalar_baseline import compute_scalar_indices
from src.prediction.detector import BaselineDetector


# =============================================================
# Origin declarations (match phase2_verify.py)
# =============================================================
STATE = "CA"
BBOX = (33.5, 36.0, -121.0, -117.0)
PROXIMITY_THRESHOLD_KM = 150.0
COMP_TOPO = "all_pairs"
RHO_BASE = 0.1


# =============================================================
# Scalar event detection
# =============================================================

def find_scalar_events(scalar_results: list, sigma_factor: float = 2.0) -> list:
    """Find hours where any scalar index exceeds sigma_factor * sigma
    above its own baseline mean.

    Returns list of (hour_index, timestamp, indices_exceeded).
    """
    keys = [
        "pressure_tendency", "temp_change", "humidity_change",
        "wind_shift", "dewpoint_depression_change",
    ]

    # Compute per-index baseline stats across full timeseries
    stats = {}
    for key in keys:
        vals = [r[key] for r in scalar_results if r[key] is not None]
        if len(vals) < 3:
            continue
        mu = sum(vals) / len(vals)
        var = sum((v - mu) ** 2 for v in vals) / len(vals)
        sigma = var ** 0.5
        stats[key] = (mu, sigma)

    events = []
    for t, r in enumerate(scalar_results):
        exceeded = []
        for key in keys:
            if key not in stats or r[key] is None:
                continue
            mu, sigma = stats[key]
            if sigma > 0 and r[key] > mu + sigma_factor * sigma:
                exceeded.append(key)
        if exceeded:
            events.append((t, r["timestamp"], exceeded))

    return events


def check_detection_hit(
    detection_hour: int,
    scalar_events: list,
    window_start_hours: int = 4,
    window_end_hours: int = 10,
) -> tuple:
    """Check if any scalar event occurred within the prediction window
    after a detection.

    Returns (is_hit, matching_event_hour, matching_indices) or
    (False, None, None).
    """
    for ev_hour, ev_ts, ev_indices in scalar_events:
        offset = ev_hour - detection_hour
        if window_start_hours <= offset <= window_end_hours:
            return True, ev_hour, ev_indices
    return False, None, None


# =============================================================
# Calibration sweep
# =============================================================

def run_calibration():
    """Run full calibration pipeline."""
    print("=" * 70)
    print("ABR Weather Station Monitor — Detector Calibration")
    print("=" * 70)

    # --- Fetch data ---
    print("\nPhase 0: Data Pipeline")
    print("-" * 70)
    stations, snapshots = run_pipeline(state=STATE, bbox=BBOX)
    fields = map_all_snapshots(
        snapshots, stations, PROXIMITY_THRESHOLD_KM, COMP_TOPO
    )

    if len(fields) < 49:
        print(f"ERROR: Only {len(fields)} timesteps. Need >= 49 for calibration.")
        return

    # --- Scalar baselines ---
    print("\nComputing scalar baselines...")
    scalar_results = compute_scalar_indices(fields)
    scalar_events = find_scalar_events(scalar_results, sigma_factor=2.0)
    print(f"  Scalar events (>2-sigma): {len(scalar_events)}")

    # Independent scalar events for recall denominator:
    # scalar events >3-sigma (strong events that should be predicted)
    strong_scalar_events = find_scalar_events(scalar_results, sigma_factor=3.0)
    # Only count those in the evaluation window (hours 48+)
    eval_scalar_events = [
        (h, ts, idx) for h, ts, idx in strong_scalar_events if h >= 48
    ]
    n_independent = len(eval_scalar_events)
    print(f"  Strong scalar events in eval window (>3-sigma, h>=48): {n_independent}")

    # --- Process both B variants ---
    results_by_variant = {}
    for b_var in ["normalized", "raw"]:
        print(f"\nComputing Gamma (B={b_var})...")
        gamma_results = process_all_timesteps(fields, RHO_BASE, b_var)
        deltas = compute_delta_gamma(gamma_results)

        dg_values = [d["delta_gamma_total"] for d in deltas]
        timestamps = [d["timestamp"] for d in deltas]
        station_counts = [
            fields[i + 1].topology.n_stations
            for i in range(len(deltas))
        ]

        results_by_variant[b_var] = {
            "dg_values": dg_values,
            "timestamps": timestamps,
            "station_counts": station_counts,
        }

    # --- Calibration sweep ---
    print("\n" + "=" * 70)
    print("CALIBRATION SWEEP")
    print("=" * 70)

    k_values = [1.0, 1.5, 2.0, 2.5, 3.0]
    all_results = []

    for b_var in ["normalized", "raw"]:
        data = results_by_variant[b_var]
        print(f"\n--- B={b_var} ---")
        print(f"  {'k':>4s} | {'Det':>4s} | {'Hits':>4s} | {'FA':>4s} | "
              f"{'Miss':>4s} | {'Prec':>6s} | {'Recall':>6s} | {'F1':>6s}")
        print(f"  {'-'*4} | {'-'*4} | {'-'*4} | {'-'*4} | "
              f"{'-'*4} | {'-'*6} | {'-'*6} | {'-'*6}")

        for k in k_values:
            detector = BaselineDetector(k=k)
            detections = detector.evaluate(
                data["dg_values"],
                data["station_counts"],
                data["timestamps"],
                b_variant=b_var,
            )

            # Score each detection
            hits = 0
            false_alarms = 0
            for det in detections:
                is_hit, _, _ = check_detection_hit(
                    det.hour_index, scalar_events,
                )
                if is_hit:
                    hits += 1
                else:
                    false_alarms += 1

            # Missed events: strong scalar events not preceded by detection
            missed = 0
            for ev_hour, ev_ts, ev_indices in eval_scalar_events:
                preceded = False
                for det in detections:
                    offset = ev_hour - det.hour_index
                    if 4 <= offset <= 10:
                        preceded = True
                        break
                if not preceded:
                    missed += 1

            # Metrics
            precision = hits / (hits + false_alarms) if (hits + false_alarms) > 0 else 0.0
            recall = hits / (hits + missed) if (hits + missed) > 0 else 0.0
            f1 = (2 * precision * recall / (precision + recall)
                  if (precision + recall) > 0 else 0.0)

            print(f"  {k:4.1f} | {len(detections):4d} | {hits:4d} | "
                  f"{false_alarms:4d} | {missed:4d} | {precision:6.3f} | "
                  f"{recall:6.3f} | {f1:6.3f}")

            all_results.append({
                "b_variant": b_var,
                "k": k,
                "detections": len(detections),
                "hits": hits,
                "false_alarms": false_alarms,
                "missed": missed,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            })

    # --- Gate decision ---
    best = max(all_results, key=lambda r: r["f1"])
    best_recall = best["recall"]
    best_precision = best["precision"]

    if best_recall >= 0.70 and best_precision >= 0.30:
        gate = "GO"
    elif all(r["recall"] < 0.50 or r["precision"] < 0.15 for r in all_results):
        gate = "NO-GO"
    else:
        gate = "BORDERLINE"

    print(f"\n{'=' * 70}")
    print(f"GATE DECISION: {gate}")
    print(f"  Best F1: {best['f1']:.3f} (k={best['k']}, B={best['b_variant']})")
    print(f"  Precision: {best['precision']:.3f}, Recall: {best['recall']:.3f}")
    print(f"  Recommended k: {best['k']}")
    print(f"  Independent scalar events (eval window): {n_independent}")
    print(f"{'=' * 70}")

    # --- Write report ---
    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "dataset": f"{STATE}-SoCal 72h",
        "n_timesteps": len(fields),
        "n_stations_range": [
            min(f.topology.n_stations for f in fields),
            max(f.topology.n_stations for f in fields),
        ],
        "results": all_results,
        "recommended_k": best["k"],
        "recommended_b_variant": best["b_variant"],
        "gate": gate,
        "independent_scalar_events": n_independent,
        "notes": (
            f"Gate={gate}. Best F1={best['f1']:.3f} at k={best['k']} "
            f"B={best['b_variant']}. "
            f"Precision={best['precision']:.3f}, Recall={best['recall']:.3f}. "
            f"{n_independent} strong scalar events in evaluation window."
        ),
    }

    report_path = "data/calibration_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nCalibration report written to {report_path}")

    return report


if __name__ == "__main__":
    run_calibration()
