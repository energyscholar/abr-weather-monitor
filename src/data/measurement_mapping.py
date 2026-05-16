"""
measurement_mapping.py — M : O → D with Declared Topology
ABR Weather Station Monitor — Phase 0

This module implements M: the measurement mapping from
observables (METAR station data) to the declared domain D
with explicit topology declaration.

DOMAIN DECLARATION:
  D := { x ∈ ℝⁿ | n < ∞ and |x[i]| < ∞ ∀ i }
  
  Each element of D is a VectorNodeField1D:
    - n cells (stations present at this timestep)
    - k=6 components per cell:
      [temp_C, pressure_hPa, humidity_pct,
       wind_u_kt, wind_v_kt, dewpoint_c]

TOPOLOGY DECLARATION:
  Operator topologies (internal to E):
    Spatial:   proximity graph on station lat/lon
               station i adj station j iff geodesic(i,j) < threshold_km
               Symmetric. Declared before processing.
    Component: all-pairs on 6 components (15 pairs)
               Symmetric. Declared before processing.

  Observational evolution ordering (NOT an operator topology):
    Temporal:  forward-only succession of hourly snapshots
               Not used inside E. Used at analysis layer.

Metatron Dynamics, Inc.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


# =============================================================
# 1. TYPES — FIELD REPRESENTATION
# =============================================================

@dataclass
class VectorNodeField1D:
    """k-component vector field on n stations.
    
    data[c][i] = value of component c at station i.
    
    This is the input to operator A.
    """
    data: list          # list[list[float]], shape [k][n]
    n: int              # number of stations (cells)
    k: int              # number of components
    station_ids: list   # list[str], length n — provenance
    timestamp: object   # datetime — observational timestamp


@dataclass
class TopologyDeclaration:
    """Complete topology declaration for one timestep.
    
    Declared by Origin before operator evaluation.
    """
    # Spatial topology: list of (i, j) index pairs
    # where i, j are indices into the station list (0-based)
    spatial_edges: list         # list[tuple[int, int]]
    
    # Component topology: list of (a, b) component pairs
    # where a, b are component indices (0-based)
    component_pairs: list       # list[tuple[int, int]]
    
    # Metadata for verification
    n_stations: int
    n_components: int
    proximity_threshold_km: float
    is_connected: bool
    
    # Station ID mapping for this timestep
    station_index: dict         # dict[str, int] — station_id → index


@dataclass 
class DeclaredField:
    """Complete declared element of D: field + topology.
    
    This is the unit that enters operator evaluation.
    No operator may act on a VectorNodeField1D without
    its accompanying TopologyDeclaration.
    """
    field: VectorNodeField1D
    topology: TopologyDeclaration
    timestamp: object


# =============================================================
# 2. GEODESIC DISTANCE
# =============================================================

def haversine_km(lat1: float, lon1: float,
                 lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km.
    
    Used within M to compute spatial adjacency.
    """
    R = 6371.0  # Earth radius km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# =============================================================
# 3. SPATIAL TOPOLOGY CONSTRUCTION
# =============================================================

def build_spatial_topology(
    stations: list,
    station_ids: list,
    threshold_km: float,
) -> tuple:
    """Construct proximity graph from station positions.
    
    station i adjacent to station j iff:
      haversine(station_i, station_j) < threshold_km
    
    Symmetric: if (i,j) is an edge, (j,i) is an edge.
    
    Args:
        stations: list[StationMeta] — full station list with lat/lon
        station_ids: list[str] — station IDs present this timestep
        threshold_km: declared proximity threshold
    
    Returns:
        (edges, is_connected) where:
          edges: list[(int, int)] — adjacency pairs (both directions)
          is_connected: bool — whether graph is connected
    """
    # Build position lookup
    pos = {}
    for s in stations:
        pos[s.station_id] = (s.lat, s.lon)

    n = len(station_ids)
    edges = []

    for i in range(n):
        for j in range(i + 1, n):
            sid_i, sid_j = station_ids[i], station_ids[j]
            if sid_i not in pos or sid_j not in pos:
                continue
            lat_i, lon_i = pos[sid_i]
            lat_j, lon_j = pos[sid_j]
            dist = haversine_km(lat_i, lon_i, lat_j, lon_j)
            if dist < threshold_km:
                edges.append((i, j))
                edges.append((j, i))

    # Check connectivity via BFS
    if n <= 1:
        is_connected = True
    else:
        adj = {i: set() for i in range(n)}
        for (i, j) in edges:
            adj[i].add(j)
        visited = set()
        queue = [0]
        visited.add(0)
        while queue:
            node = queue.pop(0)
            for nb in adj[node]:
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)
        is_connected = len(visited) == n

    return edges, is_connected


