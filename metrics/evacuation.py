"""Evacuation capacity by bottleneck attribution — Phase 4.

Implements ``evacuation_units_accommodatable`` exactly as specified in
``docs/capacity_indicators.md`` 3.1: route every tract's evacuation demand simultaneously along
free-flow shortest paths to the regional exit set, accumulate each link's load, find each
tract's binding bottleneck, and measure how many dwelling units the tract can add before that
bottleneck saturates -- under the pro-rata sharing rule, with the solo upper bound published
beside it.

Design choices carried from the spec, restated where they matter:

* **All-or-nothing shortest paths, not a congestion equilibrium.** Checkable by a person on a
  map; an equilibrium's output can only be checked by another model. The cost -- no rerouting
  under congestion -- is stated in every report.
* **Demand is measured, never assumed**: households x vehicles per household from ACS Table
  B25044, per tract. An affluent exurban tract generates roughly twice the vehicles per home of
  a dense urban one, and assuming a county average would bias the measure against dense tracts.
* **Simultaneous departure.** Everyone leaves at once -- the most conservative loading, and the
  one that needs no staging model. NUREG/CR-7002 stages departures over hours; v1 does not, so
  absolute clearance times here are upper bounds while the *ranking* between tracts is the
  meaningful output.
* **v1 is uncalibrated.** The spec's calibration against Caltrans count stations is explicit
  and separable; it has not yet been run, and every consumer of these numbers is told so.
* **v1 scores the pro-rata discharge rate, not the headroom form.** Under simultaneous
  departure the county's median binding bottleneck takes 6.5 hours to clear, so the spec's
  one-hour headroom form (capacity minus load) is negative almost everywhere and discriminates
  nothing. The scored measure is ``evacuation_units_per_hour`` -- the tract's pro-rata share of
  its binding bottleneck's discharge, in dwelling units per hour, which reduces to households
  divided by clearance hours. It is marginal, shared-bottleneck-aware, and robust to the
  departure-curve assumption; the headroom form returns with a staged-departure v2. The spec
  carries this amendment in docs/capacity_indicators.md 3.1.
"""

from __future__ import annotations

import pandas as pd

from config import INTERIM
from ingest.acs import load_table
from ingest.hazards import _block_points

#: B25044 estimate variables: households by vehicles available, owner then renter tenure.
#: The top bin ("5 or more") is counted as 5, slightly understating exurban demand.
_VEHICLE_COUNTS = {
    0: ["B25044_003", "B25044_010"],
    1: ["B25044_004", "B25044_011"],
    2: ["B25044_005", "B25044_012"],
    3: ["B25044_006", "B25044_013"],
    4: ["B25044_007", "B25044_014"],
    5: ["B25044_008", "B25044_015"],
}


def evacuation_demand() -> pd.DataFrame:
    """Evacuating vehicles per tract, from measured vehicle ownership.

    Returns:
        ``tract_geoid``, ``households`` (occupied), ``vehicles`` (total available),
        ``vehicles_per_household``.
    """
    table = load_table("B25044")
    frame = table.set_index("tract_geoid")

    households = frame["B25044_E001"]
    vehicles = sum(
        n * sum(frame[f"{v.split('_')[0]}_E{v.split('_')[1]}"] for v in variables)
        for n, variables in _VEHICLE_COUNTS.items()
    )
    out = pd.DataFrame(
        {
            "households": households,
            "vehicles": vehicles,
            "vehicles_per_household": (vehicles / households).where(households > 0),
        }
    ).reset_index()
    return out


def _tract_origins(graph, reachable=None, exits_hint=None) -> pd.DataFrame:
    """Each tract's origin node: the network node nearest its housing-weighted block centroid.

    ``reachable`` restricts candidates to nodes with a path to the exit set. Without it, a
    centroid can snap into a dead-end subgraph -- a parking aisle, a gated loop -- and a tract
    with perfectly good roads (Borrego Springs, three urban San Diego tracts in testing) reports
    as disconnected. An artifact of snapping, not a fact about the road network.

    Nearest-node search is done in metres (EPSG:3310) with a KD-tree rather than through
    ``osmnx.distance.nearest_nodes``, which requires an extra optional dependency for
    unprojected graphs; pyproj and scipy are already pinned.
    """
    import numpy as np
    from pyproj import Transformer
    from scipy.spatial import cKDTree

    points = _block_points().to_crs("EPSG:4326")
    weights = points["housing_units_2020"].clip(lower=1)  # keep zero-housing tracts locatable
    frame = pd.DataFrame(
        {
            "tract_geoid": points["tract_geoid"],
            "x": points.geometry.x * weights,
            "y": points.geometry.y * weights,
            "w": weights,
        }
    )
    centroids = frame.groupby("tract_geoid").sum()
    centroids["x"] /= centroids["w"]
    centroids["y"] /= centroids["w"]

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3310", always_xy=True)

    def tree_for(ids):
        xs = np.array([graph.nodes[n]["x"] for n in ids])
        ys = np.array([graph.nodes[n]["y"] for n in ids])
        return cKDTree(np.column_stack(transformer.transform(xs, ys)))

    all_ids = list(graph.nodes)
    origin_xy = np.column_stack(
        transformer.transform(centroids["x"].to_numpy(), centroids["y"].to_numpy())
    )
    dist_m, indices = tree_for(all_ids).query(origin_xy)
    nodes = [all_ids[i] for i in indices]

    if reachable is not None:
        # Two-stage snap: a centroid whose nearest node sits in a component that cannot reach
        # the exit set (a graph defect, not a fact about the place -- Borrego Springs in
        # testing) is re-snapped to the nearest exit-REACHABLE non-exit node, and the snap
        # distance is recorded so a long snap is visible in the output rather than silent.
        exits = exits_hint or set()
        fallback_ids = [n for n in reachable if n not in exits]
        fallback_tree = tree_for(fallback_ids)
        for i, node in enumerate(nodes):
            if node not in reachable:
                d2, j = fallback_tree.query(origin_xy[i])
                nodes[i], dist_m[i] = fallback_ids[j], d2

    return pd.DataFrame(
        {
            "tract_geoid": centroids.index,
            "origin_node": nodes,
            "origin_snap_km": np.round(dist_m / 1000.0, 2),
        }
    )


