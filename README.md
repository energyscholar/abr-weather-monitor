# ABR Weather Station Monitor

**Metatron Dynamics, Inc.**
**Data:** NOAA METAR/ASOS via Iowa Environmental Mesonet (IEM)
**Hardware:** ROBIN-1 (NVIDIA GTX 1050 Ti, CUDA 12.6)

---

## What This Repository Demonstrates

Conventional weather analysis pipelines process temperature, pressure, humidity, and wind as independent scalar fields — gridded, interpolated, and assimilated into numerical models before any analysis occurs. Each transformation adds structure not present in the measurements (uniform grids, spectral bases, parameterized physics) while discarding relational structure that is present (inter-component coupling at the station network, spatial gradient organization across irregular sensor positions).

The ABR operator framework processes the same station observations on the irregular proximity graph, extracting relational structure — spatial gradients, inter-component coupling, and temporal evolution — directly from the measurements without interpolation, gridding, or model assimilation.

This repository applies the V4 ABR kernel to 72 hours of live METAR observations from Southern California stations and quantifies the relational structure present in the raw observations.

**The claims are specific and falsifiable:**
1. Component coupling dominates Γ at all tested proximity thresholds.
2. ΔΓ (the rate of change of relational organization) precedes scalar index peaks.
3. The dual B-variant (normalized vs raw accumulation) selects for distinct physical coupling regimes.

---

## Kernel Version and Operator Declaration

This repository implements **MD V4 (ABR)** — the multi-topology generalization of the relational kernel.

**Kernel composition:** `E(x, ρ) = R(B(A(x)), ρ(A(x)))`
**Operator ordering:** A → B → R → E

C is not a kernel operator in V4. It is a declared projection applied at the application layer with stated preserved and discarded invariants. On the 6-component weather field, C's shared denominator would suppress quiet component pairs (e.g. precip during dry periods) when another pair dominates — destroying the cross-topology coupling that R produces and that Γ measures.

Γ is computed on the unbounded edge field output of R. Any bounding applied for visualization or downstream use is a declared projection, not a kernel operation.

For the formal argument establishing V4 vs V3, see the kernel README §V4 and Object Error §8.7.

---

## Results Summary

### Phase 1 — Operator Verification

| Metric | B_normalized | B_raw |
|---|---|---|
| Γ > 0 all timesteps | yes | yes |
| Mean Γ total | 0.097 | 26,396 |
| Mean Γ spatial/edge | −0.000117 | 55.05 |
| Mean Γ comp/edge | 0.000346 | −0.0416 |
| Comp/spatial per-edge ratio | −2.97 | −0.0008 |
| Top pair by σ²(E) | temp — humidity | pressure — wind_v |

The dual B-variant reveals distinct physical regimes. B_normalized (degree-corrected accumulation) produces Γ dominated by component coupling — the top pairs are temp–humidity and temp–pressure, thermodynamic couplings (Clausius-Clapeyron, equation of state). B_raw (additive accumulation) produces Γ dominated by spatial coupling — the top pairs are all pressure–X, with pressure–wind_v and pressure–wind_u leading, consistent with geostrophic/gradient wind balance where pressure gradients drive wind fields. Spatial Γ is negative under B_normalized and positive under B_raw; component Γ reverses. This is not a tuning artifact — it is the operator revealing that degree normalization selects which physical coupling regime R amplifies.

### Phase 1.5 — Topology Sensitivity

Γ stability across proximity thresholds (B_normalized):

| Threshold | Admissible hrs | Edges/hr | Degree | Γ mean | Γ_comp | Comp% | Γ>0 |
|---|---|---|---|---|---|---|---|
| 75 km | 2/72 | — | — | insufficient | — | — | — |
| 100 km | 56/72 | 146 | 9.8 | 0.09 | 0.14 | 147% | yes |
| 125 km | 68/72 | 190 | 12.9 | 0.08 | 0.13 | 158% | yes |
| 150 km | 72/72 | 240 | 16.3 | 0.10 | 0.15 | 157% | yes |