# =============================================================
# 4. COMPONENT TOPOLOGY
# =============================================================

# Declared component ordering:
COMPONENTS = [
    "temp_c",        # 0
    "pressure_hpa",  # 1
    "humidity_pct",  # 2
    "wind_u_kt",     # 3
    "wind_v_kt",     # 4
    "dewpoint_c",    # 5
]
K_COMPONENTS = len(COMPONENTS)

# Declared characteristic magnitudes for unit scaling within M.
# Each value is a representative magnitude for that component,
# chosen so that typical pairwise differences across stations
# are O(1) after scaling.
#
# These are NOT computed from data. They are declared by Origin
# based on the physical range of each observable in the declared
# region and season.
#
# temp_c:        ~30°C range across network → scale by 30
# pressure_hpa:  ~15 hPa range across network → scale by 15
# humidity_pct:  ~100% range → scale by 100
# wind_u_kt:     ~40 kt range → scale by 40
# wind_v_kt:     ~40 kt range → scale by 40
# dewpoint_c:    ~30°C range across network → scale by 30
COMPONENT_SCALES = [
    30.0,   # temp_c
    15.0,   # pressure_hpa
    100.0,  # humidity_pct
    40.0,   # wind_u_kt
    40.0,   # wind_v_kt
    30.0,   # dewpoint_c
]


def build_component_topology_all_pairs(k: int = K_COMPONENTS) -> list:
    """All-pairs component topology.
    
    Declared by Origin. 15 pairs for k=6.
    """
    pairs = []
    for a in range(k):
        for b in range(a + 1, k):
            pairs.append((a, b))
    return pairs


def build_component_topology_ring(k: int = K_COMPONENTS) -> list:
    """Ring component topology: i adjacent to (i+1) mod k.
    
    Alternative declaration. 6 pairs for k=6.
    """
    return [(i, (i + 1) % k) for i in range(k)]


# =============================================================
# 5. MEASUREMENT MAPPING M
# =============================================================

def snapshot_to_declared_field(
    snapshot,
    all_stations: list,
    threshold_km: float,
    comp_topo: str = "all_pairs",
) -> Optional[DeclaredField]:
    """M : O → D
    
    Maps a single HourlySnapshot to a DeclaredField with
    explicit topology declaration.
    
    This is the measurement mapping. All unit conversions
    have already occurred in noaa_pipeline.py. This function:
      1. Constructs VectorNodeField1D from observations
      2. Declares spatial topology (proximity graph)
      3. Declares component topology
      4. Verifies connectivity
      5. Returns complete DeclaredField or None if inadmissible
    
    Args:
        snapshot: HourlySnapshot from noaa_pipeline
        all_stations: list[StationMeta] with positions
        threshold_km: proximity threshold (declared by Origin)
        comp_topo: "all_pairs" or "ring" (declared by Origin)
    
    Returns:
        DeclaredField or None if graph is disconnected
    """
    obs_list = snapshot.observations
    n = len(obs_list)

    if n < 3:
        # Fewer than 3 stations: spatial topology is degenerate
        return None

    station_ids = [o.station_id for o in obs_list]
    station_index = {sid: idx for idx, sid in enumerate(station_ids)}

    # Build component vectors: data[c][i]
    data = [[] for _ in range(K_COMPONENTS)]
    for obs in obs_list:
        data[0].append(obs.temp_c)
        data[1].append(obs.pressure_hpa)
        data[2].append(obs.humidity_pct)
        data[3].append(obs.wind_u_kt)
        data[4].append(obs.wind_v_kt)
        data[5].append(obs.dewpoint_c)

    # Verify all values finite (D membership)
    for c in range(K_COMPONENTS):
        for i in range(n):
            if not math.isfinite(data[c][i]):
                return None

    # Declared unit scaling within M.
    # Each component is divided by a declared characteristic
    # magnitude to bring all components to O(1) scale.
    # This is a uniform scaling per component: T(x) = x / s.
    # Admissible pre-A because it does not alter pairwise
    # difference RATIOS within a component.
    # Preserved: relational structure within each component,
    #   cross-component magnitude comparability.
    # Discarded: raw unit-dependent magnitudes.
    for c in range(K_COMPONENTS):
        s = COMPONENT_SCALES[c]
        for i in range(n):
            data[c][i] = data[c][i] / s

    field = VectorNodeField1D(
        data=data,
        n=n,
        k=K_COMPONENTS,
        station_ids=station_ids,
        timestamp=snapshot.timestamp,
    )

    # Spatial topology
    spatial_edges, is_connected = build_spatial_topology(
        all_stations, station_ids, threshold_km
    )

    if not is_connected:
        return None  # Inadmissible: disconnected graph

    # Component topology
    if comp_topo == "all_pairs":
        comp_pairs = build_component_topology_all_pairs()
    elif comp_topo == "ring":
        comp_pairs = build_component_topology_ring()
    else:
        raise ValueError(f"Unknown component topology: {comp_topo}")

    topology = TopologyDeclaration(
        spatial_edges=spatial_edges,
        n_stations=n,
        n_components=K_COMPONENTS,
        proximity_threshold_km=threshold_km,
        is_connected=is_connected,
        component_pairs=comp_pairs,
        station_index=station_index,
    )

    return DeclaredField(
        field=field,
        topology=topology,
        timestamp=snapshot.timestamp,
    )


