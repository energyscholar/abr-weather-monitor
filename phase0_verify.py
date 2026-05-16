"""
phase0_verify.py — Phase 0 Live Data Verification
Run from repo root: python phase0_verify.py

Pulls 72 hours of CA Central Coast METAR data,
applies M, declares topology, and prints verification report.
"""

import sys
sys.path.insert(0, ".")

from src.data.noaa_pipeline import (
    run_pipeline, print_snapshot_summary
)
from src.data.measurement_mapping import (
    map_all_snapshots, print_topology_report, verify_topology,
    COMPONENTS, K_COMPONENTS
)

# =============================================================
# Origin declarations for this verification run
# =============================================================
STATE = "CA"
BBOX = (33.5, 36.0, -121.0, -117.0)  # SB to SD, coast to desert edge
PROXIMITY_THRESHOLD_KM = 150.0        # Origin declares
COMP_TOPO = "all_pairs"               # Origin declares
RHO_BASE = 0.1                        # Origin declares (for Phase 1)

print("=" * 60)
print("ABR Weather Station Monitor — Phase 0 Verification")
print("=" * 60)
print(f"\nOrigin declarations:")
print(f"  State: {STATE}")
print(f"  Bbox: {BBOX}")
print(f"  Proximity threshold: {PROXIMITY_THRESHOLD_KM} km")
print(f"  Component topology: {COMP_TOPO}")
print(f"  Components ({K_COMPONENTS}): {COMPONENTS}")
print()

# --- Step 1: Fetch data ---
print("-" * 60)
print("STEP 1: Data Acquisition")
print("-" * 60)
stations, snapshots = run_pipeline(state=STATE, bbox=BBOX)

# --- Step 2: Raw data sample ---
print("\n" + "-" * 60)
print("STEP 2: Raw Data Sample")
print("-" * 60)
print_snapshot_summary(snapshots, n=3)

# --- Step 3: Apply M ---
print("\n" + "-" * 60)
print("STEP 3: Measurement Mapping M")
print("-" * 60)
fields = map_all_snapshots(
    snapshots, stations, PROXIMITY_THRESHOLD_KM, COMP_TOPO
)

# --- Step 4: Topology verification ---
print("\n" + "-" * 60)
print("STEP 4: Topology Verification")
print("-" * 60)
print_topology_report(fields, n=3)

# --- Step 5: Field value ranges ---
print("\n" + "-" * 60)
print("STEP 5: Component Value Ranges Across All Timesteps")
print("-" * 60)

comp_mins = [float('inf')] * K_COMPONENTS
comp_maxs = [float('-inf')] * K_COMPONENTS

for df in fields:
    for c in range(K_COMPONENTS):
        for val in df.field.data[c]:
            if val < comp_mins[c]:
                comp_mins[c] = val
            if val > comp_maxs[c]:
                comp_maxs[c] = val

for c in range(K_COMPONENTS):
    print(f"  {COMPONENTS[c]:>15s}: "
          f"[{comp_mins[c]:>10.2f}, {comp_maxs[c]:>10.2f}]")

# --- Step 6: Temporal continuity ---
print("\n" + "-" * 60)
print("STEP 6: Temporal Continuity")
print("-" * 60)

if len(fields) >= 2:
    gaps = []
    for i in range(1, len(fields)):
        dt = fields[i].timestamp - fields[i-1].timestamp
        hours = dt.total_seconds() / 3600
        if abs(hours - 1.0) > 0.1:
            gaps.append((fields[i-1].timestamp, fields[i].timestamp, hours))

    if gaps:
        print(f"  WARNING: {len(gaps)} gaps in hourly sequence:")
        for g in gaps[:5]:
            print(f"    {g[0]} → {g[1]} ({g[2]:.1f} hours)")
    else:
        print(f"  Contiguous: {len(fields)} consecutive hours, no gaps")

    print(f"  First: {fields[0].timestamp} UTC")
    print(f"  Last:  {fields[-1].timestamp} UTC")

# --- Summary ---
print("\n" + "=" * 60)
print("PHASE 0 SUMMARY")
print("=" * 60)
print(f"  Admissible timesteps: {len(fields)}")
print(f"  Station count range:  "
      f"{min(df.topology.n_stations for df in fields)}–"
      f"{max(df.topology.n_stations for df in fields)}")
print(f"  Spatial edges range:  "
      f"{min(len(set((min(i,j),max(i,j)) for i,j in df.topology.spatial_edges)) for df in fields)}–"
      f"{max(len(set((min(i,j),max(i,j)) for i,j in df.topology.spatial_edges)) for df in fields)}")
print(f"  Component pairs:      "
      f"{len(fields[0].topology.component_pairs)}")
print(f"  All connected:        "
      f"{all(df.topology.is_connected for df in fields)}")

ok = (len(fields) > 48 and
      all(df.topology.is_connected for df in fields) and
      min(df.topology.n_stations for df in fields) >= 5)

print(f"\n  Phase 0 status: {'PASS' if ok else 'REVIEW NEEDED'}")
if ok:
    print("  Ready for Phase 1: operator application")
