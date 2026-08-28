"""Tests for the tract-scored allocator — milestone D1.2 acceptance criteria."""

from __future__ import annotations

import pandas as pd
import pytest

from allocate.model import MethodologyNotRunnable, _category_seed, allocate, to_jurisdictions
from allocate.params import Factor, Methodology


def _methodology(factors: tuple[Factor, ...], parameters: dict | None = None) -> Methodology:
    return Methodology(
        name="fixture",
        label="Synthetic fixture",
        geography="tract",
        replication_only=False,
        factors=factors,
        income_split={},
        parameters=parameters or {"floor_weight": 0.0, "mass_base": "units"},
        source_path=None,  # type: ignore[arg-type]
        raw={},
    )


FEATURES = pd.DataFrame(
    {
        "tract_geoid": ["t1", "t2", "t3", "t4"],
        "units": [100.0, 300.0, 500.0, 100.0],
        "opportunity_category": [
            "Highest Resource",
            "High Resource",
            "Low Resource",
            "Low Resource",
        ],
    }
)

RESTRICTED = Factor(
    name="high_resource_units",
    weight=1.0,
    source="fixture",
    description="units in high-resource tracts",
    column="units",
    applies_to=("very_low",),
    restrict_to_categories=("Highest Resource", "High Resource"),
)
UNRESTRICTED = Factor(
    name="all_units",
    weight=1.0,
    source="fixture",
    description="all units",
    column="units",
    applies_to=("above_moderate",),
)


def test_zero_sum_per_category() -> None:
    m = _methodology((RESTRICTED, UNRESTRICTED))
    rhnd = {"very_low": 1000, "above_moderate": 2000}
    result = allocate(m, rhnd, features=FEATURES, write=False)
    assert result["very_low"].sum() == pytest.approx(1000)
    assert result["above_moderate"].sum() == pytest.approx(2000)


def test_restriction_zeroes_excluded_tracts() -> None:
    m = _methodology((RESTRICTED, UNRESTRICTED))
    result = allocate(m, {"very_low": 1000, "above_moderate": 0}, features=FEATURES, write=False)
    # t3, t4 are Low Resource: with no floor they receive exactly nothing in very_low.
    assert result.loc[result["tract_geoid"].isin(["t3", "t4"]), "very_low"].sum() == 0
    # t1:t2 split 100:300.
    assert result.loc[result["tract_geoid"] == "t2", "very_low"].iloc[0] == pytest.approx(750)


def test_floor_gives_every_tract_mass() -> None:
    m = _methodology((RESTRICTED, UNRESTRICTED), {"floor_weight": 0.1, "mass_base": "units"})
    result = allocate(m, {"very_low": 1000, "above_moderate": 0}, features=FEATURES, write=False)
    low_resource = result[result["tract_geoid"].isin(["t3", "t4"])]["very_low"]
    assert (low_resource > 0).all()
    # Floor mass: 0.1 * 1000 * (500+100)/1000 = 60 units to the two Low Resource tracts.
    assert low_resource.sum() == pytest.approx(60)


def test_determinism() -> None:
    m = _methodology((RESTRICTED, UNRESTRICTED), {"floor_weight": 0.01, "mass_base": "units"})
    rhnd = {"very_low": 12345, "above_moderate": 54321}
    a = allocate(m, rhnd, features=FEATURES, write=False)
    b = allocate(m, rhnd, features=FEATURES, write=False)
    pd.testing.assert_frame_equal(a, b)


def test_replication_only_is_refused() -> None:
    from allocate.params import load_methodology

    archived = load_methodology("sixth_cycle")
    with pytest.raises(MethodologyNotRunnable, match="replication_only"):
        allocate(archived, {"very_low": 1}, features=FEATURES, write=False)


def test_missing_column_is_refused() -> None:
    bad = Factor(name="ghost", weight=1.0, source="s", description="d", column="not_a_column")
    with pytest.raises(MethodologyNotRunnable, match="not in the feature table"):
        allocate(_methodology((bad,)), {"very_low": 1}, features=FEATURES, write=False)


def test_weights_must_sum_to_one_per_category() -> None:
    half = Factor(
        name="half",
        weight=0.5,
        source="s",
        description="d",
        column="units",
        applies_to=("very_low",),
    )
    with pytest.raises(MethodologyNotRunnable, match="sum to 0.5"):
        _category_seed(FEATURES, _methodology((half,)), "very_low")


def test_factor_selecting_nothing_is_refused() -> None:
    empty = Factor(
        name="empty",
        weight=1.0,
        source="s",
        description="d",
        column="units",
        restrict_to_categories=("No Such Category",),
    )
    with pytest.raises(MethodologyNotRunnable, match="zero total mass"):
        _category_seed(FEATURES, _methodology((empty,)), "very_low")


# ---------------------------------------------------------------- real data


@pytest.mark.network
def test_resource_only_satisfies_all_hard_constraints() -> None:
    from allocate.params import load_methodology
    from config import RHND_6TH_CYCLE_BY_CATEGORY, RHND_6TH_CYCLE_TOTAL

    m = load_methodology("resource_only")
    tracts = allocate(m, RHND_6TH_CYCLE_BY_CATEGORY, write=False)
    juris = to_jurisdictions(tracts, RHND_6TH_CYCLE_BY_CATEGORY)

    assert int(juris["total"].sum()) == RHND_6TH_CYCLE_TOTAL
    for category, units in RHND_6TH_CYCLE_BY_CATEGORY.items():
        assert int(juris[category].sum()) == units
    assert (juris[list(RHND_6TH_CYCLE_BY_CATEGORY)] > 0).all().all()
    assert len(juris) == 19


@pytest.mark.network
def test_affh_baseline_dominated_by_high_resource_tracts() -> None:
    from allocate.model import affh_share
    from allocate.params import load_methodology
    from config import RHND_6TH_CYCLE_BY_CATEGORY

    m = load_methodology("resource_only")
    tracts = allocate(m, RHND_6TH_CYCLE_BY_CATEGORY, write=False)
    share = affh_share(tracts)
    # (1 - floor) plus the floor's own mass landing in High/Highest: strictly above 0.99.
    assert share > 0.99