# =============================================================
# 6. FULL PIPELINE: SNAPSHOTS → DECLARED FIELDS
# =============================================================

def map_all_snapshots(
    snapshots: list,
    all_stations: list,
    threshold_km: float,
    comp_topo: str = "all_pairs",
) -> list:
    """Apply M to all hourly snapshots.
    
    Returns list[DeclaredField] for admissible timesteps.
    Timesteps with disconnected graphs or insufficient
    stations are excluded with a warning.
    """
    fields = []
    excluded = 0

    for snap in snapshots:
        df = snapshot_to_declared_field(
            snap, all_stations, threshold_km, comp_topo
        )
        if df is not None:
            fields.append(df)
        else:
            excluded += 1

    print(f"M applied: {len(fields)} admissible timesteps, "
          f"{excluded} excluded (disconnected or insufficient)")

    return fields


# =============================================================
# 7. TOPOLOGY VERIFICATION
# =============================================================

def verify_topology(df: DeclaredField) -> dict:
    """Verify topology declaration for a single DeclaredField.
    
    Returns dict of verification results for Phase 0 checklist.
    """
    topo = df.topology
    n = topo.n_stations
    
    # Count unique spatial edges (undirected)
    undirected = set()
    for (i, j) in topo.spatial_edges:
        undirected.add((min(i, j), max(i, j)))
    
    # Degree distribution
    degree = [0] * n
    for (i, j) in topo.spatial_edges:
        degree[i] += 1  # counts both directions
    # Each direction counted once, so degree[i] = number of neighbors
    
    # But we stored both (i,j) and (j,i), so divide by... no.
    # Actually spatial_edges contains both directions.
    # degree[i] from the loop above counts outgoing edges = neighbors.
    
    return {
        "timestamp": df.timestamp,
        "n_stations": n,
        "n_spatial_edges_undirected": len(undirected),
        "n_component_pairs": len(topo.component_pairs),
        "is_connected": topo.is_connected,
        "min_degree": min(degree) if degree else 0,
        "max_degree": max(degree) if degree else 0,
        "mean_degree": sum(degree) / len(degree) if degree else 0,
        "threshold_km": topo.proximity_threshold_km,
    }


def print_topology_report(fields: list, n: int = 5):
    """Print topology verification for first n timesteps."""
    print("\n=== TOPOLOGY VERIFICATION ===")
    for df in fields[:n]:
        v = verify_topology(df)
        print(f"\n{v['timestamp']} UTC")
        print(f"  Stations: {v['n_stations']}")
        print(f"  Spatial edges: {v['n_spatial_edges_undirected']} "
              f"(undirected)")
        print(f"  Component pairs: {v['n_component_pairs']}")
        print(f"  Connected: {v['is_connected']}")
        print(f"  Degree: min={v['min_degree']}, "
              f"max={v['max_degree']}, "
              f"mean={v['mean_degree']:.1f}")
        print(f"  Threshold: {v['threshold_km']} km")

    if len(fields) > n:
        # Summary stats across all timesteps
        all_n = [df.topology.n_stations for df in fields]
        print(f"\n--- All {len(fields)} timesteps ---")
        print(f"  Station count: min={min(all_n)}, "
              f"max={max(all_n)}, mean={sum(all_n)/len(all_n):.1f}")
        
        # Check for topology drift
        all_sids = [set(df.field.station_ids) for df in fields]
        stable = all(s == all_sids[0] for s in all_sids)
        if stable:
            print("  Station set: STABLE across all timesteps")
        else:
            changes = sum(1 for i in range(1, len(all_sids))
                         if all_sids[i] != all_sids[i-1])
            print(f"  Station set: VARIABLE — {changes} changes "
                  f"across {len(fields)} timesteps")
            # Report the drift explicitly per Verifier requirement
            union = set()
            for s in all_sids:
                union |= s
            intersection = all_sids[0].copy()
            for s in all_sids[1:]:
                intersection &= s
            print(f"  Union of all stations: {len(union)}")
            print(f"  Intersection (always present): "
                  f"{len(intersection)}")
