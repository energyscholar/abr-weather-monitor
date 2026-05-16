"""
phase1_5_topology_sensitivity.py — Topology Sensitivity Experiment
ABR Weather Station Monitor — Phase 1.5

Tests Gamma stability, sign structure, topology decomposition,
component dominance, and temporal coherence across proximity
thresholds: 75, 100, 125, 150 km.

Verifier-recommended experiment before Phase 2 lead-time claims.

Metatron Dynamics, Inc.
"""

import sys
sys.path.insert(0, ".")

from src.data.noaa_pipeline import run_pipeline
from src.data.measurement_mapping import (
    map_all_snapshots, COMPONENTS, K_COMPONENTS
)
from src.operators.weather_abr import (
    process_all_timesteps, sigma_sq_total
)

# =============================================================
# Origin declarations
# =============================================================
STATE = "CA"
BBOX = (33.5, 36.0, -121.0, -117.0)
COMP_TOPO = "all_pairs"
RHO_BASE = 0.1

THRESHOLDS_KM = [75.0, 100.0, 125.0, 150.0]

print("=" * 70)
print("ABR Weather Station Monitor — Phase 1.5 Topology Sensitivity")
print("=" * 70)

# --- Fetch data once ---
print("\nFetching data (shared across all thresholds)...")
stations, snapshots = run_pipeline(state=STATE, bbox=BBOX)

# --- Run sweep ---
sweep_results = {}

for threshold in THRESHOLDS_KM:
    print(f"\n{'=' * 70}")
    print(f"THRESHOLD: {threshold} km")
    print(f"{'=' * 70}")

    fields = map_all_snapshots(
        snapshots, stations, threshold, COMP_TOPO
    )

    if len(fields) < 48:
        print(f"  WARNING: Only {len(fields)} admissible timesteps "
              f"(need 48+). Threshold may be too small.")
        sweep_results[threshold] = None
        continue

    # Check connectivity stats
    n_stations = [df.topology.n_stations for df in fields]
    n_edges = [
        len(set((min(i,j), max(i,j))
                for i,j in df.topology.spatial_edges))
        for df in fields
    ]
    degrees = []
    for df in fields:
        adj = {}
        for (i, j) in df.topology.spatial_edges:
            adj.setdefault(i, set()).add(j)
        if adj:
            degrees.append(sum(len(v) for v in adj.values()) / len(adj))

    print(f"  Stations/hr: {min(n_stations)}–{max(n_stations)} "
          f"(mean {sum(n_stations)/len(n_stations):.1f})")
    print(f"  Edges/hr:    {min(n_edges)}–{max(n_edges)} "
          f"(mean {sum(n_edges)/len(n_edges):.1f})")
    print(f"  Mean degree: {min(degrees):.1f}–{max(degrees):.1f} "
          f"(mean {sum(degrees)/len(degrees):.1f})")

    print(f"\n  Running ABR operators...")
    results = process_all_timesteps(fields, RHO_BASE)

    # Collect summary stats
    gammas = [r["gamma_total"] for r in results]
    g_spatial = [r["gamma_spatial"] for r in results]
    g_comp = [r["gamma_comp"] for r in results]
    sq_e = [r["sigma_sq_e"] for r in results]
    sq_ba = [r["sigma_sq_ba"] for r in results]

    total_gamma = sum(gammas)
    total_comp = sum(g_comp)
    comp_frac = total_comp / total_gamma if total_gamma != 0 else 0
    all_positive = all(g > 0 for g in gammas)
    spatial_all_neg = all(g < 0 for g in g_spatial)

    sweep_results[threshold] = {
        "n_timesteps": len(results),
        "gamma_min": min(gammas),
        "gamma_max": max(gammas),
        "gamma_mean": sum(gammas) / len(gammas),
        "gamma_spatial_mean": sum(g_spatial) / len(g_spatial),
        "gamma_comp_mean": sum(g_comp) / len(g_comp),
        "comp_fraction": comp_frac,
        "all_gamma_positive": all_positive,
        "spatial_all_negative": spatial_all_neg,
        "mean_degree": sum(degrees) / len(degrees),
        "mean_edges": sum(n_edges) / len(n_edges),
        "mean_stations": sum(n_stations) / len(n_stations),
        "sq_e_mean": sum(sq_e) / len(sq_e),
        "sq_ba_mean": sum(sq_ba) / len(sq_ba),
        # Per-pair means for top coupling analysis
        "pair_means": [],
    }

    # Per-pair component σ²(E) means
    n_pairs = len(results[0]["per_pair_comp"])
    comp_pairs = results[0]["e_field"].comp_pairs
    pair_data = []
    for p in range(n_pairs):
        vals = [r["per_pair_comp"][p] for r in results]
        pair_data.append((p, comp_pairs[p], sum(vals) / len(vals)))
    pair_data.sort(key=lambda x: x[2], reverse=True)
    sweep_results[threshold]["pair_means"] = pair_data

    print(f"\n  Γ: min={min(gammas):.2f} max={max(gammas):.2f} "
          f"mean={sum(gammas)/len(gammas):.2f}")
    print(f"  Γ spatial mean: {sum(g_spatial)/len(g_spatial):.2f}")
    print(f"  Γ comp mean:    {sum(g_comp)/len(g_comp):.2f}")
    print(f"  Comp fraction:  {comp_frac*100:.1f}%")
    print(f"  All Γ > 0:      {all_positive}")