Top pair stable across all thresholds: **temp–humidity** at 100, 125, and 150 km. Γ mean CV = 0.14 (stable). 75 km produces insufficient connected graphs (2/72 admissible) — the station density in this region cannot support that threshold. Component coupling dominates regardless of spatial density.

### Phase 2 — Temporal Lead Time

| Scalar Index | Peaks | Lead (B_norm ΔΓ_total) | Lead (B_raw ΔΓ_total) |
|---|---|---|---|
| pressure | 6 | 5.2 hr | 3.5 hr |
| temperature | 5 | 5.0 hr | 5.4 hr |
| humidity | 6 | 4.4 hr | 7.7 hr |
| wind | 1 | 2.0 hr | 10.0 hr |
| dewpoint_depression | 5 | 6.0 hr | 5.2 hr |
| **Overall** | | **4.9 hr (19/19 positive)** | **5.7 hr (23/23 positive)** |

ΔΓ — the rate of change of cross-topology relational organization — peaks before every tested scalar index peak in both B variants. Zero negative leads across 42 total comparisons. The relational structure of the weather field reorganizes hours before scalar magnitudes peak. This is consistent with the physical expectation that coupling structure (frontal organization, pressure-wind coordination) shifts before amplitude maximizes.

Note: the wind scalar index produced only 1 peak in the 72-hour window, making its lead time (2.0 hr / 10.0 hr) less reliable than the multi-peak indices.

---

## The 3-Topology Structure

```
Raw station data (METAR/ASOS, hourly, 6 components)
  → Declare spatial topology (proximity graph, 150 km default)
  → Declare component topology (all-pairs on 6 components → 15 pairs)
  → Per-timestep operator application:
      → Operator A: extract 2-topology edge field (spatial × component)
      → Operator B: accumulate along each topology
      → Operator R: cross-couple between topologies
      → Γ = σ²(R∘B∘A) − σ²(B∘A)
  → Temporal analysis: ΔΓ = Γ(t) − Γ(t−1)
```

**Components (K=6):** temperature, pressure, humidity, wind_u, wind_v, precipitation

**Components (K=6):** temperature, pressure, humidity, wind_u, wind_v, dewpoint

**Component pairs (15):** all pairwise couplings. Physically load-bearing pairs include temp–humidity (Clausius-Clapeyron, top pair under B_normalized at all thresholds), temp–pressure (equation of state), pressure–wind_u/wind_v (gradient wind relation, top pairs under B_raw), and humidity–wind (moisture advection). These operate at different spatial and temporal scales. R treats them symmetrically through cross-topology circulation; the dual B-variant selects which regime dominates.

**Temporal architecture:** ABR operators are applied per-timestep to the spatial × component edge field. Temporal succession is not an operator topology — it is the ordering over which ΔΓ is computed as a first difference of the Γ time series. This differs from the magnetosphere repo's simultaneous 3-topology R (spatial × component × temporal in a single operator pass). Per-timestep Γ captures spatial × component coupling at each hour; ΔΓ captures how that coupling changes. The lead-time result measures when relational reorganization occurs relative to scalar peaks.

No interpolation. No gridding. No model assimilation. No spectral decomposition. The operators process relational structure where the atmosphere intersects the sensors. Domain D is the station network itself. No claim is made about the atmosphere between stations.

---

## Data

Raw METAR/ASOS observations from Iowa Environmental Mesonet (IEM). No API key required.

**Pre-A steps within M:**
- Station selection: California stations within bounding box (33.5°–36.0°N, 117.0°–121.0°W)
- Temporal binning: hourly snapshots (METAR reporting cadence)
- NaN exclusion: stations missing any component at a given hour are excluded from that timestep's topology
- Wind decomposition: wind speed + direction → wind_u, wind_v (trigonometric, lossless)
- Unit standardization: each component z-scored per timestep to enable cross-component comparison in A

No gridding. No model analysis fields. No reanalysis products.

---

## Repository Structure

