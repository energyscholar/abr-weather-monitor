# Operator Hierarchy — ABR Weather Station Monitor

**Metatron Dynamics, Inc.**
**Repository:** abr-weather-monitor
**Kernel:** MD V4 (ABR) — `E(x, ρ) = R(B(A(x)), ρ(A(x)))`

---

## Status

This document defines the complete processing hierarchy for the
ABR weather station monitor, from raw observables through operator
composition to declared projection. Each stage is linked to its
kernel-level definition and its domain-specific instantiation.

All definitions are bounded over D. No claim is made beyond D.

---

## The Hierarchy

```
O  →  M  →  A  →  B  →  R  →  P
│     │     │     │     │     │
│     │     │     │     │     └─ Declared Projection (EdgeField → scalar/NodeField)
│     │     │     │     └─ Antisymmetric Circulation (EdgeField → EdgeField)
│     │     │     └─ Local Relational Accumulation (EdgeField → EdgeField)
│     │     └─ Relational Gradient Extraction (NodeField → EdgeField)
│     └─ Measurement Mapping (O → D)
└─ Observables (raw METAR/ASOS)
```

Each arrow is a declared transition. No implicit transformations
exist between stages. The hierarchy defines a compositional
operator chain in which each stage establishes the admissibility
conditions required by the next. No stage may be omitted or
reordered.

---

## O — Observables

### Kernel Definition

O is the space of raw observational data before any processing.
Observables are produced by conditions C that are outside D by
construction (Object Error §1.2). The kernel operates on M(o)
only. Conditions that produce observables are not represented
within D.

### Domain Instantiation

NOAA METAR/ASOS observations from Southern California stations,
acquired via Iowa Environmental Mesonet (IEM). Hourly cadence.

Raw fields per station report:
- `tmpf` — temperature (°F)
- `dwpf` — dewpoint (°F)
- `mslp` — mean sea-level pressure (hPa)
- `relh` — relative humidity (%)
- `sknt` — wind speed (kt)
- `drct` — wind direction (°)
- `lat`, `lon` — station coordinates

These are the observables. They arrive in mixed units, with
missing values, variable station availability per hour, and
no declared topology.

### Invariants at This Stage

None. Observables are outside D. No operator-level invariant
applies to O. The transition from O to D occurs entirely
within M.

---

## M — Measurement Mapping

### Kernel Definition

M : O → D is the declared mapping from observables to elements
of D (Object Error §1.2, Origin-Declared Topology §5).

M is responsible for:
- Embedding irregular observations into D under a declared topology
- Specifying coordinate systems and units
- Performing any interpolation or transformation, with declared
  preserved and discarded invariants
- Producing a VectorNodeField1D that satisfies the input
  requirements of operator A

M is declared by Origin before processing begins. All choices
within M — unit conversions, component selection, topology
construction, missing-data handling — are Origin declarations,
not algorithmic defaults.

### Domain Instantiation

M in this repository performs the following declared transformations:

**Unit conversions:**
- tmpf → temp_c: (F − 32) × 5/9
- dwpf → dewpoint_c: (F − 32) × 5/9
- mslp → pressure_hpa: identity (already hPa)
- relh → humidity_pct: identity (already %)

**Wind decomposition:**
- (sknt, drct) → wind_u_kt: −sknt · sin(drct · π/180)
- (sknt, drct) → wind_v_kt: −sknt · cos(drct · π/180)

This is a declared non-injective transformation within M.
Preserved: horizontal wind vector components.
Discarded: the original speed/direction representation. The
decomposition is injective on the wind vector itself (u, v
determine speed and direction uniquely) but non-injective on
the input pair when speed = 0 (all directions map to u = v = 0).
This is declared.

**Per-timestep z-scoring:**
Each component is z-scored across all stations present at that
timestep. This is a declared transformation within M.
Preserved: pairwise difference ratios within each component at
each timestep (z-scoring is a uniform shift + uniform scaling,
both admissible under the pre-operator transformation constraint).
Discarded: absolute magnitudes and cross-timestep comparability
of raw values.

Z-scoring is admissible prior to A because it preserves pairwise
differences up to a uniform scale factor per component per
timestep. It does not alter the relational content that A extracts
(Invariant Taxonomy §1). It enables cross-component comparison
by placing all components at equal variance before A operates.

