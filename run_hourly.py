"""
run_hourly.py — ABR Weather Prediction System Main Entry Point
ABR Weather Station Monitor — Plan 0412, Phase 2

Fetches 72h data for each region, runs ABR operators, detects
DeltaGamma exceedances, emits predictions, verifies pending
predictions, and reports unpredicted events.

Usage: python run_hourly.py

Metatron Dynamics, Inc.
"""

import sys
import time
import traceback
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from config import (
    REGIONS, RHO_BASE, DETECTOR_K, DEBOUNCE_HOURS,
    STATION_DELTA_MAX, SIGMA_MIN_FACTOR, PREDICTIONS_PATH,
    CALIBRATION_END,
)
from src.data.noaa_pipeline import run_pipeline
from src.data.measurement_mapping import map_all_snapshots
from src.operators.weather_abr import process_all_timesteps
from src.analysis.gamma_analysis import compute_delta_gamma
from src.analysis.scalar_baseline import compute_scalar_indices
from src.prediction.detector import BaselineDetector
from src.prediction.logger import PredictionLog
from src.prediction.records import ObservationRecord


def is_calibration_period() -> bool:
    """Check if we are still in the calibration period."""
    try:
        cal_end = datetime.strptime(CALIBRATION_END, "%Y-%m-%dT%H:%M:%SZ")
        return datetime.utcnow() < cal_end
    except ValueError:
        return True


def run_region(region: dict, log: PredictionLog) -> dict:
    """Process a single region: fetch, compute, detect, verify.

    Returns dict with summary counts.
    """
    name = region["name"]
    state = region["state"]
    bbox = region["bbox"]
    proximity_km = region["proximity_km"]
    comp_topo = region["comp_topo"]

    summary = {
        "region": name,
        "observations_logged": 0,
        "predictions_emitted": 0,
        "verifications_completed": 0,
        "unpredicted_events": 0,
        "error": None,
    }

    # --- Fetch data ---
    try:
        stations, snapshots = run_pipeline(state=state, bbox=bbox)
    except Exception as e:
        # Retry once after 10s
        print(f"  Fetch failed: {e}. Retrying in 10s...")
        time.sleep(10)
        try:
            stations, snapshots = run_pipeline(state=state, bbox=bbox)
        except Exception as e2:
            print(f"  Retry failed: {e2}. Logging gap record.")
            gap_obs = ObservationRecord(
                data_time=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                run_time=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                n_stations=0,
                station_delta=0,
                dg_norm=0.0,
                dg_raw=0.0,
            )
            log.log_observation(gap_obs)
            summary["error"] = str(e2)
            return summary

    # --- Map to declared fields ---
    fields = map_all_snapshots(snapshots, stations, proximity_km, comp_topo)
    if len(fields) < 3:
        print(f"  WARNING: Only {len(fields)} fields for {name}. Skipping.")
        summary["error"] = f"Insufficient fields: {len(fields)}"
        return summary

    # --- Compute scalar baselines ---
    scalar_results = compute_scalar_indices(fields)

    # --- Compute Gamma + DeltaGamma for both B variants ---
    variants_data = {}
    for b_var in ["normalized", "raw"]:
        gamma_results = process_all_timesteps(fields, RHO_BASE, b_var)
        deltas = compute_delta_gamma(gamma_results)
        variants_data[b_var] = {
            "gamma_results": gamma_results,
            "deltas": deltas,
        }

    # --- Determine which hours are new ---
    last_obs_time = log.last_observation_time()
    delta_timestamps_norm = [
        d["timestamp"] for d in variants_data["normalized"]["deltas"]
    ]

    # --- Log observations and run detection ---
    detector = BaselineDetector(
        k=DETECTOR_K,
        sigma_min_factor=SIGMA_MIN_FACTOR,
        debounce_hours=DEBOUNCE_HOURS,
        station_delta_max=STATION_DELTA_MAX,
    )

    calibrating = is_calibration_period()

    for b_var in ["normalized", "raw"]:
        deltas = variants_data[b_var]["deltas"]
        gamma_results = variants_data[b_var]["gamma_results"]

        dg_values = [d["delta_gamma_total"] for d in deltas]
        timestamps = [d["timestamp"] for d in deltas]
        station_counts = [
            gamma_results[i + 1]["n_stations"]
            for i in range(len(deltas))
        ]

        # Log new observations (only for normalized variant to avoid duplicates)
        if b_var == "normalized":
            for t, delta in enumerate(deltas):
                ts = delta["timestamp"]
                if last_obs_time is not None and ts <= last_obs_time:
                    continue

                # Get matching raw delta
                raw_dg = 0.0
                if t < len(variants_data["raw"]["deltas"]):
                    raw_dg = variants_data["raw"]["deltas"][t]["delta_gamma_total"]

                station_delta = 0
                if t > 0:
                    station_delta = abs(station_counts[t] - station_counts[t - 1])

                obs = ObservationRecord(
                    data_time=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    run_time=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                    n_stations=station_counts[t],
                    station_delta=station_delta,
                    dg_norm=delta["delta_gamma_total"],
                    dg_raw=raw_dg,
                    gamma_norm=delta["gamma_total"],
                    gamma_raw=(
                        variants_data["raw"]["deltas"][t]["gamma_total"]
                        if t < len(variants_data["raw"]["deltas"]) else 0.0
                    ),
                )
                log.log_observation(obs)
                summary["observations_logged"] += 1

        # Run detector
        detections = detector.evaluate(
            dg_values, station_counts, timestamps, b_variant=b_var,
        )

        # Emit predictions for new detections
        recent = log.recent_predictions(hours=DEBOUNCE_HOURS)
        recent_ids = set(r.id for r in recent)

        for det in detections:
            # Check if this detection timestamp is new
            if last_obs_time is not None and det.timestamp <= last_obs_time:
                continue

            # Build prospective ID to check for duplicates
            prospective_id = (
                f"pred-{det.timestamp.strftime('%Y%m%d%H%M')}"
                f"-{name.lower().replace(' ', '-')}"
                f"-{det.b_variant}"
            )
            if prospective_id in recent_ids:
                continue

            pred = log.emit_prediction(
                det, region=name, calibration_period=calibrating,
            )
            summary["predictions_emitted"] += 1
            print(f"  PREDICTION: {pred.id} "
                  f"(DG={det.delta_gamma:.4f}, "
                  f"threshold={det.threshold:.4f}, "
                  f"exceedance={det.exceedance_ratio:.2f}x)")

    # --- Verify pending predictions ---
    now = datetime.utcnow()
    pending = log.get_pending_verifications(now)
    for pred in pending:
        vrec = log.verify_prediction(pred.id, scalar_results, fields)
        if vrec is not None:
            summary["verifications_completed"] += 1
            print(f"  VERIFIED: {pred.id} -> {vrec.status}"
                  f" (lead={vrec.lead_hours:.1f}h)")

    # --- Find unpredicted events ---
    unpredicted = log.find_unpredicted_events(scalar_results, fields, now)
    summary["unpredicted_events"] = len(unpredicted)
    for ev_ts, ev_indices in unpredicted:
        print(f"  UNPREDICTED: {ev_ts} — {', '.join(ev_indices)}")

    return summary


