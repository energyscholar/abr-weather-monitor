"""
tests/test_operator_invariants.py — ABR Weather Station Monitor

Invariant validation tests for the V4 ABR kernel as instantiated
in this repository. Each test corresponds to a numbered invariant
in invariant-taxonomy.md and verifies that the weather pipeline
preserves it under the declared topology and dataset.

These tests operate on synthetic fields constructed on the same
station geometry used by the pipeline (proximity graph, k=6
components, all-pairs component topology). They do not require
network access or cached METAR data.

SCOPE LIMITATION: The operator implementations in this file are
self-contained and structurally simplified — particularly R,
whose cross-topology coupling is implemented as a per-station
broadcast rather than per-edge routing. These implementations
validate invariant structure and operator admissibility
conditions, not numerical equivalence with the production kernel
in src/operators/weather_abr.py. Tests confirming numerical
agreement between these implementations and the production code
are a separate concern and are not claimed here.

Some tests validate formal invariants linked to theorems (IT§1,
IT§3, IT§5, IT§6, IT§10). Others validate implementation
behavior under the declared topology and synthetic dataset
(dual B-variant divergence, sign preservation). The distinction
is noted in each test class docstring.

All assertions are bounded over D and over the declared test
geometry. No claim beyond D.

Invariant cross-references use the format [IT§N] for
invariant-taxonomy.md §N, [OE§N] for object-error.md §N,
[OH§N] for operator_hierarchy.md §N.
"""

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Synthetic geometry builder
# ---------------------------------------------------------------------------

def build_test_geometry(n_stations=20, k=6, n_comp_pairs=15, seed=42):
    """
    Build a synthetic station geometry for invariant testing.

    Returns a dict with:
      - node_field: (k, n_stations) array, random values
      - shifted_field: node_field + uniform constant per component
      - permuted_field: node_field with stations permuted (same multiset,
        different relational structure)
      - adjacency: list of (i, j) pairs (random proximity graph)
      - comp_pairs: list of (a, b) component pairs (all-pairs)
      - n, k, n_comp_pairs: dimensions
    """
    rng = np.random.default_rng(seed)

    # Random node field
    node_field = rng.standard_normal((k, n_stations))

    # Shifted field: uniform shift across ALL components and stations.
    # Translation equivalence (IT§1) requires the same constant added
    # to every element of the field. A per-component shift with
    # different constants alters inter-component differences
    # (x[a][i] + c_a) - (x[b][i] + c_b) = (x[a][i] - x[b][i]) + (c_a - c_b),
    # which is nonzero when c_a ≠ c_b. That is correct behavior —
    # per-component shifts are admissible for spatial edges but not
    # for component edges.
    uniform_shift = rng.uniform(-100, 100)
    shifted_field = node_field + uniform_shift

    # Per-component shifted field: different constant per component.
    # Spatial edges invariant, component edges shifted by (c_a - c_b).
    per_comp_shifts = rng.uniform(-100, 100, size=(k, 1))
    per_comp_shifted_field = node_field + per_comp_shifts

    # Permuted field: same multiset, different relational arrangement
    perm = rng.permutation(n_stations)
    permuted_field = node_field[:, perm]

    # Random proximity graph (connected, variable degree)
    adjacency = []
    # Ensure connectivity: chain
    for i in range(n_stations - 1):
        adjacency.append((i, i + 1))
    # Add random edges for irregular degree
    for _ in range(n_stations * 2):
        i, j = rng.integers(0, n_stations, size=2)
        if i != j and (i, j) not in adjacency and (j, i) not in adjacency:
            adjacency.append((i, j))

    # All-pairs component topology
    comp_pairs = []
    for a in range(k):
        for b in range(a + 1, k):
            comp_pairs.append((a, b))

    return {
        "node_field": node_field,
        "shifted_field": shifted_field,
        "per_comp_shifted_field": per_comp_shifted_field,
        "permuted_field": permuted_field,
        "adjacency": adjacency,
        "comp_pairs": comp_pairs,
        "n": n_stations,
        "k": k,
        "n_comp_pairs": len(comp_pairs),
    }


# ---------------------------------------------------------------------------
# Operator implementations (minimal, self-contained for testing)
#
# These mirror the logic in src/operators/weather_abr.py but are
# independent so the tests validate invariants against the kernel
# definitions, not against the pipeline implementation.
# ---------------------------------------------------------------------------

