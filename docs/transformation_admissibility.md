# Transformation Admissibility — ABR Weather Station Monitor

**Metatron Dynamics, Inc.**
**Repository:** abr-weather-monitor
**Kernel:** MD V4 (ABR) — `E(x, ρ) = R(B(A(x)), ρ(A(x)))`

---

## Status

This document specifies which transformations are admissible at
each stage of the operator hierarchy (docs/operator_hierarchy.md),
which are forbidden, and the formal basis for each determination.

Every transformation that alters the representation is classified
as admissible, conditionally admissible, or inadmissible at its
point of application. Classifications are derived from the
pre-operator transformation constraint (Object Error §11,
operators_V4.rs §11), the non-injective transformation principle
(Object Error §8.6), and the projection declaration requirement
(Object Error §8.7, Invariant Taxonomy §11).

All definitions are bounded over D. No claim is made beyond D.

---

## Governing Principle

The admissibility of a transformation depends on where it is
applied in the operator hierarchy, not on the transformation
itself in isolation.

A transformation that is inadmissible before A may be admissible
within M (as a declared part of the measurement mapping) or
after R (as a declared projection). The same mathematical
operation — z-scoring, for example — changes admissibility
status depending on its position in the compositional chain.

The formal criterion: a transformation T applied at stage S is
admissible iff T does not destroy information that a downstream
operator requires, or if T's information loss is declared with
stated preserved and discarded invariants before the downstream
operator acts.

---

## Stage 1: Within M (Before A)

### The Pre-Operator Transformation Constraint

No transformation T : D → D may be applied prior to A if T
alters pairwise differences between elements of D, unless T
is declared as part of M with stated preserved and discarded
invariants (Object Error §11, operators_V4.rs §11).

Operator A extracts relational content by computing directed
pairwise differences over declared topologies. Any transformation
that alters these differences before A operates changes the
relational content that A extracts — and therefore changes
what every downstream operator processes.

### Admissible Transformations Within M

These transformations preserve pairwise differences (up to a
declared uniform factor) and are admissible prior to A:

**Uniform shift: T(x) = x + c**

Adds a constant to all values of a component across all stations
at a timestep. Preserves all pairwise differences exactly:
T(x)[i] − T(x)[j] = x[i] − x[j] for all i, j.

Domain instance: unit conversion from Fahrenheit to Celsius.
(F − 32) × 5/9 is a uniform shift (−32) composed with a
uniform scaling (× 5/9). Both are admissible.

**Uniform scaling: T(x) = x / s**

Multiplies all values of a component by a constant factor.
Preserves pairwise difference ratios:
T(x)[i] − T(x)[j] = (x[i] − x[j]) / s for all i, j.

Domain instance: declared unit choice within M. Converting
wind speed from m/s to knots scales all values uniformly.

**Per-timestep z-scoring: T(x) = (x − μ_t) / σ_t**

Subtracts the cross-station mean and divides by the cross-station
standard deviation, computed at a single timestep for a single
component. This is a uniform shift (−μ_t) composed with a
uniform scaling (1/σ_t), applied per component per timestep.

Preserved: pairwise difference ratios within each component at
each timestep. For stations i and j at timestep t:
T(x)[i] − T(x)[j] = (x[i] − x[j]) / σ_t.
The relational content that A extracts is invariant up to the
declared scale factor σ_t (Invariant Taxonomy §1).

Discarded: absolute magnitudes, cross-timestep comparability
of raw values, cross-component magnitude relationships (each
component is independently scaled to unit variance).

This is the standardization used in this repository. It is
declared within M, not applied as preprocessing within the
operator pipeline.

**Wind decomposition: (speed, direction) → (u, v)**

Converts polar wind representation to Cartesian components.
u = −speed · sin(direction), v = −speed · cos(direction).

This is a coordinate transformation, not a scaling. It is
injective on the wind vector (u, v uniquely determine speed
and direction when speed > 0) and declared non-injective at
speed = 0 (all directions map to u = v = 0).

Preserved: the horizontal wind vector.
Discarded: the polar representation. The pairwise differences
in u and v are the Cartesian projections of the pairwise
differences in the wind vectors, which is the operationally
relevant relational content for gradient extraction under the
declared representation.

This transformation must occur within M because operator A
requires scalar components with well-defined pairwise
differences. Wind direction as an angular quantity does not
have well-defined pairwise differences on ℝ (the difference
between 350° and 10° is 20°, not 340°). The decomposition
resolves this by mapping to ℝ² where pairwise differences
are well-defined.

**Missing-data exclusion:**

Stations with any NaN component are excluded from D for that
timestep. This is not a transformation of values — it is a
declared restriction of the domain. The field at each timestep
is defined over the stations present, not over a fixed station
set with imputed values.

Preserved: all pairwise differences among included stations
are determined by actual observations.
Discarded: relational information involving excluded stations.

### Inadmissible Transformations Before A

The following are inadmissible prior to A unless declared within
M with stated preserved and discarded invariants. Even when
declared within M, these transformations alter the relational
content that A extracts, and the downstream consequences must
be stated.

