"""
phase2_verify.py — Phase 2 Temporal Analysis & Lead Time
Run from repo root: python phase2_verify.py

Computes scalar baselines, ΔΓ, and lead times for both
B variants against observables.

Metatron Dynamics, Inc.
"""

import sys
sys.path.insert(0, ".")

from src.data.noaa_pipeline import run_pipeline
from src.data.measurement_mapping import (
    map_all_snapshots, COMPONENTS
)
from src.operators.weather_abr import (
    process_all_timesteps, print_gamma_summary
)
from src.analysis.scalar_baseline import (
    compute_scalar_indices, print_scalar_summary
)
from src.analysis.gamma_analysis import (
    compute_delta_gamma, compute_lead_times, print_lead_time_report
)

# =============================================================
# Origin declarations
# =============================================================
STATE = "CA"
BBOX = (33.5, 36.0, -121.0, -117.0)
PROXIMITY_THRESHOLD_KM = 150.0
COMP_TOPO = "all_pairs"
RHO_BASE = 0.1

print("=" * 70)
print("ABR Weather Station Monitor — Phase 2 Analysis")
print("=" * 70)

# --- Phase 0 ---
print("\n" + "-" * 70)
print("Phase 0: Data Pipeline")
print("-" * 70)
stations, snapshots = run_pipeline(state=STATE, bbox=BBOX)
fields = map_all_snapshots(
    snapshots, stations, PROXIMITY_THRESHOLD_KM, COMP_TOPO
)

# --- Scalar baselines ---
print("\n" + "-" * 70)
print("Scalar Baseline Indices (index-local)")
print("-" * 70)
scalar_results = compute_scalar_indices(fields)
print_scalar_summary(scalar_results)

# --- Both B variants ---
for b_var in ["normalized", "raw"]:
    print(f"\n{'=' * 70}")
    print(f"Phase 2: Temporal Analysis — B={b_var}")
    print(f"{'=' * 70}")

    # Compute Γ
    print(f"\nComputing Γ (B={b_var})...")
    gamma_results = process_all_timesteps(fields, RHO_BASE, b_var)

    # ΔΓ
    deltas = compute_delta_gamma(gamma_results)
    dg = [d["delta_gamma_total"] for d in deltas]
    dg_comp = [d["delta_gamma_comp"] for d in deltas]

    print(f"\n  ΔΓ total:  min={min(dg):.4f} max={max(dg):.4f} "
          f"mean={sum(abs(d) for d in dg)/len(dg):.4f} (mean |ΔΓ|)")
    print(f"  ΔΓ comp:   min={min(dg_comp):.4f} max={max(dg_comp):.4f} "
          f"mean={sum(abs(d) for d in dg_comp)/len(dg_comp):.4f} (mean |ΔΓ|)")

    # Lead time analysis
    analysis = compute_lead_times(gamma_results, scalar_results, b_var)
    print_lead_time_report(analysis)

# --- Cross-variant lead time comparison ---
print(f"\n{'=' * 70}")
print("CROSS-VARIANT LEAD TIME COMPARISON")
print(f"{'=' * 70}")

for b_var in ["normalized", "raw"]:
    gamma_results = process_all_timesteps(fields, RHO_BASE, b_var)
    analysis = compute_lead_times(gamma_results, scalar_results, b_var)

    all_leads = []
    for lt in analysis["lead_times"].values():
        all_leads.extend(lt["leads_from_dg_total"])

    if all_leads:
        mean_lead = sum(all_leads) / len(all_leads)
        pos = sum(1 for l in all_leads if l > 0)
        pct = pos / len(all_leads) * 100
    else:
        mean_lead = 0
        pos = 0
        pct = 0

    print(f"\n  B={b_var}:")
    print(f"    Mean lead (ΔΓ_total → scalar): {mean_lead:.1f} hr")
    print(f"    Positive leads: {pos}/{len(all_leads)} ({pct:.0f}%)")
    print(f"    ΔΓ peaks found: {analysis['n_gamma_peaks_total']}")

    # Per-scalar breakdown
    for sc_name, lt in analysis["lead_times"].items():
        if lt["mean_lead_total"] is not None:
            print(f"    {sc_name}: {lt['mean_lead_total']:.1f} hr "
                  f"({lt['n_scalar_peaks']} scalar peaks)")

print(f"\n{'=' * 70}")
print("Phase 2 status: COMPLETE")
print("=" * 70)
