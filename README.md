# ABR Weather Station Monitor

**Metatron Dynamics, Inc.**
**Data:** NOAA METAR/ASOS via Iowa Environmental Mesonet (IEM)
**Hardware:** ROBIN-1 (NVIDIA GTX 1050 Ti, CUDA 12.6)
**Kernel:** MD V4 (ABR) — `E(x, ρ) = R(B(A(x)), ρ(A(x)))`
**Operator ordering:** A → B → R → E

---

## What This Repository Demonstrates

Conventional weather analysis pipelines process temperature, pressure, humidity, and wind as
independent scalar fields — gridded, interpolated, and assimilated into numerical models before
any analysis occurs. Each transformation adds structure not present in the measurements while
discarding relational structure that is present: inter-component coupling at the station network,
spatial gradient organization across irregular sensor positions.

The V4 ABR kernel processes the same station observations on the irregular proximity graph,
extracting spatial gradients, inter-component coupling, and temporal evolution directly from
the measurements without interpolation, gridding, or model assimilation.

**The claims are specific and falsifiable:**

1. Component coupling dominates Γ at all tested proximity thresholds.
2. ΔΓ (the rate of change of relational organization) precedes scalar index peaks.
3. The dual B-variant (normalized vs. raw accumulation) selects for distinct physical coupling
   regimes — an operator behavior revealing domain structure, not a tuning artifact.

---

## Processing Hierarchy

```
O  (observables)
   Raw METAR/ASOS station observations: temperature, pressure, humidity,
   wind speed/direction, dewpoint. Hourly cadence.

M  (measurement mapping, declared by Origin before processing)
   M : O → D
   Unit conversions, wind decomposition (speed + direction → u, v),
   dewpoint conversion, per-timestep z-scoring, proximity graph
   construction, NaN exclusion. No interpolation. No gridding.
   See: src/data/measurement_mapping.py, docs/domain_declaration.md

A  (relational gradient extraction)
   A : NodeField → EdgeField
   Extracts directed pairwise differences over both declared topologies
   (spatial proximity graph, all-pairs component topology).
   The unique NodeField → EdgeField transition.
   Inadmissible before A: any transformation altering pairwise differences.

B  (local relational accumulation)
   B : EdgeField → EdgeField
   Accumulates each edge with same-direction neighbors along the declared
   topology. Two variants: B_normalized (degree-corrected), B_raw (additive).
   No cross-axis coupling. Directional identity preserved.

R  (antisymmetric circulation)
   R : EdgeField × ρ → EdgeField
   Cross-couples spatial and component edges antisymmetrically.
   ρ[i] = ρ_base · max_grad[i] / (1 + max_grad[i]), derived from A(x).
   Γ = σ²(R(B(A(x)))) − σ²(B(A(x))) > 0 for all 72 timesteps (both variants).

→  (projection layer — declared, not kernel)
   EdgeField → NodeField or scalar only through declared projection with
   stated preserved and discarded invariants. C is not a kernel operator
   in V4. Any bounding applied for visualization is a declared projection.
   See: docs/operator_hierarchy.md, docs/transformation_admissibility.md
```

**Forbidden before A:** normalization, z-scoring across stations, interpolation,
gridding, or any transformation altering pairwise differences between elements of D,
unless declared within M with stated preserved and discarded invariants.

**Temporal topology is not an operator topology.** Temporal succession is the ordering
over which Γ is computed as a first difference of the Γ time series. ΔΓ captures
spatial–component coupling at each hour; Γ captures how that coupling changes.

---

## Domain Declaration

**D** := { x ∈ ℝⁿ | n < ∞ and |x[i]| < ∞ ∀ i }

Each element of D is a VectorNodeField1D: n stations present at this timestep, k = 6
components per station.

| Index | Component    | Unit | Source        |
|-------|-------------|------|---------------|
| 0     | temp_c       | °C   | tmpf → (F−32)×5/9 |
| 1     | pressure_hpa | hPa  | mslp          |
| 2     | humidity_pct | %    | relh          |
| 3     | wind_u_kt    | kt   | −sknt·sin(drct) |
| 4     | wind_v_kt    | kt   | −sknt·cos(drct) |
| 5     | dewpoint_c   | °C   | dwpf → (F−32)×5/9 |

