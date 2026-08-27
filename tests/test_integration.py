"""Integration tests against the real downloaded data.

Marked ``network`` because they download from public sources. ``make test`` skips them;
``make test-all`` runs them. Each asserts one of the hard constraints on the real region rather
than on a fixture, because a constraint that only holds for synthetic data is not a constraint.
"""

from __future__ import annotations

import pandas as pd
import pytest

from config import INCOME_4, RHND_6TH_CYCLE_BY_CATEGORY, RHND_6TH_CYCLE_TOTAL

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def allocation() -> pd.DataFrame:
    from allocate.sixth_cycle import allocate_sixth_cycle

    return allocate_sixth_cycle()


def test_zero_sum_regional_total(allocation: pd.DataFrame) -> None:
    """Hard constraint 1: the run sums exactly to the RHND."""
    assert int(allocation["total"].sum()) == RHND_6TH_CYCLE_TOTAL


def test_zero_sum_by_income_category(allocation: pd.DataFrame) -> None:
    """Hard constraint 1: and exactly to HCD's determination in every category."""
    for category, expected in RHND_6TH_CYCLE_BY_CATEGORY.items():
        assert int(allocation[category].sum()) == expected


def test_every_jurisdiction_nonzero_in_every_category(allocation: pd.DataFrame) -> None:
    """Hard constraint 4 and Gov. Code Sec. 65584(d)(1)."""
    zeros = [
        (jurisdiction, category)
        for jurisdiction in allocation.index
        for category in INCOME_4
        if allocation.loc[jurisdiction, category] <= 0
    ]
    assert zeros == []


def test_nineteen_jurisdictions(allocation: pd.DataFrame) -> None:
    assert len(allocation) == 19


def test_replication_is_within_threshold() -> None:
    from report.replication import ABSOLUTE_TOLERANCE_UNITS, build

    summary = build(write=False)
    assert summary["passed"]
    assert summary["max_jurisdiction_error_units"] <= ABSOLUTE_TOLERANCE_UNITS


def test_open_data_portal_matches_the_adopted_plan() -> None:
    """Two independent renderings of the adopted allocation must agree."""
    from ingest.sixth_cycle import check_allocation_sources_agree

    check_allocation_sources_agree()


def test_crosswalk_weights_sum_to_one_per_tract() -> None:
    """Hard constraint 2: no tract may lose or gain weight when split across jurisdictions."""
    from ingest.crosswalk import load_crosswalk

    sums = load_crosswalk().groupby("tract_geoid")["weight"].sum()
    assert ((sums - 1.0).abs() < 1e-9).all()


def test_crosswalk_covers_all_nineteen_jurisdictions() -> None:
    from ingest.crosswalk import load_crosswalk
    from ingest.sixth_cycle import load_jurisdictions

    covered = set(load_crosswalk()["jurisdiction"])
    assert covered == set(load_jurisdictions()["jurisdiction"])


def test_roll_up_preserves_the_regional_total() -> None:
    """Apportioning tract values to jurisdictions must not create or destroy anything."""
    from ingest.crosswalk import load_crosswalk, roll_up_to_jurisdictions

    tracts = pd.DataFrame({"tract_geoid": sorted(load_crosswalk()["tract_geoid"].unique())})
    tracts["units"] = 100.0

    rolled = roll_up_to_jurisdictions(tracts, ["units"])

    assert rolled["units"].sum() == pytest.approx(tracts["units"].sum())
    assert len(rolled) == 19


def test_feature_table_covers_every_tract() -> None:
    from ingest.crosswalk import load_crosswalk
    from metrics.feature_table import load

    features = load()
    assert set(features["tract_geoid"]) == set(load_crosswalk()["tract_geoid"])
    assert not features["tract_geoid"].duplicated().any()


def test_allocation_is_deterministic() -> None:
    """Hard constraint 7: same inputs, byte-identical outputs."""
    from allocate.sixth_cycle import allocate_sixth_cycle

    pd.testing.assert_frame_equal(allocate_sixth_cycle(), allocate_sixth_cycle())