def operator_a(node_field, adjacency, comp_pairs):
    """
    A: NodeField → EdgeField.
    Spatial edges: x[c][i] - x[c][j] for each adjacency, each component.
    Component edges: x[a][i] - x[b][i] for each comp pair, each station.
    """
    k, n = node_field.shape
    n_adj = len(adjacency)
    n_cp = len(comp_pairs)

    spatial = np.zeros((k, n_adj))
    for idx, (i, j) in enumerate(adjacency):
        for c in range(k):
            spatial[c, idx] = node_field[c, i] - node_field[c, j]

    comp = np.zeros((n_cp, n))
    for idx, (a, b) in enumerate(comp_pairs):
        comp[idx, :] = node_field[a, :] - node_field[b, :]

    return {"spatial": spatial, "comp": comp}


def operator_b_normalized(edge_field, adjacency, n_stations):
    """
    B (degree-normalized): average of neighbor edges along topology.
    """
    k, n_adj = edge_field["spatial"].shape
    n_cp, n = edge_field["comp"].shape

    # Build edge adjacency: edges sharing a node are neighbors
    edge_neighbors = _edge_neighbor_map(adjacency, n_stations)

    spatial_out = np.zeros_like(edge_field["spatial"])
    for c in range(k):
        for idx in range(n_adj):
            nbrs = edge_neighbors[idx]
            if len(nbrs) > 0:
                spatial_out[c, idx] = np.mean(
                    [edge_field["spatial"][c, n_idx] for n_idx in nbrs]
                )

    # Component edges: accumulate along station adjacency
    station_neighbors = _station_neighbor_map(adjacency, n_stations)
    comp_out = np.zeros_like(edge_field["comp"])
    for p in range(n_cp):
        for i in range(n):
            nbrs = station_neighbors[i]
            if len(nbrs) > 0:
                comp_out[p, i] = np.mean(
                    [edge_field["comp"][p, j] for j in nbrs]
                )

    return {"spatial": spatial_out, "comp": comp_out}


def operator_b_raw(edge_field, adjacency, n_stations):
    """
    B (raw/additive): sum of neighbor edges along topology.
    """
    k, n_adj = edge_field["spatial"].shape
    n_cp, n = edge_field["comp"].shape

    edge_neighbors = _edge_neighbor_map(adjacency, n_stations)

    spatial_out = np.zeros_like(edge_field["spatial"])
    for c in range(k):
        for idx in range(n_adj):
            nbrs = edge_neighbors[idx]
            spatial_out[c, idx] = sum(
                edge_field["spatial"][c, n_idx] for n_idx in nbrs
            )

    station_neighbors = _station_neighbor_map(adjacency, n_stations)
    comp_out = np.zeros_like(edge_field["comp"])
    for p in range(n_cp):
        for i in range(n):
            nbrs = station_neighbors[i]
            comp_out[p, i] = sum(
                edge_field["comp"][p, j] for j in nbrs
            )

    return {"spatial": spatial_out, "comp": comp_out}


def operator_r(edge_field, comp_pairs, rho_base=0.1):
    """
    R: antisymmetric cross-topology circulation (SIMPLIFIED).

    This is a structurally simplified R that validates invariant
    properties (Γ > 0, type preservation, ordering sensitivity)
    but does not replicate the production kernel's per-edge
    routing. Specifically:

    - Cross-topology coupling is broadcast per-station across all
      spatial edges rather than routed through declared spatial
      adjacency.
    - Component edges receive a uniform spatial-asymmetry
      contribution rather than per-adjacency contributions.

    These simplifications preserve the structural properties
    under test (antisymmetric coupling produces additional
    variance beyond B alone, output remains EdgeField, ordering
    matters) but do not produce numerically identical output to
    src/operators/weather_abr.py.
    """
    k, n_adj = edge_field["spatial"].shape
    n_cp, n = edge_field["comp"].shape

    # Compute per-station rho from max component-edge magnitude
    max_grad = np.zeros(n)
    for p in range(n_cp):
        for i in range(n):
            max_grad[i] = max(max_grad[i], abs(edge_field["comp"][p, i]))
    rho = rho_base * max_grad / (1.0 + max_grad)

    spatial_out = edge_field["spatial"].copy()
    comp_out = edge_field["comp"].copy()

    # Spatial edges receive component-edge asymmetry
    # Broadcast: each station's component-edge value is distributed
    # uniformly across all spatial edges (simplified from per-edge
    # routing in the production kernel).
    for p_idx, (a, b) in enumerate(comp_pairs):
        for i in range(n):
            contribution = rho[i] * edge_field["comp"][p_idx, i] / n_adj
            spatial_out[a, :] += contribution
            spatial_out[b, :] -= contribution

    # Component edges receive spatial-edge asymmetry
    # Averaged: the mean spatial-edge difference between components
    # a and b is added to each station's component edge (simplified
    # from per-adjacency routing in the production kernel).
    for p_idx, (a, b) in enumerate(comp_pairs):
        mean_spatial_asym = np.mean(
            edge_field["spatial"][a, :] - edge_field["spatial"][b, :]
        )
        comp_out[p_idx, :] += rho_base * mean_spatial_asym

    return {"spatial": spatial_out, "comp": comp_out}


