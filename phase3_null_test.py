"""
phase3_null_test.py — Null Test: Synthetic White Noise
ABR Weather Station Monitor

Confirms that Γ measures relational arrangement, not marginal
properties. Generates synthetic white noise with identical
per-component variance to real observations but destroyed
relational arrangement across stations. Uses the same station
geometry and proximity graph as the real data.

By Theorem 1 (Object Error), index-local operators produce
identical output on data with identical marginals regardless
of relational arrangement. Γ > 0 on real data and Γ ≈ 0 on
synthetic data confirms Γ is not index-local.

Metatron Dynamics, Inc.
"""

import sys
import math
import random
import json

sys.path.insert(0, ".")

from src.data.noaa_pipeline import run_pipeline
from src.data.measurement_mapping import (
    K_COMPONENTS,
    COMPONENTS,
    COMPONENT_SCALES,
    build_spatial_topology,
    build_component_topology_all_pairs,
    TopologyDeclaration,
    VectorNodeField1D,
    DeclaredField,
    map_all_snapshots,
)
from src.operators.weather_abr import compute_gamma


# =============================================================
# CONFIGURATION
# =============================================================

RHO_BASE = 0.1
EDGE_THRESHOLD_KM = 150.0
N_TRIALS = 10
COMP_TOPO = "all_pairs"


# =============================================================
# 1. EXTRACT GEOMETRY AND MARGINALS FROM REAL DATA
# =============================================================

def extract_geometry_and_marginals(fields):
    """Extract station positions, topology, and per-component
    variance from real declared fields.

    Returns dict with geometry, marginals, and reference Γ.
    """
    if not fields:
        raise ValueError("No admissible fields — cannot extract geometry")

    # Use first field's topology as reference
    ref = fields[0]
    topo = ref.topology

    # Collect all real values per component (AFTER unit scaling in M)
    comp_values = [[] for _ in range(K_COMPONENTS)]
    for f in fields:
        for c in range(K_COMPONENTS):
            for i in range(f.field.n):
                comp_values[c].append(f.field.data[c][i])

    # Per-component statistics (on scaled values)
    comp_stats = []
    for c in range(K_COMPONENTS):
        vals = comp_values[c]
        n = len(vals)
        mu = sum(vals) / n
        var = sum((v - mu) ** 2 for v in vals) / n
        comp_stats.append({
            "component": COMPONENTS[c],
            "mean": mu,
            "std": math.sqrt(var) if var > 0 else 0.0,
            "n_values": n,
        })

    # Collect real Γ for both B variants
    real_gammas_norm = []
    real_gammas_raw = []
    for f in fields:
        gn = compute_gamma(f, RHO_BASE, b_variant="normalized")
        gr = compute_gamma(f, RHO_BASE, b_variant="raw")
        real_gammas_norm.append(gn["gamma_total"])
        real_gammas_raw.append(gr["gamma_total"])

    return {
        "topology": topo,
        "n_stations": topo.n_stations,
        "station_ids": ref.field.station_ids,
        "comp_stats": comp_stats,
        "real_gammas_norm": real_gammas_norm,
        "real_gammas_raw": real_gammas_raw,
    }


# =============================================================
# 2. GENERATE SYNTHETIC NOISE FIELD
# =============================================================

def generate_null_field(geometry, trial_seed):
    """Generate one synthetic DeclaredField with white noise.

    Each component is i.i.d. normal with the same mean and std
    as the real data for that component (post-scaling). Station
    positions and proximity graph are identical to the real data.

    Relational arrangement (cross-station coupling, inter-
    component correlation) is destroyed by independent sampling.
    """
    rng = random.Random(trial_seed)
    topo = geometry["topology"]
    n = geometry["n_stations"]
    stats = geometry["comp_stats"]

    data = []
    for c in range(K_COMPONENTS):
        mu = stats[c]["mean"]
        sigma = stats[c]["std"]
        # i.i.d. normal per station — no relational structure
        col = [rng.gauss(mu, sigma) for _ in range(n)]
        data.append(col)

    field = VectorNodeField1D(
        data=data,
        n=n,
        k=K_COMPONENTS,
        station_ids=geometry["station_ids"],
        timestamp=f"null_trial_{trial_seed}",
    )

    return DeclaredField(
        field=field,
        topology=topo,
        timestamp=f"null_trial_{trial_seed}",
    )


# =============================================================
# 3. RUN NULL TEST
# =============================================================

