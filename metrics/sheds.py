"""Evacuation sheds — the objective zone geography — and the fire-perimeter replay.

A **shed** is the set of tracts whose evacuation routes converge on the same binding bottleneck
link, the way a watershed is the land draining to one river. Nobody draws the sheds: they are
implied by the road network, the measured demand, and the deterministic routing rule — the same
public inputs as everything else. Fire ignores city boundaries; so do sheds. And the shed is the
fire-relevant community by construction: it is precisely the set of households that will be in
your traffic jam.

Two outputs:

* :func:`build_sheds` — every tract's shed: the binding link, the co-members, the shared demand.
  Published so a resident can find their evacuation community by street name.
* :func:`replay_fires` — each large historical fire perimeter replayed as an evacuation (its
  tracts leave at once, the rest of the county drives normally), with the replay's chokepoints
  checked against the sheds' predictions. Validation zones nobody chose.
"""

from __future__ import annotations

import pandas as pd

from config import INTERIM
from ingest.fire_perimeters import load_fire_perimeters
from ingest.hazards import _block_points
from ingest.network import exit_nodes, load_network
from metrics.evacuation import (
    _distances_to_exits,
    _shortest_exit_paths,
    _tract_origins,
    binding_edge,
    evacuation_demand,
)


def _routing_state(*, refresh: bool = False) -> dict:
    """Graph, demand, per-tract paths, and county-wide link loads — one place, reused."""
    graph = load_network(refresh=refresh)
    exits = exit_nodes(graph)
    dist = _distances_to_exits(graph, exits)
    origins = _tract_origins(graph, reachable=set(dist), exits_hint=exits)

    demand = evacuation_demand()
    county_vph = float(demand["vehicles"].sum() / demand["households"].sum())
    demand = demand.copy()
    demand["vehicles_per_household"] = (
        demand["vehicles_per_household"].replace(0.0, county_vph).fillna(county_vph)
    )
    merged = origins.merge(demand, on="tract_geoid", how="left").fillna(
        {"households": 0, "vehicles": 0, "vehicles_per_household": county_vph}
    )

    paths = _shortest_exit_paths(graph, exits, merged["origin_node"].to_list(), dist=dist)
    tract_paths, load = {}, {}
    for row in merged.itertuples():
        path = paths.get(row.origin_node)
        tract_paths[row.tract_geoid] = path
        if path:
            for edge in path:
                load[edge] = load.get(edge, 0.0) + float(row.vehicles)
    return {"graph": graph, "merged": merged, "tract_paths": tract_paths, "load": load}


def _edge_users(tract_paths: dict, merged: pd.DataFrame) -> dict:
    """edge -> list of (tract, vehicles) whose evacuation routes traverse it."""
    vehicles = merged.set_index("tract_geoid")["vehicles"]
    users: dict = {}
    for tract, path in tract_paths.items():
        if not path:
            continue
        v = float(vehicles.get(tract, 0.0))
        for edge in path:
            users.setdefault(edge, []).append((tract, v))
    return users


def build_sheds(*, refresh: bool = False, state: dict | None = None) -> pd.DataFrame:
    """Assign every routed tract to its evacuation shed.

    Returns:
        One row per tract: ``tract_geoid``, ``shed_id`` (the binding link, named), ``shed_size``
        (tracts sharing it), ``shed_households``, ``shed_vehicles``, ``shed_members``
        (semicolon-joined tract GEOIDs — the evacuation community, publishable as-is).
    """
    st = state or _routing_state(refresh=refresh)
    graph, merged = st["graph"], st["merged"]
    users = _edge_users(st["tract_paths"], merged)
    households = merged.set_index("tract_geoid")["households"]

    rows = []
    for row in merged.itertuples():
        path = st["tract_paths"].get(row.tract_geoid)
        if not path:
            continue
        bind = binding_edge(graph, path, st["load"])
        edge = bind["edge"]
        data = graph.edges[edge]
        name = data.get("name", "unnamed")
        name = name[0] if isinstance(name, list) else name
        members = sorted({t for t, _ in users.get(edge, [])})
        rows.append(
            {
                "tract_geoid": row.tract_geoid,
                "shed_id": f"{name} [{edge[0]}-{edge[1]}-{edge[2]}]",
                "bottleneck_name": str(name),
                "shed_size": len(members),
                "shed_households": int(sum(households.get(t, 0) for t in members)),
                "shed_vehicles": round(sum(v for _, v in users.get(edge, [])), 0),
                "shed_members": ";".join(members),
            }
        )
    out = pd.DataFrame(rows).sort_values("tract_geoid", ignore_index=True)
    out.to_parquet(INTERIM / "evacuation_sheds.parquet", index=False)
    return out


