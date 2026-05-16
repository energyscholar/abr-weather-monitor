"""
gamma_analysis.py — Gamma Temporal Evolution & Lead Time
ABR Weather Station Monitor — Phase 2

Computes ΔΓ (rate of change of R-sustained circulation),
identifies Γ shift events, and measures temporal offset
relative to scalar index peaks.

Lead time = scalar peak time minus Γ shift time.
Positive lead time means Γ shifted before scalar peaked.

Metatron Dynamics, Inc.
"""


def compute_delta_gamma(gamma_results: list) -> list:
    """Compute ΔΓ = Γ(t) - Γ(t-1) for consecutive timesteps.

    Returns list of dicts, length len(gamma_results)-1.
    """
    deltas = []
    for t in range(len(gamma_results) - 1):
        r1 = gamma_results[t]
        r2 = gamma_results[t + 1]

        deltas.append({
            "timestamp": r2["timestamp"],
            "delta_gamma_total": r2["gamma_total"] - r1["gamma_total"],
            "delta_gamma_spatial": r2["gamma_spatial"] - r1["gamma_spatial"],
            "delta_gamma_comp": r2["gamma_comp"] - r1["gamma_comp"],
            "gamma_total": r2["gamma_total"],
            "gamma_spatial": r2["gamma_spatial"],
            "gamma_comp": r2["gamma_comp"],
        })

    return deltas


def find_peaks(values: list, timestamps: list, threshold_factor: float = 1.5):
    """Find local peaks in a timeseries.

    A peak is a value that exceeds threshold_factor × mean
    and is larger than both neighbors.

    Returns list of (index, timestamp, value).
    """
    if len(values) < 3:
        return []

    mean_val = sum(abs(v) for v in values) / len(values)
    threshold = threshold_factor * mean_val

    peaks = []
    for i in range(1, len(values) - 1):
        v = abs(values[i])
        if (v > threshold and
            v > abs(values[i-1]) and
            v > abs(values[i+1])):
            peaks.append((i, timestamps[i], values[i]))

    return peaks


def compute_lead_times(
    gamma_results: list,
    scalar_results: list,
    b_variant: str,
):
    """Compute lead times between Γ shifts and scalar peaks.

    Aligns gamma and scalar timeseries by timestamp.
    Finds peaks in |ΔΓ| and in each scalar index.
    For each scalar peak, finds the nearest preceding Γ peak.
    Lead time = scalar peak hour - Γ peak hour.

    Returns dict with lead time analysis.
    """
    # Compute ΔΓ
    deltas = compute_delta_gamma(gamma_results)

    # Align timestamps — scalar indices start at t=1 (they need
    # consecutive pairs), delta gamma also starts at t=1
    # Both should have timestamps from fields[1] onward
    delta_ts = [d["timestamp"] for d in deltas]
    scalar_ts = [s["timestamp"] for s in scalar_results]

    # Find common timestamps
    scalar_by_ts = {s["timestamp"]: s for s in scalar_results}
    delta_by_ts = {d["timestamp"]: d for d in deltas}

    common_ts = sorted(set(delta_ts) & set(scalar_ts))

    if len(common_ts) < 5:
        return {"error": "Too few common timestamps for lead time analysis"}

    # Extract aligned timeseries
    dg_total = [delta_by_ts[ts]["delta_gamma_total"] for ts in common_ts]
    dg_comp = [delta_by_ts[ts]["delta_gamma_comp"] for ts in common_ts]
    g_total = [delta_by_ts[ts]["gamma_total"] for ts in common_ts]

    sc_pressure = [scalar_by_ts[ts]["pressure_tendency"]
                   for ts in common_ts]
    sc_temp = [scalar_by_ts[ts]["temp_change"]
               for ts in common_ts]
    sc_humidity = [scalar_by_ts[ts]["humidity_change"]
                   for ts in common_ts]
    sc_wind = [scalar_by_ts[ts]["wind_shift"]
               for ts in common_ts]
    sc_dewdep = [scalar_by_ts[ts]["dewpoint_depression_change"]
                 for ts in common_ts]

    # Find peaks
    gamma_peaks_total = find_peaks(dg_total, common_ts)
    gamma_peaks_comp = find_peaks(dg_comp, common_ts)
    gamma_level_peaks = find_peaks(g_total, common_ts)

    scalar_peaks = {
        "pressure": find_peaks(sc_pressure, common_ts),
        "temperature": find_peaks(sc_temp, common_ts),
        "humidity": find_peaks(sc_humidity, common_ts),
        "wind": find_peaks(sc_wind, common_ts),
        "dewpoint_dep": find_peaks(sc_dewdep, common_ts),
    }

    # Compute lead times: for each scalar peak, find nearest
    # preceding gamma peak
    lead_times = {}

    for sc_name, sc_peaks in scalar_peaks.items():
        leads_total = []
        leads_comp = []

        for sc_idx, sc_ts, sc_val in sc_peaks:
            # Find nearest preceding ΔΓ peak
            preceding_total = [
                (g_idx, g_ts, g_val)
                for g_idx, g_ts, g_val in gamma_peaks_total
                if g_idx < sc_idx
            ]
            if preceding_total:
                nearest = preceding_total[-1]
                lead_hours = sc_idx - nearest[0]
                leads_total.append(lead_hours)

            preceding_comp = [
                (g_idx, g_ts, g_val)
                for g_idx, g_ts, g_val in gamma_peaks_comp
                if g_idx < sc_idx
            ]
            if preceding_comp:
                nearest = preceding_comp[-1]
                lead_hours = sc_idx - nearest[0]
                leads_comp.append(lead_hours)

        lead_times[sc_name] = {
            "n_scalar_peaks": len(sc_peaks),
            "leads_from_dg_total": leads_total,
            "leads_from_dg_comp": leads_comp,
            "mean_lead_total": (sum(leads_total) / len(leads_total)
                                if leads_total else None),
            "mean_lead_comp": (sum(leads_comp) / len(leads_comp)
                               if leads_comp else None),
        }

    return {
        "b_variant": b_variant,
        "n_common_timesteps": len(common_ts),
        "n_gamma_peaks_total": len(gamma_peaks_total),
        "n_gamma_peaks_comp": len(gamma_peaks_comp),
        "n_gamma_level_peaks": len(gamma_level_peaks),
        "lead_times": lead_times,
        "gamma_peaks_total": gamma_peaks_total,
        "gamma_peaks_comp": gamma_peaks_comp,
        "scalar_peaks": scalar_peaks,
        # Raw timeseries for plotting
        "timestamps": common_ts,
        "dg_total": dg_total,
        "dg_comp": dg_comp,
        "g_total": g_total,
        "sc_pressure": sc_pressure,
        "sc_temp": sc_temp,
        "sc_humidity": sc_humidity,
        "sc_wind": sc_wind,
        "sc_dewdep": sc_dewdep,
    }


