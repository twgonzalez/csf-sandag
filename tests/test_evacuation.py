"""Tests for the evacuation network machinery — synthetic graphs, no downloads."""

from __future__ import annotations

import networkx as nx

from ingest.network import _outbound_lanes, exit_nodes
from metrics.evacuation import _shortest_exit_paths

# ------------------------------------------------------------------ lane fallback tiers


def test_lanes_tag_wins_and_splits_bidirectional() -> None:
    lanes, basis = _outbound_lanes({"highway": "primary", "lanes": "4"})
    assert (lanes, basis) == (2, "lanes_tag")  # 4 total, bidirectional -> 2 out


def test_oneway_keeps_all_lanes() -> None:
    lanes, basis = _outbound_lanes({"highway": "primary", "lanes": "3", "oneway": "yes"})
    assert (lanes, basis) == (3, "lanes_tag")


def test_width_fallback_at_3_3_meters_per_lane() -> None:
    lanes, basis = _outbound_lanes({"highway": "residential", "width": "6.6"})
    assert (lanes, basis) == (1, "width_derived")  # 2 total -> 1 out


def test_class_default_last_resort() -> None:
    lanes, basis = _outbound_lanes({"highway": "motorway", "oneway": "yes"})
    assert (lanes, basis) == (3, "class_default")
    lanes, basis = _outbound_lanes({"highway": "residential"})
    assert (lanes, basis) == (1, "class_default")


def test_list_tags_take_first_value() -> None:
    lanes, basis = _outbound_lanes({"highway": ["primary", "secondary"], "lanes": ["2", "4"]})
    assert (lanes, basis) == (1, "lanes_tag")


# ------------------------------------------------------------------ routing


def _toy_graph() -> nx.MultiDiGraph:
    """a -> b -> EXIT, and c -> b (funnel: a and c share edge b->EXIT)."""
    graph = nx.MultiDiGraph()
    for u, v, tt in [("a", "b", 1.0), ("b", "x", 1.0), ("c", "b", 1.0)]:
        graph.add_edge(u, v, key=0, travel_time=tt, highway="primary")
    graph.add_edge("x", "sink", key=0, travel_time=1.0, highway="motorway")
    return graph


def test_exit_nodes_are_motorway_touching() -> None:
    assert exit_nodes(_toy_graph()) == {"x", "sink"}


def test_paths_reach_nearest_exit_and_share_the_funnel() -> None:
    graph = _toy_graph()
    paths = _shortest_exit_paths(graph, {"x"}, ["a", "c"])
    assert paths["a"] == [("a", "b", 0), ("b", "x", 0)]
    assert paths["c"] == [("c", "b", 0), ("b", "x", 0)]
    # both routes share (b, x): the funnel edge carries both tracts' demand.


def test_disconnected_origin_is_none_not_crash() -> None:
    graph = _toy_graph()
    graph.add_node("island")
    paths = _shortest_exit_paths(graph, {"x"}, ["island"])
    assert paths["island"] is None


def test_origin_already_at_exit_gets_empty_path() -> None:
    paths = _shortest_exit_paths(_toy_graph(), {"x"}, ["x"])
    assert paths["x"] == []