def _distances_to_exits(graph, exits: set) -> dict:
    """Travel time from every node to its nearest exit: one multi-source Dijkstra, reversed."""
    import networkx as nx

    reversed_graph = graph.reverse(copy=False)
    return nx.multi_source_dijkstra_path_length(reversed_graph, exits, weight="travel_time")


def _shortest_exit_paths(graph, exits: set, origins: list, dist: dict | None = None) -> dict:
    """Free-flow shortest path from each origin node to the nearest exit.

    Each origin's path is reconstructed greedily downhill on the distance field. Deterministic:
    ties break on node id.
    """
    if dist is None:
        dist = _distances_to_exits(graph, exits)

    def best_edge(u):
        candidates = []
        for _, v, k, data in graph.out_edges(u, keys=True, data=True):
            if v in dist:
                candidates.append((dist[v] + data["travel_time"], v, k))
        return min(candidates, default=None)

    paths: dict = {}
    for origin in origins:
        if origin not in dist:
            paths[origin] = None  # disconnected from every exit
            continue
        if origin in paths:
            continue
        path, u, guard = [], origin, 0
        while u not in exits and guard < 100_000:
            step = best_edge(u)
            if step is None:
                path = None
                break
            _, v, k = step
            path.append((u, v, k))
            u, guard = v, guard + 1
        paths[origin] = path
    return paths