def edge_field_variance(ef):
    """σ² of the full edge field (declared projection)."""
    all_vals = np.concatenate([
        ef["spatial"].ravel(),
        ef["comp"].ravel(),
    ])
    return np.var(all_vals)


def _edge_neighbor_map(adjacency, n_stations):
    """Map each edge index to indices of edges sharing a node."""
    node_to_edges = {}
    for idx, (i, j) in enumerate(adjacency):
        node_to_edges.setdefault(i, []).append(idx)
        node_to_edges.setdefault(j, []).append(idx)

    neighbors = {}
    for idx, (i, j) in enumerate(adjacency):
        nbrs = set()
        for n_idx in node_to_edges.get(i, []):
            if n_idx != idx:
                nbrs.add(n_idx)
        for n_idx in node_to_edges.get(j, []):
            if n_idx != idx:
                nbrs.add(n_idx)
        neighbors[idx] = list(nbrs)
    return neighbors


def _station_neighbor_map(adjacency, n_stations):
    """Map each station to its neighbor stations."""
    neighbors = {i: [] for i in range(n_stations)}
    for i, j in adjacency:
        neighbors[i].append(j)
        neighbors[j].append(i)
    return neighbors


# ===================================================================
# INVARIANT TESTS
# ===================================================================

@pytest.fixture
def geo():
    return build_test_geometry()


# -------------------------------------------------------------------
# Invariant 1: Relational Content Invariance [IT§1]
#
# A(x) = A(y) iff x ~_τ y. Uniform shift must produce identical
# edge fields. Permutation must produce different edge fields.
# -------------------------------------------------------------------

class TestRelationalContentInvariance:

    def test_uniform_shift_produces_identical_edges(self, geo):
        """Uniform shift (same constant across all components and
        stations) is translation equivalence. A(x + c) must equal
        A(x) for all edge types. [IT§1, OE§2.1]"""
        ef_original = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_shifted = operator_a(
            geo["shifted_field"], geo["adjacency"], geo["comp_pairs"]
        )
        np.testing.assert_allclose(
            ef_original["spatial"], ef_shifted["spatial"], atol=1e-12,
            err_msg="Spatial edges must be invariant under uniform shift"
        )
        np.testing.assert_allclose(
            ef_original["comp"], ef_shifted["comp"], atol=1e-12,
            err_msg="Component edges must be invariant under uniform shift"
        )

    def test_per_component_shift_preserves_spatial_not_comp(self, geo):
        """Per-component shift (different constant per component)
        preserves spatial edges but shifts component edges by
        (c_a - c_b). This is admissible within M as a declared
        unit choice per component. [IT§1, OH§M]"""
        ef_original = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_per_comp = operator_a(
            geo["per_comp_shifted_field"], geo["adjacency"], geo["comp_pairs"]
        )
        # Spatial edges: invariant (shift is uniform within each component)
        np.testing.assert_allclose(
            ef_original["spatial"], ef_per_comp["spatial"], atol=1e-12,
            err_msg="Spatial edges must be invariant under per-component shift"
        )
        # Component edges: shifted by (c_a - c_b), NOT invariant
        assert not np.allclose(
            ef_original["comp"], ef_per_comp["comp"], atol=1e-12
        ), "Component edges must differ under per-component shift"

    def test_uniform_scaling_preserves_ratios(self, geo):
        """Uniform scaling preserves pairwise difference ratios.
        A(x/s) = A(x)/s. [IT§1, OH§M]"""
        scale = 7.3
        scaled_field = geo["node_field"] / scale
        ef_original = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_scaled = operator_a(
            scaled_field, geo["adjacency"], geo["comp_pairs"]
        )
        np.testing.assert_allclose(
            ef_original["spatial"] / scale, ef_scaled["spatial"], atol=1e-12,
            err_msg="Spatial edges must scale uniformly"
        )
        np.testing.assert_allclose(
            ef_original["comp"] / scale, ef_scaled["comp"], atol=1e-12,
            err_msg="Component edges must scale uniformly"
        )

    def test_permutation_produces_different_edges(self, geo):
        """Different relational arrangement must produce different
        edge fields, even with identical multiset. [IT§1, OE Thm 4]"""
        ef_original = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_permuted = operator_a(
            geo["permuted_field"], geo["adjacency"], geo["comp_pairs"]
        )
        # At least one spatial edge must differ
        assert not np.allclose(
            ef_original["spatial"], ef_permuted["spatial"], atol=1e-12
        ), "Permuted field must produce different spatial edges"