def print_lead_time_report(analysis: dict):
    """Print lead time analysis results."""
    b_var = analysis["b_variant"]

    print(f"\n=== LEAD TIME ANALYSIS (B={b_var}) ===")
    print(f"  Common timesteps: {analysis['n_common_timesteps']}")
    print(f"  |ΔΓ| total peaks: {analysis['n_gamma_peaks_total']}")
    print(f"  |ΔΓ| comp peaks:  {analysis['n_gamma_peaks_comp']}")
    print(f"  Γ level peaks:    {analysis['n_gamma_level_peaks']}")

    print(f"\n  {'Scalar Index':<20s} {'Peaks':>6s} "
          f"{'Lead(ΔΓ_tot)':>14s} {'Lead(ΔΓ_comp)':>14s}")
    print(f"  {'-'*20} {'-'*6} {'-'*14} {'-'*14}")

    for sc_name, lt in analysis["lead_times"].items():
        n = lt["n_scalar_peaks"]
        lt_tot = lt["mean_lead_total"]
        lt_comp = lt["mean_lead_comp"]

        lt_tot_str = f"{lt_tot:.1f} hr" if lt_tot is not None else "—"
        lt_comp_str = f"{lt_comp:.1f} hr" if lt_comp is not None else "—"

        print(f"  {sc_name:<20s} {n:>6d} {lt_tot_str:>14s} {lt_comp_str:>14s}")

    # Summary
    all_leads_total = []
    all_leads_comp = []
    for lt in analysis["lead_times"].values():
        all_leads_total.extend(lt["leads_from_dg_total"])
        all_leads_comp.extend(lt["leads_from_dg_comp"])

    if all_leads_total:
        mean_all = sum(all_leads_total) / len(all_leads_total)
        pos = sum(1 for l in all_leads_total if l > 0)
        print(f"\n  Overall ΔΓ_total lead: mean={mean_all:.1f} hr "
              f"({pos}/{len(all_leads_total)} positive)")

    if all_leads_comp:
        mean_all = sum(all_leads_comp) / len(all_leads_comp)
        pos = sum(1 for l in all_leads_comp if l > 0)
        print(f"  Overall ΔΓ_comp lead:  mean={mean_all:.1f} hr "
              f"({pos}/{len(all_leads_comp)} positive)")