**Missing-data handling:**
Stations with any NaN component at a given timestep are excluded
from D for that timestep. No imputation. No interpolation.
Preserved: all pairwise differences among included stations are
determined by actual observations.
Discarded: any relational information involving excluded stations.

**Spatial topology construction:**
Proximity graph on station lat/lon. Station i adjacent to station j
iff haversine(i, j) < threshold_km. Default: 150 km. Recomputed
per timestep (because station availability varies).
Declared: the topology is Origin-declared, not inferred from the
data values. It is declared from the spatial positions of the
stations, which are observables mapped through M.

**Component topology construction:**
All-pairs on k = 6 components (15 pairs). Symmetric. Declared
by Origin as part of M.

**Output:**
VectorNodeField1D with n stations (variable per timestep), k = 6
components per station.

### Invariants Established at This Stage

After M, the field is in D. From this point forward:
- Relational content invariance holds (Invariant Taxonomy §1)
- Relational determinacy holds (Invariant Taxonomy §10)
- The pre-operator transformation constraint applies: no further
  transformation may alter pairwise differences before A

### What M Does Not Do

M performs no interpolation, no gridding, no model assimilation,
and no spatial smoothing. The station observations enter A on the
irregular proximity graph at the positions where they were measured.
The declared topology (proximity graph) satisfies the admissibility
conditions of Origin-Declared Topology §3.1 for operator A: every
station has a deterministic neighbor set under the proximity
threshold, and no station has an undeclared boundary (stations
with insufficient neighbors are included with their actual
neighbor count; isolated stations with zero neighbors within
the threshold are excluded from the edge field).

### Implementation

`src/data/noaa_pipeline.py` — IEM data acquisition and parsing
`src/data/measurement_mapping.py` — M: all transformations above

---

## A — Relational Gradient Extraction

### Kernel Definition

A : NodeField → EdgeField

A extracts directed pairwise differences over all declared
topologies (Object Error §8.2). It is the unique transition from
NodeField to EdgeField — the point at which the representation
shifts from per-entity values to per-relation values.

A is not index-local: A(x)[i] depends on two indices (Object
Error §8.2). A's output determines the relational content of
the field (Object Error, Proposition 2).

### Domain Instantiation

A produces edges over both declared topologies:

**Spatial edges:** For each component c and each adjacent station
pair (i, j) in the proximity graph:
```
spatial_edge[c][(i,j)] = x[c][i] − x[c][j]
```
One directed edge per adjacency per component. Edge count =
(number of adjacencies) × k.

**Component edges:** For each declared component pair (a, b) and
each station i:
```
comp_edge[(a,b)][i] = x[a][i] − x[b][i]
```
One edge per component pair per station. Edge count =
(number of component pairs) × n.

A's output is a MultiTopoEdgeField1D (operators_V4.rs §6)
containing both spatial and component edge arrays.

### Invariants Established at This Stage

- Representation type discipline: the field is now an EdgeField.
  All subsequent operators (B, R) must operate EdgeField →
  EdgeField. No return to NodeField without declared projection
  (Invariant Taxonomy §5).
- Relational content invariance: A(x) = A(y) iff x ~_τ y
  (Invariant Taxonomy §1). The edge field is a complete invariant
  of the relational equivalence class.
- Operator ordering: A is the first operator. Nothing precedes A
  in the kernel composition except M (Invariant Taxonomy §6).

### What A Discards

The absolute component of the field — the per-component mean
across stations — is annihilated by A. This is by construction:
the mean carries no relational information (Object Error §2.1,
Axiom 1). The z-scoring in M already centers each component;
A's differencing extracts the relational structure that z-scoring
preserved.

### Implementation

`src/operators/weather_abr.py` — `compute_edges()`

---

## B — Local Relational Accumulation

### Kernel Definition

B : EdgeField → EdgeField

B accumulates each directed edge with the same-direction edge
at the next cell along the declared topology (Object Error §8.2).
B extends relational reach while remaining in the edge
representation. B is not index-local: B(e)[i] depends on edges
at i and at its neighbor.

### Domain Instantiation

Two variants are implemented, both producing EdgeField → EdgeField:

