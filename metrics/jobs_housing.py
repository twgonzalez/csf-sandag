"""Jobs-housing balance and jobs-housing fit.

These are two different questions and conflating them is the usual mistake.

**Balance** asks whether a place has roughly as much housing as it has jobs. It is a ratio of
counts and says nothing about who can afford what. A tract full of software offices and a tract
full of warehouses look the same to it.

**Fit** asks whether the housing a place has is affordable to the people who work there. A
jurisdiction can have a textbook balance of 1.0 and still house none of its own low-wage
workforce. Gov. Code Sec. 65584.04(e)(1) directs a COG to consider "the relationship between jobs
and housing", and Sec. 65584(d)(2) requires the allocation to promote "an improved intraregional
relationship between jobs and housing, including an improved balance between the number of
low-wage jobs and the number of housing units affordable to low-wage workers" -- that second
clause is fit, not balance, and it is the one a proprietary jobs dataset makes impossible to
check.
"""

from __future__ import annotations

import pandas as pd

from ingest.acs import estimate, load_table
from metrics.housing import housing_units
from metrics.jobs import WAGE_BAND_AFFORDABLE_RENT, jobs_by_wage_band

#: Upper bound of each ACS B25056 contract-rent category, in dollars per month. The top category
#: is open-ended ("$3,500 or more") and is given a nominal ceiling that is only used for ordering;
#: no cut point in this pipeline falls near it. ``B25056_003`` is "less than $100".
_RENT_CATEGORY_CEILING = {
    "B25056_003": 100,
    "B25056_004": 149,
    "B25056_005": 199,
    "B25056_006": 249,
    "B25056_007": 299,
    "B25056_008": 349,
    "B25056_009": 399,
    "B25056_010": 449,
    "B25056_011": 499,
    "B25056_012": 549,
    "B25056_013": 599,
    "B25056_014": 649,
    "B25056_015": 699,
    "B25056_016": 749,
    "B25056_017": 799,
    "B25056_018": 899,
    "B25056_019": 999,
    "B25056_020": 1_249,
    "B25056_021": 1_499,
    "B25056_022": 1_999,
    "B25056_023": 2_499,
    "B25056_024": 2_999,
    "B25056_025": 3_499,
    "B25056_026": 10_000,
}


def jobs_housing_balance() -> pd.DataFrame:
    """Jobs per housing unit, per tract.

    Rule:
        ``jobs_housing_balance = workplace jobs / total housing units``. A value above 1 means the
        tract holds more jobs than homes. Tracts with no housing units at all -- industrial parks,
        military installations, open space -- have an undefined ratio and are returned as null
        rather than as an arbitrarily large number, because a ratio with a zero denominator is not
        a large ratio, it is not a ratio.

    Source:
        Jobs from LODES WAC (unadjusted Q2 counts); housing units from ACS Table B25001.

    Returns:
        Columns ``tract_geoid``, ``jobs_total``, ``housing_units``, ``jobs_housing_balance``.
    """
    jobs = jobs_by_wage_band()[["tract_geoid", "jobs_total"]]
    homes = housing_units()[["tract_geoid", "housing_units"]]
    out = homes.merge(jobs, on="tract_geoid", how="left")
    out["jobs_total"] = out["jobs_total"].fillna(0)
    out["jobs_housing_balance"] = (out["jobs_total"] / out["housing_units"]).where(
        out["housing_units"] > 0
    )
    return out


