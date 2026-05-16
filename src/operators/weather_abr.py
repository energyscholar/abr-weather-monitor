"""
weather_abr.py — V4 ABR Operator Application
ABR Weather Station Monitor — Phase 1

Applies V4 ABR kernel (A → B → R → E) to declared fields
per timestep. Computes diagnostics: sigma_sq per topology,
Gamma (R-sustained circulation).

STRUCTURAL DISTINCTION:
  Operator topologies (internal to E):
    Spatial:   proximity graph on stations (symmetric)
    Component: all-pairs on 6 components (symmetric)

  Observational evolution ordering (NOT an operator topology):
    Temporal:  forward-only succession of hourly snapshots
    Each e(t) = E(x(t), rho) evaluated independently.

OPERATOR DEFINITIONS:
  A: VectorNodeField1D → MultiTopoEdgeField
     Extracts directed pairwise differences over both
     spatial and component topologies.

  B: MultiTopoEdgeField → MultiTopoEdgeField
     Same-direction accumulation along declared topology.

  R: MultiTopoEdgeField × ρ → MultiTopoEdgeField
     Antisymmetric cross-coupling between spatial and
     component topologies. Local. Additive.

  V4 kernel: E(x, ρ) = R(B(A(x)), ρ(A(x)))
  C is a declared projection, not a kernel operator.

TOPOLOGY NOTE:
  The spatial topology here is an irregular proximity graph,
  NOT a ring or torus. Stations have varying degree. The
  operator definitions require:
    - For each station, a defined set of spatial neighbors
    - For B: accumulation along spatial neighbors
    - For R: antisymmetric coupling requires forward/backward
      distinction — on irregular graphs, this is replaced by
      neighbor-set asymmetry (see implementation notes).

  The component topology IS regular (all-pairs), so B and R
  on component edges follow the standard definitions.

Metatron Dynamics, Inc.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


# =============================================================
# 1. TYPES — EDGE FIELD REPRESENTATION
# =============================================================

@dataclass
class MultiTopoEdgeField:
    """Multi-topology edge field on irregular spatial graph.

    spatial_edges[c][(i,j)] = directed edge value for component c
        from station i to station j.
        One entry per directed spatial edge per component.

    comp_edges[p][i] = component edge value for pair p at station i.
        One entry per station per component pair.

    This representation preserves:
      - Direction of each spatial edge (i→j vs j→i)
      - Per-station component coupling
      - Full edge field without implicit collapse to nodes
    """
    spatial_edges: list   # list[dict[(int,int), float]], length k
    comp_edges: list      # list[list[float]], length n_pairs
    n_stations: int
    k_components: int
    comp_pairs: list      # list[(int, int)]
    spatial_adj: dict     # dict[int, list[int]] — adjacency list
    timestamp: object


# =============================================================
# 2. ADJACENCY STRUCTURE
# =============================================================

def build_adjacency(spatial_edge_list: list, n: int) -> dict:
    """Build adjacency list from declared spatial edges.

    Returns dict[int, list[int]] where adj[i] = sorted list
    of neighbors of station i.
    """
    adj = {i: set() for i in range(n)}
    for (i, j) in spatial_edge_list:
        adj[i].add(j)
    # Sort for deterministic iteration
    return {i: sorted(list(nb)) for i, nb in adj.items()}


# =============================================================
# 3. OPERATOR A — RELATIONAL GRADIENT EXTRACTION
# =============================================================

def operator_a(declared_field) -> MultiTopoEdgeField:
    """A: VectorNodeField1D → MultiTopoEdgeField

    Extracts directed pairwise differences over BOTH declared
    topologies:

    Spatial edges: For each component c and each directed spatial
      edge (i,j) in the declared topology:
        a_spatial[c][(i,j)] = field[c][i] - field[c][j]

    Component edges: For each declared component pair (a,b) and
      each station i:
        a_comp[p][i] = field[a][i] - field[b][i]

    This is the unique NodeField → EdgeField transition.
    """
    f = declared_field.field
    topo = declared_field.topology
    n = f.n
    k = f.k

    adj = build_adjacency(topo.spatial_edges, n)

    # Spatial edges: per component, per directed edge
    spatial_edges = []
    for c in range(k):
        edges_c = {}
        for i in range(n):
            for j in adj[i]:
                edges_c[(i, j)] = f.data[c][i] - f.data[c][j]
        spatial_edges.append(edges_c)

    # Component edges: per pair, per station
    comp_edges = []
    for (a, b) in topo.component_pairs:
        pair_edges = [f.data[a][i] - f.data[b][i] for i in range(n)]
        comp_edges.append(pair_edges)

    return MultiTopoEdgeField(
        spatial_edges=spatial_edges,
        comp_edges=comp_edges,
        n_stations=n,
        k_components=k,
        comp_pairs=topo.component_pairs,
        spatial_adj=adj,
        timestamp=declared_field.timestamp,
    )


# =============================================================
# 4. OPERATOR B — LOCAL RELATIONAL ACCUMULATION
# =============================================================

def operator_b_raw(ef: MultiTopoEdgeField) -> MultiTopoEdgeField:
    """B_raw: MultiTopoEdgeField → MultiTopoEdgeField

    Raw accumulation. No degree normalization.

    Spatial edges:
      b[(i,j)] = a[(i,j)] + sum(a[(j,k)] for k in adj[j])

    Accumulation magnitude scales with degree.

    On a ring (degree 1 per direction), reduces to canonical B.

    DECLARED: preserves degree-dependent accumulation magnitude
    (observational density structure). Discards degree-independent
    comparability between stations.
    """
    n = ef.n_stations
    k = ef.k_components
    adj = ef.spatial_adj

    new_spatial = []
    for c in range(k):
        old = ef.spatial_edges[c]
        new_c = {}
        for (i, j), val in old.items():
            neighbors_of_j = adj.get(j, [])
            neighbor_sum = sum(
                old.get((j, m), 0.0) for m in neighbors_of_j
            )
            new_c[(i, j)] = val + neighbor_sum
        new_spatial.append(new_c)

    new_comp = []
    for p_idx in range(len(ef.comp_pairs)):
        old = ef.comp_edges[p_idx]
        new_p = []
        for i in range(n):
            neighbors = adj.get(i, [])
            neighbor_sum = sum(old[j] for j in neighbors)
            new_p.append(old[i] + neighbor_sum)
        new_comp.append(new_p)

    return MultiTopoEdgeField(
        spatial_edges=new_spatial,
        comp_edges=new_comp,
        n_stations=n,
        k_components=k,
        comp_pairs=ef.comp_pairs,
        spatial_adj=adj,
        timestamp=ef.timestamp,
    )


def operator_b_normalized(ef: MultiTopoEdgeField) -> MultiTopoEdgeField:
    """B_norm: MultiTopoEdgeField → MultiTopoEdgeField

    Degree-normalized accumulation.

    Spatial edges:
      b[(i,j)] = a[(i,j)] + sum(a[(j,k)] for k in adj[j]) / |adj[j]|

    Preserves per-neighbor contribution independent of graph degree.

    On a ring (degree 1 per direction), reduces to canonical B.

    DECLARED: preserves relative per-neighbor contribution
    independent of graph degree. Discards degree-dependent
    accumulation magnitude.
    """
    n = ef.n_stations
    k = ef.k_components
    adj = ef.spatial_adj

    new_spatial = []
    for c in range(k):
        old = ef.spatial_edges[c]
        new_c = {}
        for (i, j), val in old.items():
            neighbors_of_j = adj.get(j, [])
            if neighbors_of_j:
                neighbor_sum = sum(
                    old.get((j, m), 0.0) for m in neighbors_of_j
                )
                new_c[(i, j)] = val + neighbor_sum / len(neighbors_of_j)
            else:
                new_c[(i, j)] = val
        new_spatial.append(new_c)

    new_comp = []
    for p_idx in range(len(ef.comp_pairs)):
        old = ef.comp_edges[p_idx]
        new_p = []
        for i in range(n):
            neighbors = adj.get(i, [])
            if neighbors:
                neighbor_mean = sum(old[j] for j in neighbors) / len(neighbors)
                new_p.append(old[i] + neighbor_mean)
            else:
                new_p.append(old[i])
        new_comp.append(new_p)

    return MultiTopoEdgeField(
        spatial_edges=new_spatial,
        comp_edges=new_comp,
        n_stations=n,
        k_components=k,
        comp_pairs=ef.comp_pairs,
        spatial_adj=adj,
        timestamp=ef.timestamp,
    )


# =============================================================
# 5. COMPUTE RHO — PER-STATION CIRCULATION STRENGTH
# =============================================================

def compute_rho(a_field: MultiTopoEdgeField, rho_base: float) -> list:
    """ρ[i] = ρ_base × max_grad[i] / (1 + max_grad[i])

    Per-station. Derived from A(x). No aggregation across stations.

    max_grad[i] = maximum absolute edge value at station i
    across all spatial edges incident to i and all component
    edges at i.
    """
    n = a_field.n_stations
    rho = []

    for i in range(n):
        m = 0.0

        # Spatial edges: all edges incident to station i
        for c in range(a_field.k_components):
            edges_c = a_field.spatial_edges[c]
            for j in a_field.spatial_adj.get(i, []):
                val = abs(edges_c.get((i, j), 0.0))
                if val > m:
                    m = val

        # Component edges at station i
        for p_idx in range(len(a_field.comp_pairs)):
            val = abs(a_field.comp_edges[p_idx][i])
            if val > m:
                m = val

        rho.append(rho_base * m / (1.0 + m))

    return rho


# =============================================================
# 6. OPERATOR R — ANTISYMMETRIC CIRCULATION
# =============================================================

def operator_r(
    bg: MultiTopoEdgeField,
    rho: list,
) -> MultiTopoEdgeField:
    """R: MultiTopoEdgeField × ρ → MultiTopoEdgeField

    Cross-couples edges across topologies:

    1. Spatial edges receive component-edge asymmetry:
       For each spatial edge (i,j) and component pair (a,b):
         spatial[a][(i,j)] += ρ[i] * (comp[p][j] - comp[p][i])
         spatial[b][(i,j)] -= ρ[i] * (comp[p][j] - comp[p][i])

       Component coupling flows into spatial structure.

    2. Component edges receive spatial-edge asymmetry:
       For each station i and component pair (a,b):
         comp[p][i] += ρ[i] * mean(spatial[a][(i,j)] - spatial[b][(i,j)]
                                    for j in adj[i])

       Spatial structure flows into component coupling.

    All coupling is local, antisymmetric, additive.
    """
    n = bg.n_stations
    k = bg.k_components
    adj = bg.spatial_adj
    pairs = bg.comp_pairs

    # Deep copy edge fields
    new_spatial = [dict(sc) for sc in bg.spatial_edges]
    new_comp = [list(ce) for ce in bg.comp_edges]

    # --- Spatial edges receive component-edge asymmetry ---
    for p_idx, (a, b) in enumerate(pairs):
        comp_vals = bg.comp_edges[p_idx]
        for i in range(n):
            rh = rho[i]
            for j in adj.get(i, []):
                # Component asymmetry along spatial edge
                comp_asym = comp_vals[j] - comp_vals[i]
                new_spatial[a][(i, j)] += rh * comp_asym
                new_spatial[b][(i, j)] -= rh * comp_asym

    # --- Component edges receive spatial-edge asymmetry ---
    for p_idx, (a, b) in enumerate(pairs):
        for i in range(n):
            neighbors = adj.get(i, [])
            if not neighbors:
                continue
            rh = rho[i]
            spatial_asym_sum = 0.0
            for j in neighbors:
                sa = bg.spatial_edges[a].get((i, j), 0.0)
                sb = bg.spatial_edges[b].get((i, j), 0.0)
                spatial_asym_sum += sa - sb
            spatial_asym_mean = spatial_asym_sum / len(neighbors)
            new_comp[p_idx][i] += rh * spatial_asym_mean

    return MultiTopoEdgeField(
        spatial_edges=new_spatial,
        comp_edges=new_comp,
        n_stations=n,
        k_components=k,
        comp_pairs=pairs,
        spatial_adj=adj,
        timestamp=bg.timestamp,
    )


# =============================================================
# 7. COMPOSITE E — V4 KERNEL
# =============================================================

def operator_e(declared_field, rho_base: float, b_variant: str = "normalized") -> MultiTopoEdgeField:
    """E(x, ρ) = R(B(A(x)), ρ(A(x)))

    V4 kernel composition. No C — C is a declared projection
    applied at the application layer.

    Args:
        declared_field: DeclaredField from measurement_mapping
        rho_base: declared circulation strength parameter
        b_variant: "raw" or "normalized" — declared B semantics

    Returns:
        MultiTopoEdgeField — the relational structure of this
        timestep's field under the full operator composition.
    """
    a = operator_a(declared_field)
    rho = compute_rho(a, rho_base)
    if b_variant == "raw":
        b = operator_b_raw(a)
    else:
        b = operator_b_normalized(a)
    r = operator_r(b, rho)
    return r


# =============================================================
# 8. DIAGNOSTICS — σ² (VARIANCE)
# =============================================================

def _variance(values: list) -> float:
    """Variance of a list of floats."""
    if not values:
        return 0.0
    n = len(values)
    mean = sum(values) / n
    return sum((v - mean) ** 2 for v in values) / n


def sigma_sq_spatial(ef: MultiTopoEdgeField, component: int) -> float:
    """σ² of spatial edge field for one component."""
    vals = list(ef.spatial_edges[component].values())
    return _variance(vals)


def sigma_sq_comp(ef: MultiTopoEdgeField, pair_idx: int) -> float:
    """σ² of component edge field for one pair."""
    return _variance(ef.comp_edges[pair_idx])


def sigma_sq_total(ef: MultiTopoEdgeField) -> float:
    """Total σ² across all spatial and component edges."""
    total = 0.0
    for c in range(ef.k_components):
        total += sigma_sq_spatial(ef, c)
    for p in range(len(ef.comp_pairs)):
        total += sigma_sq_comp(ef, p)
    return total


def sigma_sq_spatial_total(ef: MultiTopoEdgeField) -> float:
    """Total σ² across all spatial edges (all components)."""
    return sum(sigma_sq_spatial(ef, c) for c in range(ef.k_components))


def sigma_sq_comp_total(ef: MultiTopoEdgeField) -> float:
    """Total σ² across all component edges (all pairs)."""
    return sum(sigma_sq_comp(ef, p) for p in range(len(ef.comp_pairs)))


# =============================================================
# 9. GAMMA — R-SUSTAINED CIRCULATION
# =============================================================

def _count_spatial_edges(ef: MultiTopoEdgeField) -> int:
    """Count total directed spatial edges."""
    if ef.spatial_edges:
        return len(ef.spatial_edges[0])
    return 0


def _count_comp_values(ef: MultiTopoEdgeField) -> int:
    """Count total component edge values."""
    return len(ef.comp_pairs) * ef.n_stations


def sigma_sq_spatial_per_edge(ef: MultiTopoEdgeField) -> float:
    """Per-edge spatial σ²: total spatial σ² / number of directed spatial edges."""
    n_edges = _count_spatial_edges(ef)
    if n_edges == 0:
        return 0.0
    return sigma_sq_spatial_total(ef) / n_edges


def sigma_sq_comp_per_edge(ef: MultiTopoEdgeField) -> float:
    """Per-edge component σ²: total comp σ² / number of component values."""
    n_vals = _count_comp_values(ef)
    if n_vals == 0:
        return 0.0
    return sigma_sq_comp_total(ef) / n_vals


# =============================================================
# 9. GAMMA — R-SUSTAINED CIRCULATION
# =============================================================

def compute_gamma(declared_field, rho_base: float, b_variant: str = "normalized") -> dict:
    """Compute Γ and its decomposition for one timestep.

    Γ(x, ρ) = σ²(R(B(A(x)), ρ)) - σ²(B(A(x)))

    Both computed from the same input field.
    Γ > 0 means R's cross-topology coupling produces relational
    variance beyond what B∘A alone produces.

    Computes both raw topology-total Γ and per-edge-normalized Γ.

    Returns dict with:
      gamma_total: raw Γ (topology-total, cardinality-sensitive)
      gamma_spatial: raw spatial Γ
      gamma_comp: raw component Γ
      gamma_spatial_per_edge: per-edge normalized spatial Γ
      gamma_comp_per_edge: per-edge normalized component Γ
      sigma_sq_e: σ²(E)
      sigma_sq_ba: σ²(B(A))
      e_field: full E output
      ba_field: B(A) output
      per_comp_spatial: per-component spatial σ²(E)
      per_pair_comp: per-pair component σ²(E)
      n_spatial_directed: directed spatial edge count
      n_comp_values: component value count
      b_variant: which B was used
    """
    a = operator_a(declared_field)
    rho = compute_rho(a, rho_base)
    if b_variant == "raw":
        b = operator_b_raw(a)
    else:
        b = operator_b_normalized(a)
    e = operator_r(b, rho)

    # σ² for full E
    sq_e_total = sigma_sq_total(e)
    sq_e_spatial = sigma_sq_spatial_total(e)
    sq_e_comp = sigma_sq_comp_total(e)

    # σ² for B(A) — without R
    sq_ba_total = sigma_sq_total(b)
    sq_ba_spatial = sigma_sq_spatial_total(b)
    sq_ba_comp = sigma_sq_comp_total(b)

    # Raw Γ
    g_total = sq_e_total - sq_ba_total
    g_spatial = sq_e_spatial - sq_ba_spatial
    g_comp = sq_e_comp - sq_ba_comp

    # Edge counts for normalization
    n_sp_edges = _count_spatial_edges(e)
    n_cp_values = _count_comp_values(e)

    # Per-edge Γ
    g_spatial_pe = g_spatial / n_sp_edges if n_sp_edges > 0 else 0.0
    g_comp_pe = g_comp / n_cp_values if n_cp_values > 0 else 0.0

    # Per-component and per-pair decomposition
    per_comp = [sigma_sq_spatial(e, c) for c in range(e.k_components)]
    per_pair = [sigma_sq_comp(e, p) for p in range(len(e.comp_pairs))]

    return {
        "timestamp": declared_field.timestamp,
        # Raw topology-total Γ
        "gamma_total": g_total,
        "gamma_spatial": g_spatial,
        "gamma_comp": g_comp,
        # Per-edge normalized Γ
        "gamma_spatial_per_edge": g_spatial_pe,
        "gamma_comp_per_edge": g_comp_pe,
        # σ² totals
        "sigma_sq_e": sq_e_total,
        "sigma_sq_ba": sq_ba_total,
        # Fields
        "e_field": e,
        "ba_field": b,
        # Decomposition
        "per_comp_spatial": per_comp,
        "per_pair_comp": per_pair,
        # Metadata
        "n_stations": declared_field.topology.n_stations,
        "n_spatial_directed": n_sp_edges,
        "n_comp_values": n_cp_values,
        "n_spatial_edges": len(
            set((min(i,j), max(i,j))
                for i,j in declared_field.topology.spatial_edges)
        ),
        "b_variant": b_variant,
    }


# =============================================================
# 10. BATCH PROCESSING
# =============================================================

def process_all_timesteps(
    fields: list,
    rho_base: float,
    b_variant: str = "normalized",
) -> list:
    """Apply operator E and compute Γ for all timesteps.

    Args:
        fields: list[DeclaredField] from measurement_mapping
        rho_base: declared by Origin
        b_variant: "raw" or "normalized" — declared B semantics

    Returns:
        list[dict] — one gamma result dict per timestep
    """
    results = []

    for i, df in enumerate(fields):
        result = compute_gamma(df, rho_base, b_variant)
        results.append(result)

        if (i + 1) % 12 == 0 or i == 0 or i == len(fields) - 1:
            print(f"  [{i+1}/{len(fields)}] {result['timestamp']} "
                  f"Γ={result['gamma_total']:.4f} "
                  f"σ²(E)={result['sigma_sq_e']:.4f} "
                  f"σ²(BA)={result['sigma_sq_ba']:.4f} "
                  f"n={result['n_stations']}")

    return results


def print_gamma_summary(results: list):
    """Print summary statistics for Γ across all timesteps."""
    gammas = [r["gamma_total"] for r in results]
    g_spatial = [r["gamma_spatial"] for r in results]
    g_comp = [r["gamma_comp"] for r in results]
    g_sp_pe = [r["gamma_spatial_per_edge"] for r in results]
    g_cp_pe = [r["gamma_comp_per_edge"] for r in results]
    sq_e = [r["sigma_sq_e"] for r in results]
    sq_ba = [r["sigma_sq_ba"] for r in results]

    b_var = results[0].get("b_variant", "unknown")

    print(f"\n=== GAMMA SUMMARY (B={b_var}) ===")
    print(f"  Timesteps: {len(results)}")

    print(f"\n  --- Raw topology-total Γ ---")
    print(f"  Γ total:   min={min(gammas):.4f} max={max(gammas):.4f} "
          f"mean={sum(gammas)/len(gammas):.4f}")
    print(f"  Γ spatial: min={min(g_spatial):.4f} max={max(g_spatial):.4f} "
          f"mean={sum(g_spatial)/len(g_spatial):.4f}")
    print(f"  Γ comp:    min={min(g_comp):.4f} max={max(g_comp):.4f} "
          f"mean={sum(g_comp)/len(g_comp):.4f}")

    print(f"\n  --- Per-edge normalized Γ ---")
    print(f"  Γ spatial/edge: min={min(g_sp_pe):.6f} max={max(g_sp_pe):.6f} "
          f"mean={sum(g_sp_pe)/len(g_sp_pe):.6f}")
    print(f"  Γ comp/edge:    min={min(g_cp_pe):.6f} max={max(g_cp_pe):.6f} "
          f"mean={sum(g_cp_pe)/len(g_cp_pe):.6f}")

    # Per-edge ratio
    mean_sp_pe = sum(g_sp_pe) / len(g_sp_pe)
    mean_cp_pe = sum(g_cp_pe) / len(g_cp_pe)
    if mean_sp_pe != 0:
        ratio = mean_cp_pe / mean_sp_pe
        print(f"  Comp/Spatial per-edge ratio: {ratio:.4f}")

    print(f"\n  σ²(E):     min={min(sq_e):.4f} max={max(sq_e):.4f}")
    print(f"  σ²(BA):    min={min(sq_ba):.4f} max={max(sq_ba):.4f}")

    # Raw component fraction
    total_gamma = sum(gammas)
    comp_gamma = sum(g_comp)
    if total_gamma > 0:
        print(f"\n  Raw component fraction of Γ: "
              f"{comp_gamma/total_gamma*100:.1f}%")

    all_positive = all(g > 0 for g in gammas)
    print(f"  All Γ > 0: {all_positive}")
    if not all_positive:
        neg = sum(1 for g in gammas if g <= 0)
        print(f"  WARNING: {neg} timesteps with Γ ≤ 0")