def run_null_test():
    """Execute null test across N_TRIALS synthetic fields."""

    print("=" * 60)
    print("Phase 3: Null Test — Synthetic White Noise")
    print("=" * 60)
    print()

    # --- Load real data ---
    print("Loading real METAR data...")
    stations, snapshots = run_pipeline()

    print("Applying measurement mapping (M)...")
    fields = map_all_snapshots(
        snapshots, stations, EDGE_THRESHOLD_KM, COMP_TOPO
    )

    if not fields:
        print("ERROR: No admissible fields. Cannot run null test.")
        return

    # --- Extract geometry and marginals ---
    print("Extracting geometry and per-component marginals...")
    geometry = extract_geometry_and_marginals(fields)

    n_undirected = len(set(
        (min(i, j), max(i, j))
        for i, j in geometry["topology"].spatial_edges
    ))

    print(f"  Stations:        {geometry['n_stations']}")
    print(f"  Spatial edges:   {n_undirected} (undirected)")
    print(f"  Component pairs: {len(geometry['topology'].component_pairs)}")
    print()

    for s in geometry["comp_stats"]:
        print(f"  {s['component']:>15s}: "
              f"mean={s['mean']:8.4f}  std={s['std']:8.4f}  "
              f"(scaled)")
    print()

    # --- Real Γ summary ---
    for variant, key in [("B_normalized", "real_gammas_norm"),
                         ("B_raw", "real_gammas_raw")]:
        real_g = geometry[key]
        real_mean = sum(real_g) / len(real_g)
        real_abs_max = max(abs(g) for g in real_g)
        n_pos = sum(1 for g in real_g if g > 0)
        print(f"Real Γ ({variant}):")
        print(f"  Mean:  {real_mean:.6f}")
        print(f"  |Max|: {real_abs_max:.6f}")
        print(f"  Γ > 0: {n_pos}/{len(real_g)}")
        print()

    # --- Run null trials (both B variants) ---
    for variant in ["normalized", "raw"]:
        label = f"B_{variant}"
        real_key = ("real_gammas_norm" if variant == "normalized"
                    else "real_gammas_raw")
        real_g = geometry[real_key]
        real_abs_max = max(abs(g) for g in real_g)

        print(f"--- Null test: {label} ({N_TRIALS} trials) ---")

        null_gammas = []
        for trial in range(N_TRIALS):
            seed = 42 + trial
            null_field = generate_null_field(geometry, seed)
            g = compute_gamma(null_field, RHO_BASE, b_variant=variant)
            null_gammas.append(g["gamma_total"])

        null_mean = sum(null_gammas) / len(null_gammas)
        null_std = math.sqrt(
            sum((g - null_mean) ** 2 for g in null_gammas)
            / len(null_gammas)
        )
        null_abs_max = max(abs(g) for g in null_gammas)

        if null_abs_max > 0:
            separation = real_abs_max / null_abs_max
        else:
            separation = float("inf")

        print(f"  Null Γ mean:  {null_mean:.8f}")
        print(f"  Null Γ std:   {null_std:.8f}")
        print(f"  Null |max|:   {null_abs_max:.8f}")
        print(f"  Real |max|:   {real_abs_max:.6f}")
        print(f"  Separation:   {separation:.1f}x")

        # Pass criteria (either sufficient):
        #   1. null |max| < 0.01 (absolute negligibility)
        #   2. separation factor > 10x (relative negligibility)
        null_negligible = null_abs_max < 0.01
        separation_ok = separation > 10.0
        passed = null_negligible or separation_ok
        result_str = "PASS" if passed else "FAIL"
        print(f"  Result: {result_str}")

        if passed:
            print(f"  Null Γ negligible. Γ measures relational "
                  f"arrangement, not marginal properties.")
        else:
            print(f"  WARNING: Null Γ NOT negligible. Investigate.")
        print()

        # Per-trial detail
        print(f"  Per-trial null Γ ({label}):")
        for i, g in enumerate(null_gammas):
            print(f"    Trial {i}: Γ = {g:.8f}")
        print()

    # --- Save summary ---
    summary = {
        "phase": "3",
        "description": "Null test — synthetic white noise",
        "parameters": {
            "rho_base": RHO_BASE,
            "edge_threshold_km": EDGE_THRESHOLD_KM,
            "n_trials": N_TRIALS,
            "n_stations": geometry["n_stations"],
            "n_spatial_edges_undirected": n_undirected,
        },
        "comp_stats": geometry["comp_stats"],
        "declaration": (
            "Synthetic data preserves marginal distribution (variance "
            "per component, post-scaling) while destroying relational "
            "arrangement across stations. By Theorem 1 (Object Error), "
            "index-local operators produce identical output on this data "
            "and on real data with the same marginals. Γ > 0 on real "
            "data and Γ ≈ 0 on synthetic data confirms Γ measures "
            "relational arrangement, not marginal properties."
        ),
        "preprocessing_applied": (
            "No interpolation, gridding, spectral projection, or "
            "smoothing applied prior to operator A. Pre-A steps "
            "within M: topology declaration (proximity graph from "
            "real station positions), unit scaling (declared "
            "COMPONENT_SCALES). Synthetic data uses same scaled "
            "marginals. No NaN values in synthetic data."
        ),
    }

    out_path = "data/phase3_null_test_summary.json"
    try:
        with open(out_path, "w") as fp:
            json.dump(summary, fp, indent=2, default=str)
        print(f"Summary saved: {out_path}")
    except Exception as e:
        print(f"Could not save summary: {e}")


# =============================================================
# ENTRY POINT
# =============================================================

if __name__ == "__main__":
    run_null_test()
