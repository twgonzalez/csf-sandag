"""Housing stock metrics from ACS 5-year estimates.

Every function here is a pure function of a Layer 1 frame. The ACS variable IDs are written out
in the docstrings so a planner can check any number against data.census.gov without reading code.
"""

from __future__ import annotations

import pandas as pd

from ingest.acs import combined_margin, estimate, load_table, sum_variables

#: Bedroom-count variables in ACS table B25041.
_BEDROOM_VARIABLES = {
    "B25041_002": "units_0_bedroom",
    "B25041_003": "units_1_bedroom",
    "B25041_004": "units_2_bedroom",
    "B25041_005": "units_3_bedroom",
    "B25041_006": "units_4_bedroom",
    "B25041_007": "units_5_or_more_bedrooms",
}

#: Bedrooms implied by each B25041 category, for the bedroom-count total. A studio is counted as
#: one sleeping room; "5 or more" is counted as 5, which understates the tail slightly and is
#: noted here rather than silently assumed.
_BEDROOMS_PER_UNIT = {
    "units_0_bedroom": 1,
    "units_1_bedroom": 1,
    "units_2_bedroom": 2,
    "units_3_bedroom": 3,
    "units_4_bedroom": 4,
    "units_5_or_more_bedrooms": 5,
}

#: B25070 categories at or above 30% of household income: HUD's cost-burden threshold.
_RENTER_BURDENED = ["B25070_007", "B25070_008", "B25070_009", "B25070_010"]

#: B25070 category at or above 50%: severe cost burden.
_RENTER_SEVERELY_BURDENED = ["B25070_010"]

#: B25091 categories at or above 30% for owners, both with and without a mortgage.
_OWNER_BURDENED = [
    "B25091_008",
    "B25091_009",
    "B25091_010",
    "B25091_011",
    "B25091_019",
    "B25091_020",
    "B25091_021",
    "B25091_022",
]

#: B25014 categories above 1.00 occupants per room, owner and renter: HUD's overcrowding
#: definition. More than 1.50 per room is severe overcrowding.
_OVERCROWDED = ["B25014_005", "B25014_006", "B25014_007", "B25014_011", "B25014_012", "B25014_013"]
_SEVERELY_OVERCROWDED = ["B25014_006", "B25014_007", "B25014_012", "B25014_013"]


def housing_units() -> pd.DataFrame:
    """Total housing units per tract.

    Rule:
        ACS table B25001, variable ``B25001_001``: all housing units, occupied and vacant. Vacant
        units are included because the jobs-housing balance asks how much housing *exists*, not
        how much is currently lived in.

    Source:
        ACS 5-Year, Table B25001 "Housing Units".

    Returns:
        Columns ``tract_geoid``, ``housing_units``, ``housing_units_moe``.
    """
    table = load_table("B25001")
    return pd.DataFrame(
        {
            "housing_units": estimate(table, "B25001_001"),
            "housing_units_moe": combined_margin(table, ["B25001_001"]),
        }
    ).reset_index()


def tenure() -> pd.DataFrame:
    """Owner- and renter-occupied units per tract.

    Rule:
        ACS table B25003: ``_002`` owner-occupied, ``_003`` renter-occupied. Their sum is
        occupied units, which is less than total housing units by the vacancy count.

    Source:
        ACS 5-Year, Table B25003 "Tenure".

    Returns:
        Columns ``tract_geoid``, ``occupied_units``, ``owner_occupied``, ``renter_occupied``.
    """
    table = load_table("B25003")
    return pd.DataFrame(
        {
            "occupied_units": estimate(table, "B25003_001"),
            "owner_occupied": estimate(table, "B25003_002"),
            "renter_occupied": estimate(table, "B25003_003"),
        }
    ).reset_index()


def bedrooms() -> pd.DataFrame:
    """Housing units by bedroom count, and total bedrooms, per tract.

    Rule:
        ACS table B25041 gives units in six bedroom-count categories. Total bedrooms multiplies
        each category by the bedroom count in :data:`_BEDROOMS_PER_UNIT`. Two approximations are
        baked in and should be read as such: a studio is counted as one sleeping room rather than
        zero, and the open-ended "5 or more" category is counted as exactly 5, which understates
        the largest units.

    Source:
        ACS 5-Year, Table B25041 "Bedrooms".

    Returns:
        Columns ``tract_geoid``, one per entry in :data:`_BEDROOM_VARIABLES`, and
        ``total_bedrooms``.
    """
    table = load_table("B25041")
    out = pd.DataFrame({name: estimate(table, var) for var, name in _BEDROOM_VARIABLES.items()})
    out["total_bedrooms"] = sum(out[name] * n for name, n in _BEDROOMS_PER_UNIT.items())
    return out.reset_index()


def cost_burden() -> pd.DataFrame:
    """Cost-burdened and severely cost-burdened households per tract.

    Rule:
        A household is cost-burdened when housing costs are 30% or more of household income, and
        severely cost-burdened at 50% or more -- HUD's long-standing thresholds, and the ones HCD
        uses in the RHNA determination. Renters come from B25070 (gross rent as a percentage of
        income); owners from B25091 (owner costs as a percentage of income), counting both
        mortgaged and unmortgaged units. Households whose ratio is "not computed" -- typically
        zero or negative reported income -- are excluded from both numerator and denominator
        rather than assumed unburdened.

    Source:
        ACS 5-Year, Tables B25070 and B25091.

    Returns:
        Columns ``tract_geoid``, ``renter_cost_burdened``, ``renter_severely_cost_burdened``,
        ``owner_cost_burdened``, ``cost_burdened_households``, and
        ``cost_burdened_households_moe``.
    """
    renters = load_table("B25070")
    owners = load_table("B25091")

    renter_burdened = sum_variables(renters, _RENTER_BURDENED)
    owner_burdened = sum_variables(owners, _OWNER_BURDENED)

    out = pd.DataFrame(
        {
            "renter_cost_burdened": renter_burdened,
            "renter_severely_cost_burdened": sum_variables(renters, _RENTER_SEVERELY_BURDENED),
            "owner_cost_burdened": owner_burdened,
            "cost_burdened_households": renter_burdened + owner_burdened,
        }
    )
    # Margins on the renter and owner components come from different tables, so they combine in
    # quadrature the same way the within-table components do.
    renter_moe = combined_margin(renters, _RENTER_BURDENED)
    owner_moe = combined_margin(owners, _OWNER_BURDENED)
    out["cost_burdened_households_moe"] = (renter_moe**2 + owner_moe**2) ** 0.5
    return out.reset_index()


def overcrowding() -> pd.DataFrame:
    """Overcrowded and severely overcrowded households per tract.

    Rule:
        More than 1.00 occupants per room is overcrowded; more than 1.50 is severely overcrowded.
        Both tenures are counted. This is the standard HUD definition and is one of the
        "housing need" factors Gov. Code Sec. 65584.04(e) directs a COG to consider.

    Source:
        ACS 5-Year, Table B25014 "Tenure by Occupants per Room".

    Returns:
        Columns ``tract_geoid``, ``overcrowded_households``, ``severely_overcrowded_households``.
    """
    table = load_table("B25014")
    return pd.DataFrame(
        {
            "overcrowded_households": sum_variables(table, _OVERCROWDED),
            "severely_overcrowded_households": sum_variables(table, _SEVERELY_OVERCROWDED),
        }
    ).reset_index()
