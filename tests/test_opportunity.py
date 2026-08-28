"""Tests for the Opportunity Map replication and the Capacity Map framework."""

from __future__ import annotations

import pandas as pd
import pytest

from metrics.capacity import (
    ALL_CAPACITY_INDICATORS,
    CAPACITY_DOMAINS,
    SCORED_INDICATORS,
    capacity_category_from_score,
    check_guardrails,
    check_orientation,
    score_capacity,
    scoring_set,
)
from metrics.opportunity import category_from_score

# ------------------------------------------------------------------ offline: banding


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (9, "Highest Resource"),
        (8, "Highest Resource"),
        (7, "High Resource"),
        (6, "High Resource"),
        (5, "Moderate Resource"),
        (4, "Moderate Resource"),
        (3, "Low Resource"),
        (0, "Low Resource"),
    ],
)
def test_opportunity_banding(score: int, expected: str) -> None:
    assert category_from_score(score) == expected


# ------------------------------------------------------------------ offline: capacity map


def test_every_capacity_indicator_passes_the_statutory_screen() -> None:
    """The Capacity Map must not contain a factor Gov. Code 65584.04(e)(2)(B) forbids."""
    assert check_guardrails() == []


def test_capacity_domains_mirror_the_statute() -> None:
    """Evacuation is its own domain, not a hazard footprint.

    Evacuation capacity is a network property: a dense neighbourhood with two narrow outlets
    evacuates badly whether or not it is in a fire zone, and a ridge tract inside a Very High
    Fire Hazard Severity Zone with four arterials may evacuate fine. Folding it into a hazard
    domain conflates the two.
    """
    assert [d.key for d in CAPACITY_DOMAINS] == [
        "evacuation",
        "infrastructure",
        "land",
        "hazard",
        "diagnostic",
    ]
    for domain in CAPACITY_DOMAINS:
        assert domain.statutory_text
        assert domain.indicators


def test_power_is_registered_but_never_scored() -> None:
    """Gov. Code 65584.04(e) names sewer and water. It does not name electrical capacity."""
    power = [i for i in ALL_CAPACITY_INDICATORS if i.name == "circuit_headroom"]
    assert len(power) == 1
    assert power[0].scored is False
    assert power[0] not in SCORED_INDICATORS
    assert "does not name" in power[0].statutory_basis


def test_every_scored_indicator_states_an_objective_measure() -> None:
    """'Absolute clarity' means a formula a reader can check, not a description."""
    for indicator in SCORED_INDICATORS:
        assert indicator.measure and ("/" in indicator.measure or "-" in indicator.measure)
        assert indicator.reported_as


def test_every_indicator_declares_a_source_and_statutory_basis() -> None:
    """Nothing enters the map without a citation; the appendix is generated from these."""
    for indicator in ALL_CAPACITY_INDICATORS:
        assert indicator.source and indicator.url and indicator.statutory_basis
        if not indicator.available:
            assert indicator.gap, f"{indicator.name} is unavailable but declares no gap"


def test_share_indicators_are_oriented_so_higher_is_more_capacity() -> None:
    good = pd.DataFrame({"share_outside_vhfhsz": [0.0, 0.5, 1.0]})
    assert check_orientation(good) == []

    inverted = pd.DataFrame({"share_outside_vhfhsz": [-0.2, 0.5, 1.4]})
    assert check_orientation(inverted)


def test_scoring_uses_only_indicators_complete_for_every_tract() -> None:
    """A tract scored on four indicators and one scored on six are not comparable."""
    table = pd.DataFrame(
        {
            "tract_geoid": ["a", "b", "c"],
            "share_land_unprotected": [0.9, 0.5, 0.1],
            "share_outside_floodway": [0.9, None, 0.1],  # incomplete
        }
    )
    usable, excluded = scoring_set(table)
    assert usable == ["share_land_unprotected"]
    assert "share_outside_floodway" in excluded

    scored = score_capacity(table)
    assert (scored["indicators_scored"] == 1).all()
    assert "share_outside_floodway" in scored["indicators_excluded"].iloc[0]


def test_scoring_refuses_when_no_indicator_is_ingested() -> None:
    """A capacity map with no capacity data must fail loudly, not score everything the same."""
    with pytest.raises(ValueError, match="no capacity indicator is complete"):
        score_capacity(pd.DataFrame({"tract_geoid": ["06073000100"]}))


def test_scoring_uses_the_opportunity_map_rule() -> None:
    """count(indicator >= regional median) + 1 — the rule verified against TCAC's own output."""
    table = pd.DataFrame(
        {
            "tract_geoid": ["a", "b", "c"],
            "share_land_unprotected": [0.9, 0.5, 0.1],
            "share_outside_floodway": [0.9, 0.5, 0.1],
        }
    )
    scored = score_capacity(table)
    # Medians are 0.5 for both indicators. Tract a is at or above on both -> 3;
    # b is exactly at the median on both, and "at or above" counts -> 3; c is below both -> 1.
    assert scored["capacity_score"].tolist() == [3, 3, 1]
    assert scored["indicators_scored"].tolist() == [2, 2, 2]


@pytest.mark.parametrize(
    ("score", "n", "expected"),
    [
        (1, 3, "Low Capacity"),
        (2, 3, "Moderate Capacity"),
        (3, 3, "High Capacity"),
        (4, 3, "Highest Capacity"),
        (7, 6, "Highest Capacity"),
        (5, 6, "High Capacity"),
        (3, 6, "Moderate Capacity"),
    ],
)
def test_capacity_banding_scales_with_indicator_count(score: int, n: int, expected: str) -> None:
    """Categories must mean the same thing as the map gains indicators in later phases."""
    assert capacity_category_from_score(score, n) == expected


# ------------------------------------------------------------------ network: replication


@pytest.mark.network
def test_opportunity_score_replicates_exactly() -> None:
    """Every TCAC-published San Diego tract with complete indicators must reproduce."""
    from metrics.opportunity import replication_summary

    summary = replication_summary()
    assert summary["exact"]
    assert summary["complete_matches"] == summary["complete_tracts"]


@pytest.mark.network
def test_category_banding_replicates_exactly() -> None:
    from metrics.opportunity import check_category_banding

    assert check_category_banding()["exact"]


@pytest.mark.network
def test_block_group_tracts_are_aggregated_not_dropped() -> None:
    """Dropping them would leave ~73,000 housing units unmapped, most of it in the county."""
    from ingest.opportunity_map import coverage

    cover = coverage()
    assert cover["block_group_aggregated"] > 0
    assert cover["uncovered_tracts"] <= 1
    assert cover["tcac_tracts"] + cover["uncovered_tracts"] == cover["region_tracts"]


@pytest.mark.network
def test_one_row_per_tract() -> None:
    from ingest.opportunity_map import load_opportunity_map

    table = load_opportunity_map()
    assert not table["tract_geoid"].duplicated().any()