def build_evacuation(*, refresh: bool = False, write: bool = True) -> pd.DataFrame:
    """Run the full bottleneck-attribution computation. See the module docstring.

    Returns:
        One row per tract: demand, vehicles per household, path length, the binding bottleneck's
        volume-to-capacity ratio and identity, ``evacuation_units_accommodatable`` (pro-rata),
        and ``evacuation_units_solo`` (upper bound).
    """
    from ingest.network import exit_nodes, load_network

    graph = load_network(refresh=refresh)
    exits = exit_nodes(graph)

    demand = evacuation_demand()
    county_vph = float(demand["vehicles"].sum() / demand["households"].sum())
    # Missing OR zero vehicles-per-household falls back to the county mean for the marginal
    # term. A handful of tracts report zero vehicles across all households (group-quarters
    # adjacency); taking that at face value would say added units cost nothing to evacuate,
    # which overstates capacity exactly where the data is least representative of new housing.
    demand["vehicles_per_household"] = (
        demand["vehicles_per_household"].replace(0.0, county_vph).fillna(county_vph)
    )

    dist = _distances_to_exits(graph, exits)
    origins = _tract_origins(graph, reachable=set(dist), exits_hint=exits)
    merged = origins.merge(demand, on="tract_geoid", how="left").fillna(
        {"households": 0, "vehicles": 0, "vehicles_per_household": county_vph}
    )

    paths = _shortest_exit_paths(graph, exits, merged["origin_node"].to_list(), dist=dist)

    # Pass 1: accumulate every tract's vehicles onto its path edges.
    load: dict = {}
    tract_paths: dict = {}
    for row in merged.itertuples():
        path = paths.get(row.origin_node)
        tract_paths[row.tract_geoid] = path
        if path is None or len(path) == 0:
            continue
        for edge in path:
            load[edge] = load.get(edge, 0.0) + float(row.vehicles)

    # Pass 2: per tract, the binding bottleneck and the units-addable headroom.
    rows = []
    for row in merged.itertuples():
        path = tract_paths[row.tract_geoid]
        if path is None:
            rows.append(
                {
                    "tract_geoid": row.tract_geoid,
                    "connected": False,
                    "clearance_hours": None,
                    "evacuation_units_per_hour": 0.0,
                    "evacuation_units_per_hour_solo": 0.0,
                }
            )
            continue

        if len(path) == 0:
            # Origin sits on the freeway mainline: no on-network link between the tract and the
            # exit set, so no shared bottleneck is measured. Discharge is bounded by one
            # three-lane mainline -- stated rather than silent.
            mainline = 3 * 2000.0
            uph = mainline / row.vehicles_per_household
            rows.append(
                {
                    "tract_geoid": row.tract_geoid,
                    "connected": True,
                    "households": int(row.households),
                    "vehicles": int(row.vehicles),
                    "vehicles_per_household": round(float(row.vehicles_per_household), 3),
                    "path_edges": 0,
                    "clearance_hours": 0.0,
                    "bottleneck_highway": "motorway",
                    "bottleneck_name": "at freeway mainline",
                    "bottleneck_capacity_vph": mainline,
                    "bottleneck_load": 0.0,
                    "evacuation_units_per_hour": round(uph, 1),
                    "evacuation_units_per_hour_solo": round(uph, 1),
                    "delta_clearance_min_per_100_units": round(
                        100 * row.vehicles_per_household / mainline * 60, 2
                    ),
                }
            )
            continue

        worst_ratio, worst_edge, min_cap = -1.0, path[0], float("inf")
        for edge in path:
            data = graph.edges[edge]
            capacity = float(data["capacity_vph"])
            ratio = load[edge] / capacity
            if ratio > worst_ratio:
                worst_ratio, worst_edge = ratio, edge
            min_cap = min(min_cap, capacity)

        clearance_hours = max(worst_ratio, 0.0)
        vph = float(row.vehicles_per_household)
        # Pro-rata discharge rate at the binding shared bottleneck. Algebra worth seeing once:
        # the tract's share of the bottleneck's hourly discharge is veh_t/load_b x cap_b, and
        # dividing by vehicles-per-household turns vehicles into dwelling units --
        #   (veh_t / load_b) x cap_b / vph  =  households_t / clearance_hours.
        # A tract that takes 9 hours to clear discharges one-ninth of its homes per hour.
        # Robust to the simultaneous-departure inflation in a way the headroom form is not:
        # see the module docstring's v1 note.
        uph = (
            (float(row.vehicles) / vph) / clearance_hours if clearance_hours > 0 else min_cap / vph
        )
        data = graph.edges[worst_edge]
        rows.append(
            {
                "tract_geoid": row.tract_geoid,
                "connected": True,
                "households": int(row.households),
                "vehicles": int(row.vehicles),
                "vehicles_per_household": round(vph, 3),
                "path_edges": len(path),
                "clearance_hours": round(clearance_hours, 3),
                "bottleneck_highway": str(
                    data.get("highway")
                    if not isinstance(data.get("highway"), list)
                    else data.get("highway")[0]
                ),
                "bottleneck_name": str(
                    data.get("name")
                    if not isinstance(data.get("name"), list)
                    else data.get("name")[0]
                ),
                "bottleneck_capacity_vph": float(data["capacity_vph"]),
                "bottleneck_load": round(load[worst_edge], 1),
                "evacuation_units_per_hour": round(float(uph), 1),
                "evacuation_units_per_hour_solo": round(min_cap / vph, 1),
                "delta_clearance_min_per_100_units": round(100 * vph / min_cap * 60, 2),
            }
        )

    out = (
        pd.DataFrame(rows)
        .merge(origins[["tract_geoid", "origin_snap_km"]], on="tract_geoid", how="left")
        .sort_values("tract_geoid", ignore_index=True)
    )
    if write:
        out.to_parquet(INTERIM / "evacuation_capacity.parquet", index=False)
        _write_ledger(graph, load, merged, tract_paths)
    return out


def _write_ledger(graph, load: dict, merged: pd.DataFrame, tract_paths: dict) -> None:
    """The bottleneck ledger: every loaded edge with capacity, load, and contributing tracts."""
    contributions: dict = {}
    for row in merged.itertuples():
        path = tract_paths.get(row.tract_geoid)
        if path is None or len(path) == 0 or row.vehicles <= 0:
            continue
        for edge in path:
            contributions.setdefault(edge, []).append((row.tract_geoid, float(row.vehicles)))

    rows = []
    for edge, edge_load in load.items():
        data = graph.edges[edge]
        contribs = sorted(contributions.get(edge, []), key=lambda t: -t[1])
        highway = data.get("highway")
        name = data.get("name")
        rows.append(
            {
                "u": edge[0],
                "v": edge[1],
                "highway": highway[0] if isinstance(highway, list) else highway,
                "name": name[0] if isinstance(name, list) else name,
                "lanes_out": data["lanes_out"],
                "lane_basis": data["lane_basis"],
                "capacity_vph": data["capacity_vph"],
                "load_vehicles": round(edge_load, 1),
                "vc_ratio": round(edge_load / data["capacity_vph"], 4),
                "n_tracts": len(contribs),
                "top_tracts": "; ".join(f"{t}:{v:.0f}" for t, v in contribs[:5]),
            }
        )
    ledger = pd.DataFrame(rows).sort_values("vc_ratio", ascending=False, ignore_index=True)
    ledger.to_parquet(INTERIM / "bottleneck_ledger.parquet", index=False)


def load_evacuation() -> pd.DataFrame:
    path = INTERIM / "evacuation_capacity.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return build_evacuation()