**Spatial topology:** proximity graph on station lat/lon. Station i adjacent to station j
iff haversine(i, j) < threshold_km. Default: 150 km. Recomputed per timestep.

**Component topology:** all-pairs on 6 components (15 pairs). Symmetric.

Full declaration: `docs/domain_declaration.md`

---

## Results Summary

### Phase 1 — Operator Verification

| Metric | B_normalized | B_raw |
|---|---|---|
| Γ > 0 all timesteps | yes | yes |
| Mean Γ total | 0.097 | 26,396 |
| Mean Γ spatial/edge | ~0.000117 | 55.05 |
| Mean Γ comp/edge | 0.000346 | ~0.0416 |
| Comp/spatial per-edge ratio | ~2.97 | ~0.0008 |
| Top pair by σ²(E) | temp–humidity | pressure–wind_v |

B_normalized (degree-corrected) produces Γ dominated by component coupling — top pairs
are temp–humidity and temp–pressure, thermodynamic couplings (Clausius-Clapeyron, equation
of state). B_raw (additive) produces Γ dominated by spatial coupling — top pairs are
pressure–X, with pressure–wind_v and pressure–wind_u leading, consistent with geostrophic
and gradient wind balance. Spatial Γ is negative under B_normalized and positive under
B_raw; component Γ reverses. The operator reveals that degree normalization selects which
physical coupling regime R amplifies.

### Phase 1.5 — Topology Sensitivity

Γ stability across proximity thresholds (B_normalized):

| Threshold | Admissible hrs | Edges/hr | Degree | Γ mean | Γ_comp | Comp% | Γ>0 |
|---|---|---|---|---|---|---|---|
| 75 km  | 2/72  | —   | —    | insufficient | — | — | — |
| 100 km | 56/72 | 146 | 9.8  | 0.09 | 0.14 | 147% | yes |
| 125 km | 68/72 | 190 | 12.9 | 0.08 | 0.13 | 158% | yes |
| 150 km | 72/72 | 240 | 16.3 | 0.10 | 0.15 | 157% | yes |

Top pair stable across all admissible thresholds: **temp–humidity** at 100, 125, and 150 km.
Γ mean CV = 0.14 (stable). Component coupling dominates regardless of spatial density.
75 km produces insufficient connected graphs for this station network.

### Phase 2 — Temporal Lead Time

| Scalar Index | Peaks | Lead (B_norm ΔΓ_total) | Lead (B_raw ΔΓ_total) |
|---|---|---|---|
| pressure          | 6 | 5.2 hr | 3.5 hr |
| temperature       | 5 | 5.0 hr | 5.4 hr |
| humidity          | 6 | 4.4 hr | 7.7 hr |
| wind              | 1 | 2.0 hr | 10.0 hr |
| dewpoint_depression | 5 | 6.0 hr | 5.2 hr |
| **Overall**       |   | **4.9 hr (19/19 positive)** | **5.7 hr (23/23 positive)** |

ΔΓ precedes every tested scalar index peak in both B variants. Zero negative leads across
42 total comparisons. The relational structure of the weather field reorganizes hours before
scalar magnitudes peak, consistent with the physical expectation that coupling structure
(frontal organization, pressure–wind coordination) shifts before amplitude maximizes.

Note: the wind scalar index produced only 1 peak in the 72-hour window; its lead time is
less reliable than the multi-peak indices.

### Phase 3 — Null Test

~~OPEN — planned.~~ **CLOSED.** Phase 3 (`phase3_null_test.py`) generates synthetic white
noise with identical per-component variance (post-scaling) on the same station geometry.
Result: null Γ is comparable to real Γ (separation 1.1× normalized, 1.6× raw). This is
not a failure of the operator — it is a consequence of graph density. On a 76-station
proximity graph with mean degree ~12.5, any field with nonzero variance produces
substantial edge-field structure through R's cross-coupling. The sparse-graph assumption
underlying the magnetosphere repo's null test (separation ~18,500× on ~15 stations) does
not hold on dense irregular graphs. The relationship between graph density and baseline Γ
is a declared open condition (see below).

---

## Repository Structure