**Cross-station normalization (min-max scaling):**

T(x)[i] = (x[i] − min) / (max − min), where min and max are
computed across stations. This is not a uniform scaling — min
and max are themselves functions of the field, and the
transformation maps the extreme values to 0 and 1 regardless
of their relational position.

Alters pairwise differences: T(x)[i] − T(x)[j] =
(x[i] − x[j]) / (max − min), where the denominator depends
on the specific field values. Two fields with identical
relational structure but different ranges produce different
post-normalization pairwise differences relative to each other
when compared across timesteps.

Inadmissible before A as a default. Admissible within M only
if the range-dependence of the denominator is declared and the
cross-timestep non-comparability is stated as a discarded
invariant.

Note: within a single field at a single timestep, min-max
scaling is affine and preserves pairwise difference ratios
exactly, just as z-scoring does. The concern is that the
scaling denominator (max − min) is itself field-dependent,
making cross-field relational comparisons range-coupled: two
fields with identical relational structure but different ranges
produce different post-normalization pairwise differences
relative to each other when compared across timesteps. Z-scoring
shares this property (σ_t is field-dependent), but both are
uniform affine transformations within a single field. The
distinction between z-scoring and min-max scaling is not
within-field behavior — both are admissible there — but
sensitivity to outliers in the denominator: min-max scaling's
denominator is determined by two extreme values, while
z-scoring's denominator integrates across all values.

**Spatial interpolation / gridding:**

Mapping irregular station observations onto a regular grid
through interpolation (kriging, inverse-distance weighting,
spline fitting). This introduces values at grid points that
are weighted combinations of station observations.

Alters pairwise differences: the interpolated value at grid
point g is a weighted sum of station values, and pairwise
differences between grid points do not correspond to pairwise
differences between any pair of stations. Interpolation
introduces relational structure not directly present in the
original station-to-station measurements.

Inadmissible before A in this repository. The repository
operates on the irregular station graph precisely to avoid
this transformation. Interpolation is admissible within M for
repositories that require regular topologies (e.g., the
magnetosphere repo uses grid interpolation within M and
declares its preserved/discarded invariants), but this
repository does not use it.

**Model assimilation:**

Numerical weather prediction models assimilate observations
into a dynamical model state through variational or ensemble
methods. The output is a model state, not an observation.

Inadmissible before A because the model state is a product of
the model's dynamics, not of M. The kernel operates on M(o) —
images of observables under the declared measurement mapping —
not on model states. Model output is a different O requiring
its own M declaration.

**Temporal smoothing / rolling averages:**

Averaging a station's values across multiple timesteps. This
couples values at different times into a single field value,
destroying the temporal independence of each timestep's
relational structure.

Inadmissible before A. Temporal succession is the ordering
over which Γ is computed as a first difference; smoothing
across that ordering before A operates conflates the relational
structure at distinct timesteps.

**Log transforms, power transforms, Box-Cox:**

T(x) = log(x), T(x) = x^λ, etc. These are non-uniform
transformations: they alter pairwise differences
non-uniformly across the field.

For log: T(x)[i] − T(x)[j] = log(x[i]/x[j]), which depends
on the ratio of values, not the difference. The relational
content A extracts from log-transformed data is the log-ratio
structure, not the difference structure.

Inadmissible before A unless declared within M with stated
preserved and discarded invariants. If the domain's relational
content is better characterized by ratios than differences (e.g.,
multiplicative processes), a log transform within M may be
admissible — but the declaration must state that A will extract
log-ratio gradients rather than difference gradients, and that
the downstream interpretation changes accordingly.

---

## Stage 2: Between A and B

### Admissible

No transformations are applied between A and B in this
repository. B's input is A's output directly.

In principle, any EdgeField → EdgeField transformation that
preserves pairwise edge differences along the declared topology
would be admissible here, but no such transformation is defined
or needed in the current implementation.

### Inadmissible

**Any EdgeField → NodeField transition.** Collapsing the edge
field back to node values between A and B violates
representation type discipline (Invariant Taxonomy §5). B
requires EdgeField input.

**Any aggregation across edges.** Computing summary statistics
of the edge field (mean, variance, max) and using them to
modify individual edges before B operates would introduce
global coupling at a stage where only local accumulation is
declared.

---

## Stage 3: Between B and R

### Admissible

No transformations are applied between B and R in this
repository. R's input is B's output directly.

### Inadmissible

The same restrictions as Stage 2 apply. Additionally:

**Cross-axis coupling before R.** B preserves directional
identity — it accumulates edges along their own axis without
coupling across axes (spatial vs. component). Introducing
cross-axis coupling between B and R would duplicate R's
function and alter R's input in undeclared ways.

---

## Stage 4: After R (Projection Layer)

### The Projection Declaration Requirement

Every non-injective transformation applied to R's output must
declare what it preserves and what it discards (Object Error
§8.6–8.7, Invariant Taxonomy §11).

