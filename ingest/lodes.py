"""LEHD Origin-Destination Employment Statistics (LODES).

LODES is the open-data answer to the proprietary jobs dataset the 6th-cycle methodology relied
on. It is published by the Census Bureau at census-block resolution, for free, with full
documentation, and it is the same dataset SANDAG itself uses to fill the QCEW "job spaces" in its
Employment Estimates -- just without the proprietary blending step.

Three things a reader needs to know before using these numbers:

**Reference period.** LODES counts a job if the worker was on the payroll on the reference date,
which is in the **second quarter (April-June)** of the vintage year. It is a single-quarter
snapshot, not an annual average. A beach resort, an agricultural packing shed, and a school
district all look different in Q2 than they do in January.
:mod:`metrics.adjustments.seasonality` converts this to annualised full-time equivalents.

**Workplace geocoding.** A job is assigned to the block of the employer's reporting unit, which
for a multi-site employer is often headquarters rather than the site where the work happens. A
school district's 4,000 employees can land on the block holding the district office.
:mod:`metrics.adjustments.multi_site` detects and corrects this.

**Earnings bands are nominal.** CE01/CE02/CE03 split jobs at $1,250 and $3,333 per month. Those
thresholds are fixed in nominal dollars and are *not* indexed across vintages, so they drift
against area median income every year. They are a usable proxy for the RHNA income categories
only after the explicit mapping in :mod:`metrics.jobs`, never directly.

Source:
    U.S. Census Bureau, Center for Economic Studies, LODES8.
    https://lehd.ces.census.gov/data/#lodes
    Technical documentation: https://lehd.ces.census.gov/data/lodes/LODES8/LODESTechDoc8.2.pdf
"""

from __future__ import annotations

import pandas as pd

import cache
from config import COUNTY_FIPS, INTERIM, SOURCES, STATE_FIPS

#: LODES earnings bands, as published. Monthly earnings, nominal dollars.
EARNINGS_BANDS = {
    "CE01": "jobs_earning_1250_or_less",
    "CE02": "jobs_earning_1251_to_3333",
    "CE03": "jobs_earning_over_3333",
}

#: LODES NAICS sector groups. Retained in full because the QCEW reconciliation and the
#: seasonality curves both work sector by sector.
SECTORS = {
    "CNS01": "agriculture_forestry_fishing_hunting",
    "CNS02": "mining_quarrying_oil_gas",
    "CNS03": "utilities",
    "CNS04": "construction",
    "CNS05": "manufacturing",
    "CNS06": "wholesale_trade",
    "CNS07": "retail_trade",
    "CNS08": "transportation_warehousing",
    "CNS09": "information",
    "CNS10": "finance_insurance",
    "CNS11": "real_estate_rental_leasing",
    "CNS12": "professional_scientific_technical",
    "CNS13": "management_of_companies",
    "CNS14": "administrative_support_waste",
    "CNS15": "educational_services",
    "CNS16": "health_care_social_assistance",
    "CNS17": "arts_entertainment_recreation",
    "CNS18": "accommodation_food_services",
    "CNS19": "other_services",
    "CNS20": "public_administration",
}

#: Blocks in San Diego County start with this 5-digit state+county FIPS prefix.
_COUNTY_PREFIX = f"{STATE_FIPS}{COUNTY_FIPS}"


def _read_block_file(source_key: str, geocode_column: str, *, refresh: bool) -> pd.DataFrame:
    """Read one LODES block file, filter to San Diego County, and tidy the column names."""
    path = cache.fetch(SOURCES[source_key], refresh=refresh)
    keep = [geocode_column, "C000", *EARNINGS_BANDS, *SECTORS]
    df = pd.read_csv(
        path, compression="gzip", usecols=keep, dtype={geocode_column: str}, low_memory=False
    )
    df = df[df[geocode_column].str.startswith(_COUNTY_PREFIX)].copy()
    return df.rename(
        columns={geocode_column: "block_geoid", "C000": "jobs_total", **EARNINGS_BANDS, **SECTORS}
    )