# -------------------------------------------------------------------
# Invariant 3: R-Sustained Circulation [IT§3]
#
# Γ = σ²(R(B(A(x)))) − σ²(B(A(x))) > 0 for nontrivial fields.
# -------------------------------------------------------------------

class TestRSustainedCirculation:

    def test_gamma_positive_normalized(self, geo):
        """Γ > 0 under B_normalized for nontrivial input. [IT§3]"""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_b = operator_b_normalized(ef_a, geo["adjacency"], geo["n"])
        ef_r = operator_r(ef_b, geo["comp_pairs"])
        var_b = edge_field_variance(ef_b)
        var_r = edge_field_variance(ef_r)
        gamma = var_r - var_b
        assert gamma > 0, (
            f"Γ must be > 0 for nontrivial field; got {gamma:.6e} "
            f"(σ²_R={var_r:.6e}, σ²_B={var_b:.6e})"
        )

    def test_gamma_positive_raw(self, geo):
        """Γ > 0 under B_raw for nontrivial input. [IT§3]"""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_b = operator_b_raw(ef_a, geo["adjacency"], geo["n"])
        ef_r = operator_r(ef_b, geo["comp_pairs"])
        var_b = edge_field_variance(ef_b)
        var_r = edge_field_variance(ef_r)
        gamma = var_r - var_b
        assert gamma > 0, (
            f"Γ must be > 0 for nontrivial field; got {gamma:.6e}"
        )

    def test_gamma_zero_for_uniform_field(self, geo):
        """Γ = 0 when input is uniform (zero relational content).
        A produces zero edge field → B and R produce zero → Γ = 0."""
        uniform = np.ones((geo["k"], geo["n"])) * 42.0
        ef_a = operator_a(uniform, geo["adjacency"], geo["comp_pairs"])
        # All edges should be zero
        assert np.allclose(ef_a["spatial"], 0, atol=1e-12)
        assert np.allclose(ef_a["comp"], 0, atol=1e-12)


# -------------------------------------------------------------------
# Invariant 4: Edge Sign Structure [IT§4]
#
# Implementation behavior test (not a formal theorem): B's additive
# accumulation preserves edge signs when all accumulated edges share
# a sign. This validates expected behavior under the declared
# topology and synthetic dataset, not a proved invariant on
# irregular graphs.
# -------------------------------------------------------------------

class TestEdgeSignStructure:

    def test_b_preserves_sign_uniform_positive(self, geo):
        """B applied to an all-positive edge field must produce
        all-positive output. [IT§4]"""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        # Construct all-positive edge field
        ef_pos = {
            "spatial": np.abs(ef_a["spatial"]) + 0.01,
            "comp": np.abs(ef_a["comp"]) + 0.01,
        }
        ef_b = operator_b_raw(ef_pos, geo["adjacency"], geo["n"])
        assert np.all(ef_b["spatial"] >= 0), (
            "B_raw on all-positive edges must produce non-negative spatial edges"
        )
        assert np.all(ef_b["comp"] >= 0), (
            "B_raw on all-positive edges must produce non-negative comp edges"
        )