**B_normalized (degree-corrected):**
```
B(e)[i] = (1/|N(i)|) · Σ_{j ∈ N(i)} e[j]
```
where N(i) is the neighbor set of edge i along the declared
topology. Degree correction normalizes by neighbor count,
preventing high-degree nodes from dominating accumulation.

**B_raw (additive):**
```
B(e)[i] = Σ_{j ∈ N(i)} e[j]
```
Additive accumulation without degree correction. Preserves
magnitude differences due to connectivity.

Both variants are departures from the canonical ring-topology B
defined in the kernel (operators_V4.rs), which sums exactly two
adjacent edges. On an irregular graph, the neighbor count varies.
The two variants represent different declared choices about how
to generalize B's accumulation to irregular topology.

**Experimental finding:** The two variants select for different
physical coupling regimes:
- B_normalized → Γ dominated by component coupling
  (thermodynamic: temp–humidity, temp–pressure)
- B_raw → Γ dominated by spatial coupling
  (dynamic: pressure–wind_v, pressure–wind_u)

This is not a tuning result. The observed coupling-regime
differences are consequences of the declared accumulation rule
under the tested topology and dataset: degree normalization
determines whether R's cross-coupling amplifies thermodynamic
or dynamic couplings on this station geometry.

### Invariants at This Stage

- Representation type: still EdgeField (Invariant Taxonomy §5)
- Operator ordering: B follows A (Invariant Taxonomy §6)
- Edge sign structure: preserved by B (additive accumulation
  does not alter sign) (Invariant Taxonomy §4)
- B-admissible spectral concentration: on the ring topology,
  B concentrates energy at low-frequency modes (Invariant
  Taxonomy §7). On the irregular proximity graph, the spectral
  characterization is a declared open condition (Invariant
  Taxonomy §7, "On Irregular Graphs")

### Declared Open Conditions

