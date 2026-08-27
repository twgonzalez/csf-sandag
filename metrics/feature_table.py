"""Assemble the single tract-level feature table that Layer 3 allocates against.

One row per 2020 census tract in San Diego County. Every column comes from a named metric
function whose docstring states its rule and cites its source, and the provenance of each is
recorded in :data:`COLUMN_SOURCES` so the methodology appendix can be generated from it rather
than maintained by hand.

Nothing in this module decides anything. It joins.
"""

from __future__ import annotations

import pandas as pd

from config import PROCESSED
from ingest.crosswalk import load_crosswalk
from metrics.housing import bedrooms, cost_burden, housing_units, overcrowding, tenure
from metrics.jobs import jobs_by_wage_band, resident_workers
from metrics.jobs_housing import (
    affordable_units_by_wage_band,
    jobs_housing_balance,
    jobs_housing_fit,
)

#: Where each feature column comes from. Consumed by ``report/appendix.py``.
COLUMN_SOURCES: dict[str, str] = {
    "housing_units": "ACS 5-Year Table B25001",
    "housing_units_moe": "ACS 5-Year Table B25001 (margin of error)",
    "occupied_units": "ACS 5-Year Table B25003",
    "owner_occupied": "ACS 5-Year Table B25003",
    "renter_occupied": "ACS 5-Year Table B25003",
    "total_bedrooms": "ACS 5-Year Table B25041, weighted by bedroom count",
    "cost_burdened_households": "ACS 5-Year Tables B25070 and B25091, 30% of income threshold",
    "overcrowded_households": "ACS 5-Year Table B25014, over 1.00 occupants per room",
    "jobs_total": "LODES WAC, Q2 unadjusted",
    "lower_wage_jobs": "LODES WAC, CE01 + CE02",
    "resident_workers_total": "LODES RAC, Q2 unadjusted",
    "jobs_housing_balance": "LODES WAC / ACS B25001",
    "jobs_housing_fit": "LODES WAC CE01+CE02 / ACS B25056 units under $1,000 contract rent",
    "workforce_housing_gap_units": "LODES WAC CE01+CE02 minus affordable units",
}


def build(*, write: bool = True) -> pd.DataFrame:
    """Build the tract feature table.

    Args:
        write: Write the result to ``data/processed/tract_features.parquet``.

    Returns:
        One row per tract, indexed by ``tract_geoid``, with every metric column and the
        jurisdiction each tract predominantly falls in.

    Raises:
        ValueError: If the assembled table does not cover every tract in the crosswalk. A tract
            missing from the feature table would silently receive zero units, so this is a hard
            failure rather than a fill.
    """
    crosswalk = load_crosswalk()
    tracts = pd.DataFrame({"tract_geoid": sorted(crosswalk["tract_geoid"].unique())})

    parts = [
        housing_units(),
        tenure(),
        bedrooms()[["tract_geoid", "total_bedrooms"]],
        cost_burden()[["tract_geoid", "cost_burdened_households", "cost_burdened_households_moe"]],
        overcrowding(),
        jobs_by_wage_band(),
        resident_workers(),
        affordable_units_by_wage_band(),
        jobs_housing_balance()[["tract_geoid", "jobs_housing_balance"]],
        jobs_housing_fit()[["tract_geoid", "jobs_housing_fit", "workforce_housing_gap_units"]],
    ]

    table = tracts
    for part in parts:
        table = table.merge(part, on="tract_geoid", how="left", validate="one_to_one")

    # The predominant jurisdiction is for labelling and sorting only. Allocations are rolled up
    # with the full split weights by ingest.crosswalk.roll_up_to_jurisdictions, never with this.
    predominant = (
        crosswalk.sort_values(["tract_geoid", "weight"], ascending=[True, False])
        .drop_duplicates("tract_geoid")
        .set_index("tract_geoid")["jurisdiction"]
    )
    table["predominant_jurisdiction"] = table["tract_geoid"].map(predominant)

    missing = set(crosswalk["tract_geoid"]) - set(table["tract_geoid"])
    if missing:
        raise ValueError(
            f"{len(missing)} tracts in the crosswalk are absent from the feature table"
        )

    # Job and unit counts are genuine zeros where a source has no row for a tract; ratios are not.
    count_columns = [
        c
        for c in table.columns
        if c.startswith(("jobs_", "units_", "resident_", "lower_wage"))
        and not c.endswith(("balance", "fit"))
    ]
    table[count_columns] = table[count_columns].fillna(0)

    table = table.sort_values("tract_geoid", ignore_index=True)
    if write:
        table.to_parquet(PROCESSED / "tract_features.parquet", index=False)
    return table


def load() -> pd.DataFrame:
    """Read the cached feature table, building it if it does not exist yet."""
    path = PROCESSED / "tract_features.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return build()