```
data/                           — Cached METAR observations

src/
  data/
    noaa_pipeline.py            — IEM data acquisition and parsing
    measurement_mapping.py      — M: station data → declared topology + field
  operators/
    weather_abr.py              — V4 ABR kernel (A → B → R → Γ)
  analysis/
    scalar_baseline.py          — Index-local scalar indices for comparison
    gamma_analysis.py           — ΔΓ computation and lead-time analysis

tests/                          — Operator and pipeline tests

phase0_verify.py                — Phase 0: data pipeline verification
phase1_verify.py                — Phase 1: operator application, dual B-variant
phase1_5_topology_sensitivity.py — Phase 1.5: proximity threshold sweep
phase2_verify.py                — Phase 2: temporal analysis and lead times
```

---

## Reproduction

```bash
# Phase 0: Data pipeline verification
python phase0_verify.py

# Phase 1: Operator application (both B variants)
python phase1_verify.py

# Phase 1.5: Topology sensitivity sweep
python phase1_5_topology_sensitivity.py

# Phase 2: Temporal analysis and lead times
python phase2_verify.py
```

Requirements: numpy, scipy, matplotlib, requests.

IEM METAR data is free and requires no account: https://mesonet.agron.iastate.edu/

---

## Declared Open Conditions

1. **Null test.** Synthetic white noise with identical marginal variance per component but destroyed relational arrangement should produce Γ ≈ 0. The magnetosphere repo's Phase 4.1 null test confirms this for the same operator architecture on different data. A weather-specific null test using the same station geometry is planned but not yet implemented.

2. **ρ_base parameter sensitivity.** Default ρ_base = 0.1. ρ is derived from A(x) — the local relational gradient magnitude — bounded by ρ_base × m / (1 + m). A sweep across [0.05, 0.1, 0.2, 0.3] is planned to characterize whether the lead-time result depends on ρ_base.

3. **Geographic region.** These results are from Southern California (coastal to desert, ~150 km scale). The comparison should be repeated on at least two additional regions with different meteorological regimes (e.g. Great Plains frontal zone, Gulf Coast convective) to confirm the lead-time pattern is not region-specific.

4. **Seasonal dependence.** The current 72-hour window captures one weather regime. Repeating across seasons (winter frontal, summer convective, spring transitional) would test whether the component coupling structure and lead-time results are regime-dependent.

5. **B accumulation and vertex degree.** B_raw sums without degree normalization; B_normalized divides by vertex degree. The dual-variant design treats this as an experimental variable rather than a parameter choice. The finding that each variant selects for different physical coupling is documented but not yet theoretically characterized. The relationship between degree normalization and coupling-regime selection is a declared open condition.

6. **Window size and temporal resolution.** The current pipeline uses hourly METAR observations over 72 hours. Sub-hourly METAR special observations (SPECI) during weather events would provide higher temporal resolution. Whether the lead-time result scales with temporal resolution is untested.

7. **Component weighting in A.** Z-scoring per timestep enables cross-component comparison but imposes equal variance across components before A operates. Alternative standardizations (physical units, climatological anomalies) would alter the relative weight of component pairs in R's cross-topology circulation. The choice is declared; alternatives are not yet tested.

8. **Per-station Γ decomposition.** The pipeline computes Γ over the full edge field but does not yet decompose per-station. Adding per-station σ² from R output would enable spatial localization of coupling structure — identifying which stations contribute most to Γ and whether frontal passages produce spatially coherent ΔΓ patterns.

9. **Spectral theorem applicability.** Theorems 5 and 6 of the Object Error are proved for the periodic ring topology. This repository operates on a proximity graph. Γ is measured empirically, not derived from spectral results. The spectral characterization of B-admissibility and scale resonance on irregular graphs is a declared open condition (invariant taxonomy §7, §8).

---

## References

- Macomber, R. (2026). Invariant Relational Evolution over Bounded Domains. arXiv:2601.22389.
- Macomber, R. (2026). The Object Error: A Formal Argument. Metatron Dynamics, Inc.
- Iowa Environmental Mesonet. ASOS/METAR observations. https://mesonet.agron.iastate.edu/

---

*All definitions bounded over D. No claim beyond D. The structure described above does not require adoption. It describes relational admissibility conditions within D.*