def _to_tract(blocks: pd.DataFrame) -> pd.DataFrame:
    """Aggregate block rows to 2020 tracts.

    The tract GEOID is the first 11 characters of the block GEOID by construction, so this needs
    no crosswalk and cannot disagree with one.
    """
    out = blocks.copy()
    out["tract_geoid"] = out["block_geoid"].str[:11]
    value_columns = [c for c in out.columns if c not in ("block_geoid", "tract_geoid")]
    return (
        out.groupby("tract_geoid", as_index=False)[value_columns]
        .sum()
        .sort_values("tract_geoid", ignore_index=True)
    )


def load_workplace_jobs(*, refresh: bool = False, by: str = "tract") -> pd.DataFrame:
    """Jobs counted at the workplace (LODES WAC).

    This is the open-data replacement for the "Total Jobs" column of the 6th-cycle methodology's
    Table 2.

    Args:
        refresh: Re-download even if cached.
        by: ``"tract"`` or ``"block"``. Block level is needed by the multi-site correction, which
            works on employer sites; everything else uses tracts.

    Returns:
        One row per geography. Columns: the geography id, ``jobs_total``, one column per entry in
        :data:`EARNINGS_BANDS`, and one per entry in :data:`SECTORS`. All counts are Q2 job
        counts, not annualised.
    """
    blocks = _read_block_file("lodes_wac", "w_geocode", refresh=refresh)
    out = blocks if by == "block" else _to_tract(blocks)
    out.to_parquet(INTERIM / f"lodes_wac_{by}.parquet", index=False)
    return out


def load_residence_jobs(*, refresh: bool = False, by: str = "tract") -> pd.DataFrame:
    """Jobs counted at the worker's residence (LODES RAC).

    Paired with :func:`load_workplace_jobs`, this gives the two halves of the jobs-housing
    relationship: where the work is, and where the workers sleep.

    Args:
        refresh: Re-download even if cached.
        by: ``"tract"`` or ``"block"``.

    Returns:
        Same schema as :func:`load_workplace_jobs`, counted at the residence block.
    """
    blocks = _read_block_file("lodes_rac", "h_geocode", refresh=refresh)
    out = blocks if by == "block" else _to_tract(blocks)
    out.to_parquet(INTERIM / f"lodes_rac_{by}.parquet", index=False)
    return out


def load_commute_flows(*, refresh: bool = False) -> pd.DataFrame:
    """Tract-to-tract commute flows for workers employed in San Diego County (LODES OD).

    Both the ``main`` file (home and work both in California) and the ``aux`` file (home out of
    state, work in California) are read, so a job filled by a worker living in Riverside County or
    across the border is not silently dropped.

    Args:
        refresh: Re-download even if cached.

    Returns:
        Columns ``home_tract_geoid``, ``work_tract_geoid``, ``jobs_total`` and one column per
        earnings band. Rows are restricted to flows whose **workplace** is in San Diego County;
        the home end may be anywhere.
    """
    frames = []
    for key in ("lodes_od_main", "lodes_od_aux"):
        path = cache.fetch(SOURCES[key], refresh=refresh)
        df = pd.read_csv(
            path,
            compression="gzip",
            usecols=["w_geocode", "h_geocode", "S000", "SE01", "SE02", "SE03"],
            dtype={"w_geocode": str, "h_geocode": str},
            low_memory=False,
        )
        frames.append(df[df["w_geocode"].str.startswith(_COUNTY_PREFIX)])

    od = pd.concat(frames, ignore_index=True)
    od["work_tract_geoid"] = od["w_geocode"].str[:11]
    od["home_tract_geoid"] = od["h_geocode"].str[:11]
    out = (
        od.groupby(["home_tract_geoid", "work_tract_geoid"], as_index=False)[
            ["S000", "SE01", "SE02", "SE03"]
        ]
        .sum()
        .rename(
            columns={
                "S000": "jobs_total",
                "SE01": "jobs_earning_1250_or_less",
                "SE02": "jobs_earning_1251_to_3333",
                "SE03": "jobs_earning_over_3333",
            }
        )
        .sort_values(["home_tract_geoid", "work_tract_geoid"], ignore_index=True)
    )
    out.to_parquet(INTERIM / "lodes_od_tract.parquet", index=False)
    return out