def main():
    """Run the hourly prediction pipeline for all regions."""
    print("=" * 70)
    print("ABR Weather Prediction System — Hourly Run")
    print(f"  Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"  Calibration period: {is_calibration_period()}")
    print("=" * 70)

    log = PredictionLog(path=PREDICTIONS_PATH)

    all_summaries = []
    for region in REGIONS:
        print(f"\n{'─' * 70}")
        print(f"Region: {region['name']}")
        print(f"{'─' * 70}")

        try:
            summary = run_region(region, log)
            all_summaries.append(summary)
        except Exception as e:
            print(f"  ERROR: {e}")
            traceback.print_exc()
            all_summaries.append({
                "region": region["name"],
                "error": str(e),
            })

    # --- Print summary ---
    print(f"\n{'=' * 70}")
    print("RUN SUMMARY")
    print(f"{'=' * 70}")
    total_obs = 0
    total_pred = 0
    total_verify = 0
    total_unpredicted = 0

    for s in all_summaries:
        region = s.get("region", "unknown")
        obs = s.get("observations_logged", 0)
        pred = s.get("predictions_emitted", 0)
        verify = s.get("verifications_completed", 0)
        unp = s.get("unpredicted_events", 0)
        err = s.get("error")

        total_obs += obs
        total_pred += pred
        total_verify += verify
        total_unpredicted += unp

        print(f"  {region}: {obs} obs, {pred} pred, "
              f"{verify} verified, {unp} unpredicted"
              + (f" [ERROR: {err}]" if err else ""))

    print(f"\n  TOTAL: {total_obs} observations, {total_pred} predictions, "
          f"{total_verify} verifications, {total_unpredicted} unpredicted")

    # --- Stats ---
    stats = log.stats()
    if stats["total_verifications"] > 0:
        print(f"\n  Cumulative stats (excluding calibration):")
        print(f"    Precision: {stats['precision']:.3f}")
        print(f"    Recall:    {stats['recall']:.3f}")
        print(f"    F1:        {stats['f1']:.3f}")
        print(f"    Mean lead: {stats['mean_lead_hours']:.1f}h")

    print(f"\n{'=' * 70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