- The relationship between degree normalization and coupling-regime
  selection is documented empirically but not yet theoretically
  characterized (README, Open Condition #5).
- The spectral properties of B on the irregular proximity graph
  are not formally established (Invariant Taxonomy §7).

### Implementation

`src/operators/weather_abr.py` — `accumulate_edges()`

---

## R — Antisymmetric Circulation

### Kernel Definition

R : EdgeField × ρ → EdgeField

R cross-couples edges between topologies antisymmetrically
(Object Error §8.2, operators_V4.rs §6). R's coupling is:
- Local: each edge receives contribution from its declared
  neighbors only
- Antisymmetric: the coupling term is a difference of neighbor
  edges, not a sum
- Additive: coupling is added to the existing edge value

R is not index-local: R(e)[i] depends on neighboring edges.

### Domain Instantiation

R in this repository performs cross-topology circulation as
defined in the V4 kernel (operators_V4.rs, multi_1d module):

**Spatial edges receive component-edge asymmetry:**
For each component pair (a, b) and each station i, the spatial
edges for components a and b receive ±ρ times the spatial
asymmetry of the component edge for pair (a, b).

**Component edges receive spatial-edge asymmetry:**
For each component pair (a, b) and each station i, the component
edge receives ρ times the difference of spatial edges for
components a and b.

**ρ computation:**
```
ρ[i] = ρ_base · max_grad[i] / (1 + max_grad[i])
```
Per-cell. Derived from A(x). No aggregation. Default ρ_base = 0.1.

### The Γ Diagnostic

Γ (R-sustained circulation, Invariant Taxonomy §3) is the
difference in edge-field variance with and without R:

```
Γ = σ²(R(B(A(x)))) − σ²(B(A(x)))
```

Γ > 0 means R's antisymmetric coupling produces relational
variance beyond what B alone sustains. Γ > 0 at all 72 timesteps
for both B variants.

ΔΓ (the first difference of the Γ time series across timesteps)
is the rate of change of relational organization. Over the tested
72-hour window (Southern California, May 2026, `phase2_verify.py`),
ΔΓ peaks precede scalar index peaks — pressure, temperature,
humidity, wind, and dewpoint depression — by 4.9 hr mean
(B_normalized) and 5.7 hr mean (B_raw), with 42/42 positive
leads across all tested indices and both B variants. Full
per-index lead times are reported in README §"Phase 2 —
Temporal Lead Time".

### Invariants at This Stage

- Representation type: still EdgeField (Invariant Taxonomy §5)
- Operator ordering: R follows B (Invariant Taxonomy §6)
- R-sustained circulation: Γ > 0 for all tested timesteps
  (Invariant Taxonomy §3)
- Edge sign structure: R's additive antisymmetric coupling
  preserves signs of existing edges while introducing signed
  coupling terms (Invariant Taxonomy §4)

### Declared Open Conditions

- ρ_base sensitivity (README, Open Condition #2)
- ρ splitting: single ρ vs ρ_spatial + ρ_component
  (operators_V4.rs, Open Condition #1)

### Implementation

`src/operators/weather_abr.py` — `apply_circulation()`

---

## P — Declared Projection

### Kernel Definition

In V4, C is not a kernel operator. It is a declared projection
applied at the application layer (README kernel §"Why C Leaves
the Kernel in V4").

Any transition from EdgeField to NodeField or to scalar summary
is a projection. Every projection must declare what it preserves
and what it discards (Object Error §8.7, Invariant Taxonomy §11).

### Domain Instantiation

The projections used in this repository:

**σ² (observable variance):**
The primary diagnostic. Computes variance of the edge field.
Preserved: total relational variance magnitude.
Discarded: all spatial structure, all edge-level detail, sign
structure, directional information. σ² is a scalar summary of
the full edge field (Object Error §8.5).

**Γ (R-sustained circulation):**
Γ = σ²(E) − σ²(composition without R).
Preserved: the difference in relational variance attributable
to R's coupling.
Discarded: everything else. Γ is a scalar comparison of two
σ² values (Invariant Taxonomy §3).

**Per-component σ² decomposition:**
σ² computed separately for spatial edges per component and for
component edges per pair.
Preserved: per-type variance contribution.
Discarded: cross-type relationships, spatial structure within
each type.

**No C_per_type, C_shared, or C_spatial_only projections are
applied in this repository.** The kernel output is not bounded
before σ² is computed. The σ² diagnostic operates on unbounded
R output. This is admissible because σ² is a declared projection
with stated preserved and discarded invariants; bounding is not
required before a declared projection.

### Invariants at This Stage

- Projection declaration: every projection states what it
  preserves and discards (Invariant Taxonomy §11)
- Domain closure: not enforced by the kernel in V4. The σ²
  diagnostic does not require bounded input (Invariant
  Taxonomy §9, V4 note)

### Implementation

`src/analysis/gamma_analysis.py` — Γ computation
`src/analysis/scalar_baseline.py` — scalar index computation

---

## Hierarchy Integrity Checks

The following conditions must hold across the hierarchy:

| Condition | Stage | Check |
|---|---|---|
| No pairwise-difference-altering transform before A | M → A boundary | Pre-operator constraint (Invariant Taxonomy §1) |
| Representation is NodeField entering A | A input | Type discipline (Invariant Taxonomy §5) |
| Representation is EdgeField after A | A output | Type discipline (Invariant Taxonomy §5) |
| Representation remains EdgeField through B and R | B, R | Type discipline (Invariant Taxonomy §5) |
| Operator ordering A → B → R maintained | Full chain | Ordering invariant (Invariant Taxonomy §6) |
| No EdgeField → NodeField without declared projection | P | Projection declaration (Invariant Taxonomy §11) |
| Γ > 0 at all timesteps | R output | R-sustained circulation (Invariant Taxonomy §3) |
| All quantifiers bounded over D | All stages | Domain closure (Invariant Taxonomy §9) |

---

## Relationship to Kernel Documents

| This Document | Kernel Reference |
|---|---|
| O (observables) | Object Error §1.2 |
| M (measurement mapping) | Object Error §1.2, Origin-Declared Topology §5 |
| A (gradient extraction) | Object Error §8.2, operators_V4.rs §6 |
| B (accumulation) | Object Error §8.2, operators_V4.rs §6 |
| R (circulation) | Object Error §8.2, operators_V4.rs §6 |
| P (projection) | Object Error §8.7, Invariant Taxonomy §11 |
| Pre-A constraint | Object Error §11, operators_V4.rs §11 |
| Type discipline | Invariant Taxonomy §5, Triad §3.9.5 |
| Operator ordering | Invariant Taxonomy §6, Triad §3.9.6 |

---

*All definitions bounded over D. No claim beyond D.*
