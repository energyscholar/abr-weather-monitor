# Domain Declaration — ABR Weather Station Monitor

## Domain

D := { x ∈ ℝⁿ | n < ∞ and |x[i]| < ∞ ∀ i }

Each element of D is a VectorNodeField1D:
- n cells (stations present at this timestep)
- k=6 components per cell

## Component Vector (declared units)

| Index | Component    | Unit | Source Field |
|-------|-------------|------|-------------|
| 0     | temp_c       | °C   | tmpf → (F-32)*5/9 |
| 1     | pressure_hpa | hPa  | mslp (mbar = hPa) |
| 2     | humidity_pct | %    | relh |
| 3     | wind_u_kt    | kt   | -sknt * sin(drct) |
| 4     | wind_v_kt    | kt   | -sknt * cos(drct) |
| 5     | precip_mm    | mm   | p01i * 25.4 |

### Wind Direction Transformation

Declared within M. Transforms (speed, direction) to (u, v).

Preserved: wind speed magnitude, direction information, linear differentiability.
Discarded: circular angular representation.

## Operator Topologies (internal to E)

### Spatial Topology
Proximity graph on station lat/lon positions.
Station i adjacent to station j iff haversine(i, j) < threshold_km.
Symmetric. Declared before processing. Recomputed per timestep
over stations present (addresses topology drift from missing data).

### Component Topology
All-pairs on 6 components (15 pairs). Symmetric.
Declared before processing.

Alternative: ring topology on components (6 pairs).
Origin declares which.

## Observational Evolution Ordering (NOT an operator topology)

Forward-only succession of hourly snapshots.
Not used inside E. Used at analysis layer only.
Each e(t) = E(x(t), rho) is evaluated independently.
The temporal sequence {e(t)} is examined for lead time
at the analysis layer.

## Missing Data Protocol

If a station is missing any component at timestep t,
that station is excluded from the field at timestep t.
Topology is recomputed per timestep over stations present.

Declared: preserves completeness of component vectors.
Discarded: stations with partial observations.

## Pre-Operator Transformation Constraint

Unit conversions (°F→°C, inches→mm, direction→u/v) are
declared within M. No normalization, standardization, or
statistical scaling is applied.

Admissible pre-A: uniform shift (unit choice), uniform
scaling (unit choice). All applied within M.

## Declared Open Conditions

1. Proximity threshold (km) — declared by Origin per session
2. Component topology — all_pairs vs ring, declared by Origin
3. rho_base — declared by Origin (starting: 0.1)
4. Hourly binning: closest-to-hour obs retained.
   Preserved: single representative observation per station-hour.
   Discarded: sub-hourly variation.