"""Replication of SANDAG's adopted 6th-cycle allocation.

This is the validation milestone. It is deliberately kept out of the general tract-scored
allocator planned as ``allocate/model.py``, because
the adopted 6th-cycle method scores *jurisdictions* directly -- station counts and jurisdiction
job totals -- which Hard constraint 2 forbids for any methodology this pipeline would propose.
It is here to prove the arithmetic in ``allocate/`` is right, not to be adopted.

The adopted rule, assembled from the *Final 6th Cycle RHNA Plan* (2020-07-10):

1. 65% of the RHND is allocated on transit access; of that, 75% by share of Rail & Rapid stations
   and 25% by share of major transit stops (Plan pp. 16-18).
2. 35% is allocated by share of total jobs (Plan p. 19).
3. Those two components give each jurisdiction a total. The total is split across the four income
   categories by the inverse-ratio equity adjustment (Plan p. 22, and Methodology FAQ #15).

Step 3 as published does not produce a valid allocation on its own: the equity shares do not sum
to 1.0 within a jurisdiction, and nothing in the document forces the four category columns to
match HCD's Determination. **The missing step is a biproportional fit to both margins.** It is
not stated anywhere in the adopted methodology or plan, and it moves real units -- reconstructing
the allocation without it misses cells by up to 987 units. Recovering it required inferring it
from the published output. That is the verification gap this project exists to close, in
miniature.
"""

from __future__ import annotations

import pandas as pd

from allocate.equity import equity_seed
from allocate.reconcile import fit_to_margins, round_preserving_totals
from config import (
    INCOME_4,
    RHND_6TH_CYCLE_BY_CATEGORY,
    RHND_6TH_CYCLE_SHARES,
    RHND_6TH_CYCLE_TOTAL,
)
from ingest.sixth_cycle import (
    SIXTH_CYCLE_JOBS_SHARE,
    SIXTH_CYCLE_RAIL_RAPID_SHARE_OF_TRANSIT,
    SIXTH_CYCLE_TRANSIT_SHARE,
    load_household_income_counts,
    load_jobs_counts,
    load_transit_counts,
)


def component_units(rhnd_total: int = RHND_6TH_CYCLE_TOTAL) -> dict[str, float]:
    """Units carried by each component of the 6th-cycle methodology.

    Returns:
        Keys ``rail_rapid``, ``major_transit_stops``, ``jobs``. With the adopted RHND of 171,685
        these are 83,696.375, 27,898.79 and 60,089.75, which SANDAG published rounded to 83,696,
        27,899 and 60,090.
    """
    transit = rhnd_total * SIXTH_CYCLE_TRANSIT_SHARE
    rail_rapid = transit * SIXTH_CYCLE_RAIL_RAPID_SHARE_OF_TRANSIT
    return {
        "rail_rapid": rail_rapid,
        "major_transit_stops": transit - rail_rapid,
        "jobs": rhnd_total * SIXTH_CYCLE_JOBS_SHARE,
    }


def jurisdiction_totals(
    *, jobs_column: str = "total_jobs_adopted", rhnd_total: int = RHND_6TH_CYCLE_TOTAL
) -> pd.Series:
    """Total units per jurisdiction from the transit and jobs components.

    Args:
        jobs_column: ``total_jobs_adopted`` reproduces the adopted allocation;
            ``total_jobs_draft`` reproduces the draft allocation issued for appeal, before the
            military multi-site correction. See :func:`ingest.sixth_cycle.load_jobs_counts`.
        rhnd_total: Regional determination to distribute.

    Returns:
        Jurisdiction-indexed units, summing to ``rhnd_total``.
    """
    transit = load_transit_counts().set_index("jurisdiction")
    jobs = load_jobs_counts().set_index("jurisdiction")[jobs_column]
    units = component_units(rhnd_total)

    return (
        units["rail_rapid"] * transit["rail_rapid_stations"] / transit["rail_rapid_stations"].sum()
        + units["major_transit_stops"]
        * transit["major_transit_stops"]
        / transit["major_transit_stops"].sum()
        + units["jobs"] * jobs / jobs.sum()
    ).rename("units")


def allocate_sixth_cycle(
    *,
    jobs_column: str = "total_jobs_adopted",
    rhnd_total: int = RHND_6TH_CYCLE_TOTAL,
    apply_equity: bool = True,
    reconcile: bool = True,
    integer: bool = True,
) -> pd.DataFrame:
    """Run the adopted 6th-cycle methodology end to end.

    Args:
        jobs_column: Which published jobs table to use; see :func:`jurisdiction_totals`.
        rhnd_total: Regional determination to distribute.
        apply_equity: Apply the inverse-ratio equity adjustment. Setting this False seeds every
            jurisdiction with the flat regional income shares, which is the counterfactual the
            sensitivity report uses to price the adjustment.
        reconcile: Fit to both margins. Setting this False normalises each jurisdiction's row on
            its own, reproducing the methodology exactly as written -- and missing HCD's income
            category totals, which is how the omission was detected.
        integer: Round to whole units with the largest-remainder method.

    Returns:
        Jurisdiction-indexed matrix with one column per category in :data:`config.INCOME_4` and a
        ``total`` column.
    """
    totals = jurisdiction_totals(jobs_column=jobs_column, rhnd_total=rhnd_total)

    households = load_household_income_counts().set_index("jurisdiction")
    shares = households[INCOME_4].div(households["total_households"], axis=0)
    regional = pd.Series(RHND_6TH_CYCLE_SHARES).reindex(INCOME_4)

    if apply_equity:
        preferences = equity_seed(shares, regional)
    else:
        preferences = pd.DataFrame(
            [regional.to_numpy()] * len(shares), index=shares.index, columns=INCOME_4
        )

    seed = preferences.reindex(totals.index).mul(totals, axis=0)

    # HCD's Determination by category, scaled if the caller is running a different RHND.
    # The published counts are used rather than the rounded percentages in Table 3; see
    # config.RHND_6TH_CYCLE_BY_CATEGORY for why the two disagree by up to 74 units.
    column_totals = pd.Series(RHND_6TH_CYCLE_BY_CATEGORY).reindex(INCOME_4).astype("float64")
    column_totals *= rhnd_total / column_totals.sum()

    if reconcile:
        result = fit_to_margins(seed, totals, column_totals)
    else:
        result = seed.div(seed.sum(axis=1), axis=0).mul(totals, axis=0)

    if integer:
        targets = (
            column_totals.round().astype("int64")
            if reconcile
            else result.sum(axis=0).round().astype("int64")
        )
        result = round_preserving_totals(result, targets)

    result["total"] = result[INCOME_4].sum(axis=1)
    return result