def affordable_units_by_wage_band() -> pd.DataFrame:
    """Renter-occupied units affordable to a worker at the top of each lower wage band.

    Rule:
        A unit is affordable to a worker earning ``W`` per month if its contract rent is at most
        30% of ``W``. Applying the LODES band ceilings gives two cut points: $375/month for the
        CE01 band ($1,250/month earnings) and $1,000/month for the CE02 band ($3,333/month).
        Units are counted from the ACS contract-rent distribution, assigning each category by its
        upper bound, so the count is conservative -- a category straddling a cut point is excluded
        rather than split.

    Warning:
        Two limitations, both material, both deliberate rather than hidden:

        1. **Single earner.** See :func:`metrics.jobs.affordable_monthly_housing_cost`. A
           two-earner household at the CE01 band can afford roughly twice this rent.
        2. **Contract rent, not gross rent.** B25056 excludes tenant-paid utilities, so it
           understates what a household actually pays and therefore overstates the number of
           affordable units. Gross rent (B25063) would be the better table; it is not used here
           because the wage-to-rent cut points are defined against a rent-burden ratio that HUD
           applies to gross rent, and mixing the two would be worse than being consistently
           conservative. This is flagged in ``docs/status.md``.

        A version keyed to HCD's published State Income Limits rather than LODES wage bands would
        answer the statutory question more directly. That needs the HCD income-limits table, which
        is public but not yet ingested; see ``docs/status.md``, "AMI-based affordability".

    Source:
        ACS 5-Year, Table B25056 "Contract Rent". Wage bands from LODES.

    Returns:
        Columns ``tract_geoid``, ``units_affordable_to_ce01``, ``units_affordable_to_ce02``. The
        CE02 count includes the CE01 units, since a unit affordable at $375 is also affordable at
        $1,000.
    """
    rent = load_table("B25056")
    out = pd.DataFrame(index=rent.set_index("tract_geoid").index)

    for band, ceiling in WAGE_BAND_AFFORDABLE_RENT.items():
        variables = [v for v, top in _RENT_CATEGORY_CEILING.items() if top <= ceiling]
        column = "units_affordable_to_ce01" if "1250" in band else "units_affordable_to_ce02"
        out[column] = (
            sum(estimate(rent, v) for v in variables)
            if variables
            else pd.Series(0.0, index=out.index)
        )
    return out.reset_index()


def jobs_housing_fit() -> pd.DataFrame:
    """Lower-wage jobs per affordable unit, and the workforce housing gap in units.

    Rule:
        ``jobs_housing_fit = lower-wage jobs / units affordable to lower-wage workers``, where
        lower-wage is LODES CE01 + CE02 (jobs paying $3,333 a month or less) and the affordable
        stock is ``units_affordable_to_ce02`` from :func:`affordable_units_by_wage_band`. A value
        above 1 means the tract holds more lower-wage jobs than homes those workers could rent.

        ``workforce_housing_gap_units`` is the same thing as a count rather than a ratio:
        lower-wage jobs minus affordable units. Positive means a shortfall.

    Note:
        Fit is a *regional* diagnostic, not a per-tract obligation. A downtown tract will always
        show a large shortfall and a residential tract a large surplus, because jobs and homes are
        not meant to be co-located block by block. What matters is the pattern across a
        jurisdiction and, above all, whether the region's low-wage workers can live anywhere in it.

    Returns:
        Columns ``tract_geoid``, ``lower_wage_jobs``, ``units_affordable_to_ce02``,
        ``jobs_housing_fit``, ``workforce_housing_gap_units``.
    """
    jobs = jobs_by_wage_band()[["tract_geoid", "lower_wage_jobs"]]
    affordable = affordable_units_by_wage_band()[["tract_geoid", "units_affordable_to_ce02"]]

    out = affordable.merge(jobs, on="tract_geoid", how="outer")
    out["lower_wage_jobs"] = out["lower_wage_jobs"].fillna(0)
    out["units_affordable_to_ce02"] = out["units_affordable_to_ce02"].fillna(0)
    out["jobs_housing_fit"] = (out["lower_wage_jobs"] / out["units_affordable_to_ce02"]).where(
        out["units_affordable_to_ce02"] > 0
    )
    out["workforce_housing_gap_units"] = out["lower_wage_jobs"] - out["units_affordable_to_ce02"]
    return out.sort_values("tract_geoid", ignore_index=True)