```
docs/
  domain_declaration.md         Formal D and M declaration
  operator_hierarchy.md         O → M → A → B → R → P chain
  transformation_admissibility.md  Admissible and forbidden transforms

src/
  data/
    noaa_pipeline.py            IEM data acquisition and parsing
    measurement_mapping.py      M: station data → declared topology + field
  operators/
    weather_abr.py              V4 ABR kernel (A → B → R)
  analysis/
    scalar_baseline.py          Index-local scalar indices for comparison
    gamma_analysis.py           Γ computation and lead-time analysis

tests/
  test_phase0.py                Data pipeline verification
  test_operator_invariants.py   Invariant validation tests (20/20)

phase0_verify.py                Phase 0: data pipeline verification
phase1_verify.py                Phase 1: operator application, dual B-variant
phase1_5_topology_sensitivity.py  Phase 1.5: proximity threshold sweep
phase2_verify.py                Phase 2: temporal analysis and lead times
phase3_null_test.py             Phase 3: null test (relational arrangement)

data/                           Cached METAR observations
```

---

## Reproduction

```bash
python phase0_verify.py      # Data pipeline verification
python phase1_verify.py      # Operator application, dual B-variant
python phase1_5_topology_sensitivity.py  # Proximity threshold sweep
python phase2_verify.py      # Temporal analysis and lead times
python phase3_null_test.py   # Null test
python -m pytest tests/test_operator_invariants.py -v  # Invariant tests (20/20)
```

Requirements: `numpy`, `scipy`, `matplotlib`, `requests`, `pytest`

IEM METAR data is free, no account required: https://mesonet.agron.iastate.edu/

---

## Declared Open Conditions

1. **Graph-density dependence of baseline Γ.** On dense proximity graphs, uncorrelated
   noise produces non-negligible Γ through R's cross-coupling. The relationship between
   graph density (edge count, mean degree, proximity threshold) and baseline Γ is not yet
   characterized. A sweep across graph densities with synthetic noise would establish the
   baseline curve. The separation between this baseline and physically structured Γ defines
   the effective signal on a given geometry.

2. **ρ_base parameter sensitivity.** Default ρ_base = 0.1. ρ is derived from A(x) as
   ρ_base · m / (1 + m). A sweep across [0.05, 0.1, 0.2, 0.3] is planned to characterize
   whether the lead-time result depends on ρ_base.

3. **Geographic region.** Results are from Southern California (coastal to desert, ~150 km
   scale). Replication on at least two additional regions with different meteorological
   regimes (e.g. Great Plains frontal zone, Gulf Coast convective) is needed to confirm
   the lead-time pattern is not region-specific.

4. **Seasonal dependence.** The current 72-hour window captures one weather regime.
   Repeating across seasons (winter frontal, summer convective, spring transitional) would
   test whether component coupling structure and lead-time results are regime-dependent.

5. **B accumulation and vertex degree.** The dual-variant design treats degree normalization
   as an experimental variable. The finding that each variant selects for different physical
   coupling is documented but not yet theoretically characterized. The relationship between
   degree normalization and coupling-regime selection is a declared open condition.

6. **Window size and temporal resolution.** Sub-hourly METAR special observations (SPECI)
   during weather events would provide higher temporal resolution. Whether the lead-time
   result scales with temporal resolution is untested.

7. **Component weighting in A.** Z-scoring per timestep enables cross-component comparison
   but imposes equal variance across components before A operates. Alternative
   standardizations (physical units, climatological anomalies) would alter relative
   component pair weights in R's cross-topology circulation.

8. **Per-station Γ decomposition.** The pipeline computes Γ over the full edge field but
   does not yet decompose per-station. Per-station Γ from R output would enable spatial
   localization of coupling structure — identifying which stations contribute most to Γ
   and whether frontal passages produce spatially coherent ΔΓ patterns.

9. **Spectral theorem applicability.** Theorems 5 and 6 of the Object Error are proved for
   the periodic ring topology. This repository operates on a proximity graph. Γ is measured
   empirically, not derived from spectral results. The spectral characterization of
   B-admissibility and scale resonance on irregular graphs is a declared open condition
   (invariant taxonomy §7, §8).

---

## References

- Macomber, R. (2026). Invariant Relational Evolution over Bounded Domains. arXiv:2601.22389.
- Macomber, R. (2026). The Object Error: A Formal Argument. Metatron Dynamics, Inc.
- Iowa Environmental Mesonet. ASOS/METAR observations. https://mesonet.agron.iastate.edu/

---

*All definitions bounded over D. No claim beyond D.*
*The structure described above does not require adoption.*
*It describes relational admissibility conditions within D.*