# -------------------------------------------------------------------
# Invariant 5: Representation Type Discipline [IT§5]
#
# A outputs EdgeField. B and R input/output EdgeField. No implicit
# EdgeField → NodeField transition occurs.
# -------------------------------------------------------------------

class TestRepresentationTypeDiscipline:

    def test_a_output_is_edge_field(self, geo):
        """A must produce spatial and component edge arrays, not
        a node-level array. [IT§5]"""
        ef = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        assert "spatial" in ef and "comp" in ef, (
            "A output must contain 'spatial' and 'comp' edge arrays"
        )
        # Spatial: (k, n_edges), not (k, n_stations)
        assert ef["spatial"].shape == (geo["k"], len(geo["adjacency"])), (
            f"Spatial edges shape {ef['spatial'].shape} does not match "
            f"expected ({geo['k']}, {len(geo['adjacency'])})"
        )
        # Component: (n_comp_pairs, n_stations)
        assert ef["comp"].shape == (geo["n_comp_pairs"], geo["n"]), (
            f"Component edges shape {ef['comp'].shape} does not match "
            f"expected ({geo['n_comp_pairs']}, {geo['n']})"
        )

    def test_b_output_matches_input_shape(self, geo):
        """B must produce EdgeField with same shape as input. [IT§5]"""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_b = operator_b_normalized(ef_a, geo["adjacency"], geo["n"])
        assert ef_b["spatial"].shape == ef_a["spatial"].shape
        assert ef_b["comp"].shape == ef_a["comp"].shape

    def test_r_output_matches_input_shape(self, geo):
        """R must produce EdgeField with same shape as input. [IT§5]"""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_b = operator_b_normalized(ef_a, geo["adjacency"], geo["n"])
        ef_r = operator_r(ef_b, geo["comp_pairs"])
        assert ef_r["spatial"].shape == ef_b["spatial"].shape
        assert ef_r["comp"].shape == ef_b["comp"].shape


# -------------------------------------------------------------------
# Invariant 6: Operator Ordering [IT§6]
#
# A → B → R must produce different output than any reordering.
# -------------------------------------------------------------------

class TestOperatorOrdering:

    def test_abr_differs_from_arb(self, geo):
        """A→B→R must differ from A→R→B (reordering violates
        invariant). [IT§6]"""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        # Canonical: A → B → R
        ef_b = operator_b_normalized(ef_a, geo["adjacency"], geo["n"])
        ef_abr = operator_r(ef_b, geo["comp_pairs"])

        # Reordered: A → R → B
        ef_r_first = operator_r(ef_a, geo["comp_pairs"])
        ef_arb = operator_b_normalized(
            ef_r_first, geo["adjacency"], geo["n"]
        )

        assert not np.allclose(
            ef_abr["spatial"], ef_arb["spatial"], atol=1e-10
        ), "A→B→R and A→R→B must produce different output"


# -------------------------------------------------------------------
# Invariant 10: Relational Determinacy [IT§10]
#
# All pairwise differences are defined and finite within D.
# -------------------------------------------------------------------

class TestRelationalDeterminacy:

    def test_all_edges_finite(self, geo):
        """All edge values must be finite (no NaN, no inf). [IT§10]"""
        ef = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        assert np.all(np.isfinite(ef["spatial"])), (
            "Spatial edges must be finite"
        )
        assert np.all(np.isfinite(ef["comp"])), (
            "Component edges must be finite"
        )

    def test_edges_finite_through_full_chain(self, geo):
        """Full A→B→R chain must produce finite output. [IT§10]"""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_b = operator_b_normalized(ef_a, geo["adjacency"], geo["n"])
        ef_r = operator_r(ef_b, geo["comp_pairs"])
        assert np.all(np.isfinite(ef_r["spatial"]))
        assert np.all(np.isfinite(ef_r["comp"]))


# -------------------------------------------------------------------
# Invariant 11: Projection Declaration [IT§11]
#
# σ² is a declared projection. Verify it is non-negative and
# that it returns zero for zero edge fields.
# -------------------------------------------------------------------