def replay_fires(*, refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay each large historical fire as a zonal evacuation and score the shed predictions.

    For each perimeter: every tract the fire touched (any inhabited block point inside) departs
    at once; the rest of the county is absent. Link loads are recomputed for that scenario, each
    scenario tract's binding bottleneck found, and compared with the shed prediction from the
    county-wide analysis.

    Returns:
        ``(fires, chokepoints)`` — one row per fire with tract counts, households, and the
        match rate between shed-predicted and replay bottlenecks; and the top stressed links
        per fire.
    """
    st = _routing_state(refresh=refresh)
    graph, merged = st["graph"], st["merged"]
    sheds = build_sheds(state=st).set_index("tract_geoid")

    perimeters = load_fire_perimeters(refresh=refresh).to_crs("EPSG:3310")
    points = _block_points().to_crs("EPSG:3310")
    inhabited = points[points["housing_units_2020"] > 0]

    fire_rows, choke_rows = [], []
    for fire in perimeters.itertuples():
        hits = inhabited[inhabited.within(fire.geometry)]
        tracts = sorted(set(hits["tract_geoid"]))
        if not tracts:
            continue

        scenario_load: dict = {}
        vehicles = merged.set_index("tract_geoid")["vehicles"]
        for tract in tracts:
            path = st["tract_paths"].get(tract)
            if not path:
                continue
            for edge in path:
                scenario_load[edge] = scenario_load.get(edge, 0.0) + float(vehicles.get(tract, 0))

        households_by_tract = merged.set_index("tract_geoid")["households"]
        matches, name_matches, total, hh = 0, 0, 0, 0
        for tract in tracts:
            path = st["tract_paths"].get(tract)
            if not path:
                continue
            total += 1
            hh += int(households_by_tract.get(tract, 0))
            bind = binding_edge(graph, path, scenario_load)
            predicted = sheds.loc[tract, "shed_id"] if tract in sheds.index else None
            edge = bind["edge"]
            data = graph.edges[edge]
            name = data.get("name", "unnamed")
            name = name[0] if isinstance(name, list) else name
            if predicted == f"{name} [{edge[0]}-{edge[1]}-{edge[2]}]":
                matches += 1
            predicted_name = sheds.loc[tract, "bottleneck_name"] if tract in sheds.index else None
            # Corridor-level match: the same named road, any segment. Exact-edge matching
            # counts a different segment of Wildcat Canyon Road as a miss, which overstates
            # disagreement -- the corridor is the prediction a fire marshal would act on.
            if predicted_name is not None and str(predicted_name) == str(name):
                name_matches += 1

        ranked = sorted(
            scenario_load.items(), key=lambda kv: -kv[1] / graph.edges[kv[0]]["capacity_vph"]
        )
        seen_links: set = set()
        for edge, load_v in ranked:
            if len(seen_links) >= 5:
                break
            data = graph.edges[edge]
            name = data.get("name", "unnamed")
            name = name[0] if isinstance(name, list) else name
            if str(name) in seen_links:
                continue
            seen_links.add(str(name))
            choke_rows.append(
                {
                    "fire": f"{fire.fire_name} {int(fire.year)}",
                    "link": str(name),
                    "highway": str(data.get("highway")),
                    "queue_hours": round(load_v / float(data["capacity_vph"]), 1),
                    "load_vehicles": round(load_v, 0),
                }
            )
        fire_rows.append(
            {
                "fire": f"{fire.fire_name} {int(fire.year)}",
                "acres": round(float(fire.acres), 0),
                "tracts": total,
                "households": hh,
                "shed_prediction_match": round(matches / total, 3) if total else None,
                "corridor_match": round(name_matches / total, 3) if total else None,
            }
        )

    fires = pd.DataFrame(fire_rows).sort_values("acres", ascending=False, ignore_index=True)
    chokes = pd.DataFrame(choke_rows)
    fires.to_parquet(INTERIM / "fire_replay.parquet", index=False)
    chokes.to_parquet(INTERIM / "fire_replay_chokepoints.parquet", index=False)
    return fires, chokes
