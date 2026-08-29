"""The San Diego County road network — Phase 4's substrate.

One drivable network for the whole county, downloaded from OpenStreetMap through ``osmnx``,
cached as GraphML with its checksum in the manifest. **One graph, not nineteen**: shared
bottlenecks only exist when every tract is routed on the same network, which is the entire point
of the bottleneck-attribution design (docs/capacity_indicators.md 3.1). City boundaries never
touch this computation.

Each edge carries an **outbound lane count** and an **hourly capacity**, derived per the spec's
fallback hierarchy, with the tier recorded so every report can state what share of the network
rests on a real tag versus a default:

1. OSM ``lanes`` (with ``oneway`` handling) -- the measured tier;
2. OSM ``width`` / 3.3 m -- the derived tier;
3. a class default -- the assumed tier.

Per-lane hourly capacities are method constants with citations, not tuned parameters: the 1,900
pc/h/ln base saturation flow and the class-level capacity defaults follow the FHWA HPMS Field
Manual, Appendix N (https://www.fhwa.dot.gov/ohim/hpmsmanl/pdf/appn.pdf), the free federal
reproduction of the values the Highway Capacity Manual is known for; the licensed manual itself
is not used (Hard constraint 6, applied to methods).
"""

from __future__ import annotations

import networkx as nx
import osmnx as ox

import cache
from config import RAW

GRAPH_PATH = RAW / "osm_sandiego_drive.graphml"

#: Per-lane hourly capacity (passenger cars/hour/lane) by OSM highway class. Uninterrupted-flow
#: classes carry freeway-level values; signalized arterial classes carry the base saturation
#: flow of 1,900 pc/h/ln discounted by a 0.45-0.5 effective green ratio, per HPMS App. N's
#: capacity procedure. Local streets are discounted further for friction and stop control.
PER_LANE_CAPACITY: dict[str, int] = {
    "motorway": 2000,
    "motorway_link": 1500,
    "trunk": 1500,
    "trunk_link": 1200,
    "primary": 900,
    "primary_link": 900,
    "secondary": 850,
    "secondary_link": 850,
    "tertiary": 800,
    "tertiary_link": 800,
    "unclassified": 700,
    "residential": 600,
    "living_street": 300,
}
DEFAULT_PER_LANE_CAPACITY = 600

#: Class-default lane counts (total, both directions unless oneway), per the spec's tier 3.
CLASS_DEFAULT_LANES: dict[str, int] = {
    "motorway": 3,
    "trunk": 2,
    "primary": 2,
    "secondary": 2,
    "motorway_link": 1,
    "trunk_link": 1,
    "primary_link": 1,
    "secondary_link": 1,
    "tertiary": 1,
    "residential": 1,
    "unclassified": 1,
}

#: Metres of street width per lane, for the tier-2 fallback.
METERS_PER_LANE = 3.3


def _first(value):
    """OSM tags can arrive as lists after simplification; take the first scalar."""
    return value[0] if isinstance(value, list) else value


def _numeric(value) -> float | None:
    try:
        return float(str(_first(value)).split(";")[0].replace("m", "").strip())
    except (TypeError, ValueError):
        return None


def _outbound_lanes(data: dict) -> tuple[int, str]:
    """Outbound lane count for one directed edge, with the tier that produced it."""
    highway = str(_first(data.get("highway", "unclassified")))
    oneway = data.get("oneway") in (True, "yes", 1, "1", "-1")

    lanes = _numeric(data.get("lanes"))
    if lanes is not None and lanes > 0:
        out = lanes if oneway else max(lanes / 2.0, 1.0)
        return max(int(round(out)), 1), "lanes_tag"

    width = _numeric(data.get("width"))
    if width is not None and width > 0:
        total = max(int(round(width / METERS_PER_LANE)), 1)
        out = total if oneway else max(total // 2, 1)
        return out, "width_derived"

    total = CLASS_DEFAULT_LANES.get(highway, 1)
    out = total if oneway else max(total // 2, 1)
    return max(out, 1), "class_default"


def load_network(*, refresh: bool = False) -> nx.MultiDiGraph:
    """The county drive network with travel times, outbound lanes, and hourly capacities.

    Downloaded once from OpenStreetMap (Overpass) and cached as GraphML; the manifest records
    the checksum of the cached graph, which pins the extract. Edge attributes added here:
    ``lanes_out``, ``lane_basis`` (the fallback tier), ``capacity_vph``.
    """
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(RAW / "osmnx_cache")
    ox.settings.log_console = False

    if GRAPH_PATH.exists() and not refresh:
        graph = ox.load_graphml(GRAPH_PATH)
    else:
        graph = ox.graph_from_place("San Diego County, California, USA", network_type="drive")
        graph = ox.routing.add_edge_speeds(graph)
        graph = ox.routing.add_edge_travel_times(graph)
        ox.save_graphml(graph, GRAPH_PATH)
        cache.record_assembled(
            "osm_sandiego_drive",
            GRAPH_PATH,
            url="https://overpass-api.de/ (San Diego County, California; network_type=drive)",
            vintage="OpenStreetMap extract at fetch date (see fetched_utc)",
            notes=f"{len(graph)} nodes, {graph.number_of_edges()} edges; osmnx graph_from_place",
        )

    for _, _, data in graph.edges(data=True):
        lanes_out, basis = _outbound_lanes(data)
        highway = str(_first(data.get("highway", "unclassified")))
        data["lanes_out"] = lanes_out
        data["lane_basis"] = basis
        data["capacity_vph"] = lanes_out * PER_LANE_CAPACITY.get(highway, DEFAULT_PER_LANE_CAPACITY)
        if not isinstance(data.get("travel_time"), int | float):
            data["travel_time"] = float(data.get("travel_time", 1.0))
    return graph


def lane_basis_coverage(graph: nx.MultiDiGraph) -> dict[str, float]:
    """Share of edges (by count) whose lane figure came from each tier. Honesty accounting."""
    counts: dict[str, int] = {}
    for _, _, data in graph.edges(data=True):
        counts[data["lane_basis"]] = counts.get(data["lane_basis"], 0) + 1
    total = sum(counts.values())
    return {tier: n / total for tier, n in sorted(counts.items())}


def exit_nodes(graph: nx.MultiDiGraph) -> set:
    """The regional exit set: every node touching a motorway mainline edge.

    The spec's default is freeway mainline plus county boundary. **v1 simplification, stated
    plainly:** county-boundary exits (the two-lane highways leaving the county eastward) are not
    yet included, which makes far-east desert communities look worse than the spec's full exit
    set would. Recorded as an open item; the parameter is named in the methodology file.
    """
    exits = set()
    for u, v, data in graph.edges(data=True):
        if str(_first(data.get("highway", ""))) == "motorway":
            exits.add(u)
            exits.add(v)
    return exits