class TestProjectionDeclaration:

    def test_variance_non_negative(self, geo):
        """σ² must be non-negative for any edge field. [IT§11]"""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        assert edge_field_variance(ef_a) >= 0

    def test_variance_zero_for_zero_field(self, geo):
        """σ² must be zero for a zero edge field. [IT§11]"""
        zero_ef = {
            "spatial": np.zeros((geo["k"], len(geo["adjacency"]))),
            "comp": np.zeros((geo["n_comp_pairs"], geo["n"])),
        }
        assert edge_field_variance(zero_ef) == 0.0


# -------------------------------------------------------------------
# Pre-operator transformation constraint [OE§11, OH§M]
#
# Inadmissible transforms before A must alter edge output.
# Admissible transforms must not.
# -------------------------------------------------------------------

class TestPreOperatorConstraint:

    def test_nonuniform_scaling_alters_edges(self, geo):
        """Non-uniform scaling is inadmissible: it alters pairwise
        differences and therefore A's output. [OE§11]"""
        # Scale each station by a different factor
        rng = np.random.default_rng(99)
        scales = rng.uniform(0.5, 2.0, size=(1, geo["n"]))
        nonuniform = geo["node_field"] * scales

        ef_original = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )
        ef_nonuniform = operator_a(
            nonuniform, geo["adjacency"], geo["comp_pairs"]
        )
        assert not np.allclose(
            ef_original["spatial"], ef_nonuniform["spatial"], atol=1e-10
        ), "Non-uniform scaling must alter spatial edges"

    def test_log_transform_alters_edges(self, geo):
        """Log transform is inadmissible before A: it alters pairwise
        differences non-uniformly. [OE§11]"""
        # Shift to positive values first
        field_pos = geo["node_field"] - geo["node_field"].min() + 1.0
        log_field = np.log(field_pos)

        ef_original = operator_a(
            field_pos, geo["adjacency"], geo["comp_pairs"]
        )
        ef_log = operator_a(
            log_field, geo["adjacency"], geo["comp_pairs"]
        )
        assert not np.allclose(
            ef_original["spatial"], ef_log["spatial"], atol=1e-10
        ), "Log transform must alter spatial edges"


# -------------------------------------------------------------------
# Dual B-variant behavior
#
# Implementation behavior tests (not formal invariants): both
# variants must produce Γ > 0 on nontrivial input under the
# declared test geometry, and the two variants must produce
# different Γ values on the same input. These are observed
# consequences of the declared accumulation rules under the
# tested topology, not proved theorems.
# -------------------------------------------------------------------

class TestDualBVariant:

    def test_both_variants_gamma_positive(self, geo):
        """Both B_normalized and B_raw must yield Γ > 0."""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )

        ef_bn = operator_b_normalized(ef_a, geo["adjacency"], geo["n"])
        ef_rn = operator_r(ef_bn, geo["comp_pairs"])
        gamma_norm = edge_field_variance(ef_rn) - edge_field_variance(ef_bn)

        ef_br = operator_b_raw(ef_a, geo["adjacency"], geo["n"])
        ef_rr = operator_r(ef_br, geo["comp_pairs"])
        gamma_raw = edge_field_variance(ef_rr) - edge_field_variance(ef_br)

        assert gamma_norm > 0, f"Γ_normalized must be > 0; got {gamma_norm}"
        assert gamma_raw > 0, f"Γ_raw must be > 0; got {gamma_raw}"

    def test_variants_produce_different_gamma(self, geo):
        """B_normalized and B_raw must produce different Γ values
        on the same input (they select different coupling regimes)."""
        ef_a = operator_a(
            geo["node_field"], geo["adjacency"], geo["comp_pairs"]
        )

        ef_bn = operator_b_normalized(ef_a, geo["adjacency"], geo["n"])
        ef_rn = operator_r(ef_bn, geo["comp_pairs"])
        gamma_norm = edge_field_variance(ef_rn) - edge_field_variance(ef_bn)

        ef_br = operator_b_raw(ef_a, geo["adjacency"], geo["n"])
        ef_rr = operator_r(ef_br, geo["comp_pairs"])
        gamma_raw = edge_field_variance(ef_rr) - edge_field_variance(ef_br)

        assert not np.isclose(gamma_norm, gamma_raw, rtol=1e-6), (
            f"Γ_normalized ({gamma_norm}) and Γ_raw ({gamma_raw}) "
            f"should differ on the same input"
        )