R's output is a MultiTopoEdgeField1D — the full coupled
relational structure of the weather field at that timestep.
Any reduction of this structure to scalars, node values, or
summaries is a projection that discards information.

### Projections Used in This Repository

**σ² (edge-field variance):**
```
σ²(e) = Var(e) = (1/n) Σ (e[i] − mean(e))²
```
Applied to the full edge field or to per-type subsets.

Preserved: total relational variance magnitude (or per-type
variance magnitude).
Discarded: all spatial structure, edge-level detail, sign
structure, directional information.

This is the primary diagnostic. It is a declared scalar
projection of a structured edge field (Invariant Taxonomy §3
note: "σ² is itself a declared projection").

**Γ (R-sustained circulation):**
```
Γ = σ²(R(B(A(x)))) − σ²(B(A(x)))
```
A difference of two σ² projections applied to the same input
field under two different operator compositions.

Preserved: the variance contribution attributable to R's
coupling.
Discarded: everything not captured by the σ² difference.

**ΔΓ (temporal first difference):**
```
ΔΓ(t) = Γ(t) − Γ(t−1)
```
The rate of change of Γ across consecutive timesteps.

Preserved: the direction and magnitude of change in R-sustained
circulation between adjacent timesteps.
Discarded: the absolute Γ value, all within-timestep structure.

**Scalar indices (for comparison):**
Per-component scalar statistics computed from the raw station
observations (not from the edge field). These are index-local
measures used as comparison baselines, not as kernel outputs.

### Projections Not Used in This Repository

The kernel README defines three C projections for V4 multi-
topology fields: C_per_type, C_shared, and C_spatial_only
(operators_V4.rs §8). None are applied in this repository.
The σ² diagnostic operates on unbounded R output. Bounding
is not required before a declared variance projection.

### Admissible but Not Implemented

Any EdgeField → NodeField or EdgeField → scalar projection
with stated preserved and discarded invariants is admissible
at this stage. Examples that would extend the analysis:

- Per-station Γ decomposition (README, Open Condition #8)
- Edge sign structure summaries (Invariant Taxonomy §4)
- Per-component-pair Γ for coupling identification
- Spatial Γ maps for frontal passage localization

Each would require its own preserved/discarded declaration
before implementation.

---

## Summary Table

| Transformation | Within M | Before A (outside M) | Between A–B | Between B–R | After R |
|---|---|---|---|---|---|
| Uniform shift (T = x + c) | admissible | admissible | — | — | admissible |
| Uniform scaling (T = x / s) | admissible | admissible | — | — | admissible |
| Per-timestep z-scoring | admissible (declared) | inadmissible | — | — | — |
| Wind decomposition | admissible (declared) | inadmissible | — | — | — |
| Min-max normalization | conditional (must declare) | inadmissible | — | — | — |
| Spatial interpolation | conditional (must declare) | inadmissible | — | — | — |
| Temporal smoothing | inadmissible | inadmissible | — | — | conditional |
| Log / power transforms | conditional (must declare) | inadmissible | — | — | — |
| Model assimilation | inadmissible | inadmissible | — | — | — |
| EdgeField → NodeField | — | — | inadmissible | inadmissible | admissible (declared) |
| σ², Γ, ΔΓ | — | — | — | — | admissible (declared) |
| Cross-axis coupling | — | — | inadmissible | inadmissible | — |

"—" indicates the transformation does not arise at that stage.
"conditional" indicates admissible only with stated preserved
and discarded invariants.

---

## Relationship to Kernel Documents

| Topic | Reference |
|---|---|
| Pre-operator transformation constraint | Object Error §11, operators_V4.rs §11 |
| Relational content invariance | Invariant Taxonomy §1 |
| Non-injective transformation principle | Object Error §8.6 |
| Projection declaration requirement | Object Error §8.7, Invariant Taxonomy §11 |
| Representation type discipline | Invariant Taxonomy §5 |
| Operator ordering | Invariant Taxonomy §6 |
| R-sustained circulation (Γ) | Invariant Taxonomy §3 |
| Edge sign structure | Invariant Taxonomy §4 |
| B-admissibility on irregular graphs | Invariant Taxonomy §7 (open condition) |
| Domain closure (V4) | Invariant Taxonomy §9 |

---

## Declared Open Conditions

1. **Min-max normalization within M.** The distinction between
   z-scoring (uniform affine, admissible) and min-max scaling
   (range-dependent, conditional) is stated but not formally
   proved as a theorem. The claim rests on the observation that
   z-scoring preserves pairwise difference ratios while min-max
   scaling does not preserve them uniformly across fields with
   different distributions. A formal characterization of which
   non-uniform scalings preserve which relational invariants
   under A is a declared open condition.

2. **Log transforms for multiplicative domains.** The statement
   that log transforms within M are conditionally admissible
   for domains with multiplicative relational structure is a
   declared design principle, not a proved result. Whether
   A operating on log-transformed data produces a well-defined
   relational structure equivalent to ratio-based gradients,
   and whether Theorems 4–6 hold under this substitution, is
   a declared open condition.

---

*All definitions bounded over D. No claim beyond D.*
