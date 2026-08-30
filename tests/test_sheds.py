"""Tests for the shed-local binding rule and the shed machinery."""

from __future__ import annotations

import networkx as nx
import pytest

from metrics.evacuation import MAINLINE_CLASSES, binding_edge


def _graph():
    g = nx.MultiDiGraph()
    g.add_edge("a", "b", key=0, highway="residential", capacity_vph=600.0)
    g.add_edge("b", "c", key=0, highway="motorway", capacity_vph=6000.0)
    g.add_edge("c", "d", key=0, highway="primary", capacity_vph=900.0)
    return g


def test_binding_prefers_local_links_over_mainline() -> None:
    """A saturated mainline never becomes a tract's binding bottleneck — it is flagged."""
    g = _graph()
    path = [("a", "b", 0), ("b", "c", 0), ("c", "d", 0)]
    load = {("a", "b", 0): 600.0, ("b", "c", 0): 60000.0, ("c", "d", 0): 900.0}

    bind = binding_edge(g, path, load)

    assert g.edges[bind["edge"]]["highway"] not in MAINLINE_CLASSES
    assert bind["regional_contention"] is True
    # Among local links, primary at 900/900 = 1.0 equals residential 600/600; first-max wins
    # deterministically (residential comes first on the path).
    assert bind["edge"] == ("a", "b", 0)


def test_all_mainline_path_falls_back_to_overall_worst() -> None:
    g = nx.MultiDiGraph()
    g.add_edge("a", "b", key=0, highway="motorway", capacity_vph=6000.0)
    path = [("a", "b", 0)]
    bind = binding_edge(g, path, {("a", "b", 0): 12000.0})
    assert bind["edge"] == ("a", "b", 0)
    assert bind["regional_contention"] is False


def test_min_cap_spans_the_whole_path() -> None:
    g = _graph()
    path = [("a", "b", 0), ("b", "c", 0), ("c", "d", 0)]
    bind = binding_edge(g, path, {})
    assert bind["min_cap"] == 600.0


@pytest.mark.network
def test_every_routed_tract_belongs_to_exactly_one_shed() -> None:
    import pandas as pd

    from config import INTERIM

    sheds = pd.read_parquet(INTERIM / "evacuation_sheds.parquet")
    assert not sheds["tract_geoid"].duplicated().any()
    assert (sheds["shed_size"] >= 1).all()
    # Every tract is a member of its own shed.
    sample = sheds.sample(25, random_state=0)
    for row in sample.itertuples():
        assert row.tract_geoid in row.shed_members.split(";")


@pytest.mark.network
def test_fire_replay_has_the_cedar_validation() -> None:
    """The known-answer test: the Cedar Fire replay must surface Wildcat Canyon Road."""
    import pandas as pd

    from config import INTERIM

    chokes = pd.read_parquet(INTERIM / "fire_replay_chokepoints.parquet")
    cedar = chokes[chokes["fire"].str.startswith("CEDAR")]
    assert any("Wildcat Canyon" in str(link) for link in cedar["link"])