# =============================================================
# COMPARISON TABLE
# =============================================================
print(f"\n\n{'=' * 70}")
print("TOPOLOGY SENSITIVITY COMPARISON")
print(f"{'=' * 70}")

header = f"{'Threshold':>10s} {'Stations':>9s} {'Edges':>7s} {'Degree':>7s} "
header += f"{'Γ mean':>9s} {'Γ_sp':>9s} {'Γ_cp':>9s} {'Comp%':>7s} {'Γ>0':>5s}"
print(header)
print("-" * len(header))

for t in THRESHOLDS_KM:
    r = sweep_results.get(t)
    if r is None:
        print(f"{t:>8.0f}km   {'INSUFFICIENT DATA':>50s}")
        continue
    print(f"{t:>8.0f}km "
          f"{r['mean_stations']:>9.1f} "
          f"{r['mean_edges']:>7.1f} "
          f"{r['mean_degree']:>7.1f} "
          f"{r['gamma_mean']:>9.2f} "
          f"{r['gamma_spatial_mean']:>9.2f} "
          f"{r['gamma_comp_mean']:>9.2f} "
          f"{r['comp_fraction']*100:>6.1f}% "
          f"{'yes' if r['all_gamma_positive'] else 'NO':>5s}")

# --- Top coupling stability ---
print(f"\n{'=' * 70}")
print("TOP 3 COMPONENT PAIRS BY MEAN σ²(E) — PER THRESHOLD")
print(f"{'=' * 70}")

for t in THRESHOLDS_KM:
    r = sweep_results.get(t)
    if r is None:
        continue
    print(f"\n  {t:.0f} km:")
    for rank, (p_idx, (a, b), mean_val) in enumerate(r["pair_means"][:3]):
        print(f"    {rank+1}. {COMPONENTS[a]:>15s} — {COMPONENTS[b]:<15s}: "
              f"σ²={mean_val:.2f}")

# --- Sensitivity assessment ---
print(f"\n{'=' * 70}")
print("SENSITIVITY ASSESSMENT")
print(f"{'=' * 70}")

valid = [(t, sweep_results[t]) for t in THRESHOLDS_KM
         if sweep_results.get(t) is not None]

if len(valid) >= 2:
    gamma_range = max(r["gamma_mean"] for _, r in valid) - \
                  min(r["gamma_mean"] for _, r in valid)
    gamma_mean_all = sum(r["gamma_mean"] for _, r in valid) / len(valid)
    gamma_cv = gamma_range / gamma_mean_all if gamma_mean_all > 0 else 0

    comp_fracs = [r["comp_fraction"] for _, r in valid]
    comp_stable = max(comp_fracs) - min(comp_fracs)

    # Check if top pair is same across all thresholds
    top_pairs = [r["pair_means"][0][1] for _, r in valid]
    top_pair_stable = all(p == top_pairs[0] for p in top_pairs)

    print(f"  Γ mean range:      {gamma_range:.2f} "
          f"(CV={gamma_cv:.2f})")
    print(f"  Comp fraction range: "
          f"{min(comp_fracs)*100:.1f}%–{max(comp_fracs)*100:.1f}%")
    print(f"  Top pair stable:   {top_pair_stable} "
          f"({COMPONENTS[top_pairs[0][0]]}—{COMPONENTS[top_pairs[0][1]]})")

    if gamma_cv < 0.3:
        print("\n  FINDING: Γ is relatively STABLE across thresholds.")
        print("  Component coupling dominates regardless of spatial density.")
    elif gamma_cv < 0.6:
        print("\n  FINDING: Γ shows MODERATE sensitivity to threshold.")
        print("  Spatial topology contributes meaningfully.")
    else:
        print("\n  FINDING: Γ is HIGHLY SENSITIVE to threshold.")
        print("  Spatial topology dominates — threshold choice is critical.")

    all_pos = all(r["all_gamma_positive"] for _, r in valid)
    print(f"\n  Γ > 0 at all thresholds: {all_pos}")
    if all_pos:
        print("  R sustains total relational variance across all "
              "tested spatial densities.")
