"""
scalar_baseline.py — Conventional Scalar Index Computation
ABR Weather Station Monitor — Phase 2

Computes standard scalar meteorological indices from the same
raw data used by the ABR operator pass. These are index-local
measures (per-station values aggregated through symmetric
functions) and are in the null space of relational structure
by Theorem 3.

All indices are computed from consecutive DeclaredField pairs
(t, t+1) using only stations present at BOTH timesteps.

Metatron Dynamics, Inc.
"""

import math
from src.data.measurement_mapping import COMPONENTS, COMPONENT_SCALES


def _common_stations(df1, df2):
    """Find stations present in both timesteps.

    Returns list of (station_id, idx_in_df1, idx_in_df2).
    """
    idx1 = df1.topology.station_index
    idx2 = df2.topology.station_index
    common = []
    for sid in idx1:
        if sid in idx2:
            common.append((sid, idx1[sid], idx2[sid]))
    return common


def compute_scalar_indices(fields: list) -> list:
    """Compute scalar indices for consecutive timestep pairs.

    For each pair (t, t+1), computes per-station differences
    then aggregates via mean absolute value (symmetric function).

    Returns list of dicts, length len(fields)-1.
    Each dict contains scalar indices at time t+1.
    """
    results = []

    for t in range(len(fields) - 1):
        df1 = fields[t]
        df2 = fields[t + 1]
        common = _common_stations(df1, df2)
        n = len(common)

        if n < 3:
            results.append({
                "timestamp": df2.timestamp,
                "n_common": n,
                "pressure_tendency": None,
                "temp_change": None,
                "humidity_change": None,
                "wind_shift": None,
                "dewpoint_depression_change": None,
                "max_pressure_tendency": None,
                "max_temp_change": None,
            })
            continue

        # Per-station differences for each component
        # Components are unit-scaled in the field, so we
        # multiply back by scale to get physical units for
        # interpretability. The index-local character is
        # the same either way.
        diffs = {c: [] for c in range(len(COMPONENTS))}
        for sid, i1, i2 in common:
            for c in range(len(COMPONENTS)):
                v1 = df1.field.data[c][i1] * COMPONENT_SCALES[c]
                v2 = df2.field.data[c][i2] * COMPONENT_SCALES[c]
                diffs[c].append(v2 - v1)

        # Pressure tendency (hPa/hr) — mean and max absolute
        p_diffs = diffs[1]  # pressure_hpa
        pressure_tendency = sum(abs(d) for d in p_diffs) / n
        max_pressure_tendency = max(abs(d) for d in p_diffs)

        # Temperature change (°C/hr)
        t_diffs = diffs[0]  # temp_c
        temp_change = sum(abs(d) for d in t_diffs) / n
        max_temp_change = max(abs(d) for d in t_diffs)

        # Humidity change (%/hr)
        h_diffs = diffs[2]  # humidity_pct
        humidity_change = sum(abs(d) for d in h_diffs) / n

        # Wind shift (kt/hr) — magnitude of (Δu, Δv) vector
        u_diffs = diffs[3]  # wind_u_kt
        v_diffs = diffs[4]  # wind_v_kt
        wind_shifts = [
            math.sqrt(u_diffs[i]**2 + v_diffs[i]**2)
            for i in range(n)
        ]
        wind_shift = sum(wind_shifts) / n

        # Dewpoint depression change
        # Depression = T - Td at each station
        # Change in depression from t to t+1
        dep_diffs = []
        for sid, i1, i2 in common:
            t1 = df1.field.data[0][i1] * COMPONENT_SCALES[0]
            td1 = df1.field.data[5][i1] * COMPONENT_SCALES[5]
            t2 = df2.field.data[0][i2] * COMPONENT_SCALES[0]
            td2 = df2.field.data[5][i2] * COMPONENT_SCALES[5]
            dep1 = t1 - td1
            dep2 = t2 - td2
            dep_diffs.append(dep2 - dep1)
        dewpoint_depression_change = sum(abs(d) for d in dep_diffs) / n

        results.append({
            "timestamp": df2.timestamp,
            "n_common": n,
            "pressure_tendency": pressure_tendency,
            "temp_change": temp_change,
            "humidity_change": humidity_change,
            "wind_shift": wind_shift,
            "dewpoint_depression_change": dewpoint_depression_change,
            "max_pressure_tendency": max_pressure_tendency,
            "max_temp_change": max_temp_change,
        })

    return results


def print_scalar_summary(results: list):
    """Print summary of scalar indices."""
    valid = [r for r in results if r["pressure_tendency"] is not None]
    if not valid:
        print("  No valid scalar index computations.")
        return

    print(f"\n=== SCALAR INDEX SUMMARY ===")
    print(f"  Valid timesteps: {len(valid)}")

    for key, unit in [
        ("pressure_tendency", "hPa/hr"),
        ("temp_change", "°C/hr"),
        ("humidity_change", "%/hr"),
        ("wind_shift", "kt/hr"),
        ("dewpoint_depression_change", "°C/hr"),
    ]:
        vals = [r[key] for r in valid]
        print(f"  {key:>30s}: min={min(vals):.3f} "
              f"max={max(vals):.3f} mean={sum(vals)/len(vals):.3f} {unit}")
