"""6th-cycle RHNA baseline: the adopted allocation and the inputs that produced it.

Everything the replication milestone validates against lives here.

Two kinds of thing are ingested:

1. **The adopted allocation** (:func:`load_adopted_allocation`), from SANDAG's open-data portal.
   Machine-readable, downloaded fresh on every run. This is ground truth.
2. **The published inputs** (:func:`load_transit_counts`, :func:`load_jobs_counts`,
   :func:`load_household_income_counts`), transcribed from Tables 1, 2 and 4 of the adopted
   methodology PDF into ``data/reference/``.

The second group deserves a warning. Tables 1 and 2 are published *outputs of proprietary
models* -- the SANDAG Activity Based Model and the SANDAG Employment Estimates. SANDAG published
the 19 jurisdiction totals; it did not publish the models. Replicating the 6th cycle therefore
requires taking those 19 numbers on faith, which is precisely the verification gap this project
exists to close. No 7th-cycle parameter file may depend on them; see ``docs/status.md``.

Source:
    San Diego Association of Governments, *6th Cycle Regional Housing Needs Assessment
    Methodology* (Final, adopted November 22, 2019).
    https://www.sandag.org/-/media/SANDAG/Documents/PDF/projects-and-programs/regional-initiatives/housing-land-use/regional-housing-needs-assessment/6th-cycle-regional-housing-needs-assessment-methodology-2019-11-22.pdf
"""

from __future__ import annotations

import json

import pandas as pd

import cache
from config import (
    INCOME_4,
    INTERIM,
    REFERENCE,
    RHND_6TH_CYCLE_TOTAL,
    SANDAG_INCOME_LABELS,
    SOURCES,
)

# ---------------------------------------------------------------------------------------
# The adopted rule, as numbers. Every constant below is quoted from the methodology document.
# ---------------------------------------------------------------------------------------

#: "Of the total housing units, 65% will be allocated to jurisdictions with access to transit"
#: -- 6th Cycle RHNA Methodology, p. 2, item 1. 65% of 171,685 = 111,595 units (p. 3).
SIXTH_CYCLE_TRANSIT_SHARE = 0.65

#: "Within the housing units allocated for jurisdictions with access to transit, 75% of the units
#: will be allocated to jurisdictions with rail stations and Rapid bus stations" -- p. 2, item 2.
#: 75% of 111,595 = 83,696 units (p. 4).
SIXTH_CYCLE_RAIL_RAPID_SHARE_OF_TRANSIT = 0.75

#: "Of the total housing units, 35% will be allocated to jurisdictions based on the total number
#: of jobs in their jurisdiction" -- p. 2, item 3. 35% of 171,685 = 60,090 units (p. 5).
SIXTH_CYCLE_JOBS_SHARE = 0.35

#: Unit counts as published, used to check that our arithmetic matches SANDAG's rounding.
SIXTH_CYCLE_PUBLISHED_UNITS = {
    "transit_total": 111_595,
    "rail_rapid": 83_696,
    "major_transit_stops": 27_899,
    "jobs": 60_090,
}


def verify_source_documents() -> None:
    """Confirm both cited 6th-cycle PDFs still hash to the values pinned in ``config.SOURCES``.

    The checksum check is the whole reason the transcriptions in ``data/reference/`` are
    trustworthy: if SANDAG reissues either document, the run fails loudly rather than silently
    validating against numbers that no longer appear in the cited source.

    Raises:
        cache.ChecksumMismatch: If either PDF has changed.
    """
    cache.fetch(SOURCES["sandag_methodology_6th"])
    cache.fetch(SOURCES["sandag_rhna6_plan"])


def _reference(name: str) -> pd.DataFrame:
    """Read a transcribed reference table, after confirming the source PDFs are unchanged."""
    verify_source_documents()
    return pd.read_csv(REFERENCE / name)


def load_transit_counts() -> pd.DataFrame:
    """Rail & Rapid station and Major Transit Stop counts by jurisdiction.

    Rule (6th Cycle RHNA Methodology, p. 3):
        *Rail & Rapid (R&R) Stations*: stations served by rail (NCTD COASTER, NCTD SPRINTER, MTS
        Trolley including planned Mid-Coast stations) and Rapid bus routes (NCTD BREEZE 350; MTS
        Rapid 215, 225, 235; MTS Rapid Express 280, 290).
        *Major Transit Stops*: the intersection of two or more major local bus routes with a
        service frequency of 15 minutes or less during morning and afternoon peak periods.
        Stop pairs on either side of a road count as one. A station serving several routes counts
        once.

    Source:
        SANDAG, *Final 6th Cycle RHNA Plan* (2020-07-10), Table 4.1 (Transit Data), p. 17;
        identical to Table 1 of the *6th Cycle RHNA Methodology* (2019-11-22), p. 4. The
        appeals process did not change these counts. Underlying data: SANDAG Activity Based
        Model, Release v14.0.1, Forecast Year 2025 No Build (Reference Scenario #242) for R&R
        stations; Forecast Year 2020 (Reference Scenario #243) for major transit stops.
        **Both are proprietary model outputs.**

    Returns:
        One row per jurisdiction, columns ``jurisdiction``, ``rail_rapid_stations``,
        ``major_transit_stops``. Regional totals are 154 and 140 respectively.
    """
    return _reference("sixth_cycle_transit.csv")


def load_jobs_counts() -> pd.DataFrame:
    """Total jobs by jurisdiction, before and after the 6th-cycle appeals correction.

    Rule (6th Cycle RHNA Methodology, p. 5):
        "The jobs data consists of all job types and includes jobs that are classified as a
        primary source of income, which can be part-time or full-time, year-round or seasonal."

    Two columns are returned because the appeals process changed this input rather than
    transferring units between jurisdictions:

    ``total_jobs_draft``
        Table 2 of the *6th Cycle RHNA Methodology* (2019-11-22), p. 5. Regional total 1,656,001.
        Produces the draft allocation issued for appeal.
    ``total_jobs_adopted``
        Table 4.2 of the *Final 6th Cycle RHNA Plan* (2020-07-10), p. 20. Regional total
        1,656,199. Produces the adopted allocation.

    The correction, quoted from the Plan, p. 14:
        Silver Strand Training Complex (Coronado) and Naval Outlying Landing Field (Imperial
        Beach) "have at most 99 active duty military jobs according to DMDC data"; the totals had
        "erroneously treated both SSTC and NOLF as remote stations of Naval Base San Diego 32nd
        Street", so those jobs are reattributed to San Diego. Separately, Naval Air Station North
        Island jobs are split by land area, "approximately 80.5% ... within the City of Coronado
        and 19.5% ... within the City of San Diego."

    This is a **multi-site employer correction** -- the same defect that
    ``metrics/adjustments/multi_site.py`` is specified to detect from open data, and which is not
    yet built. In the 6th cycle it was found by a phone call to Naval Facilities Engineering
    Command, four months after the draft allocation was issued, and only because Coronado could
    afford to appeal. That is the case for computing it in the open.

    Source:
        SANDAG Employment Estimates: a blend of EDD QCEW job spaces filled with a five-year
        average of Census LODES, supplemented by San Diego Military Advisory Council and Defense
        Manpower Data Center counts (Navy ship billets assigned to homeport), validated against
        EDD Labor Market Information county totals. **The blend is proprietary; only these 19
        totals are public.** ``metrics/jobs.py`` builds the open-data replacement.

    Returns:
        Columns ``jurisdiction``, ``total_jobs_draft``, ``total_jobs_adopted``.
    """
    return _reference("sixth_cycle_jobs.csv")


def load_household_income_counts() -> pd.DataFrame:
    """Existing households by income category and jurisdiction, for the equity adjustment.

    Rule (6th Cycle RHNA Methodology, p. 6 and Table 3):
        Categories are shares of the regional area median income of $66,529 as provided by HCD:
        very low is under 50% of AMI, low is 50-80%, moderate is 80-120%, above moderate is over
        120%.

    Source:
        SANDAG, *6th Cycle RHNA Methodology*, Table 4 (Households per Income Category), p. 7;
        reprinted unchanged as Table 4.4 of the *Final 6th Cycle RHNA Plan*, p. 22.
        Underlying data: ACS 2012-2016 5-Year, Table B19001. This is the one 6th-cycle input that
        is fully public and reproducible.

    Note:
        Six rows in the published table have income categories that sum to one unit more or less
        than the published household total (Carlsbad, El Cajon, Poway, San Diego, Santee, Vista).
        This is rounding in SANDAG's own table. The transcription is faithful to the document and
        the discrepancy is left in place rather than silently corrected; the equity adjustment
        uses category shares, which are unaffected at this magnitude.

    Returns:
        One row per jurisdiction, columns ``jurisdiction``, ``total_households``, and one column
        per category in :data:`config.INCOME_4`.
    """
    return _reference("sixth_cycle_households.csv")


def load_jurisdictions() -> pd.DataFrame:
    """The 19 SANDAG jurisdictions, with the name each source uses for them.

    The unincorporated county is a jurisdiction for RHNA purposes under Gov. Code Sec. 65584 and
    has no Census place GEOID; it is defined residually as the part of San Diego County outside
    any incorporated place.

    Returns:
        Columns ``jurisdiction`` (our stable key), ``name``, ``sandag_open_data_name``,
        ``methodology_pdf_name``, ``place_geoid``, ``kind``.
    """
    df = pd.read_csv(REFERENCE / "jurisdictions.csv", dtype={"place_geoid": "string"})
    if len(df) != 19:
        raise ValueError(f"expected 19 jurisdictions, found {len(df)}")
    return df


def load_adopted_allocation(*, refresh: bool = False) -> pd.DataFrame:
    """The adopted 6th-cycle RHNA allocation, by jurisdiction and income category.

    This is the validation target for the replication milestone. It is downloaded fresh from
    SANDAG's open-data portal rather than transcribed, because it is already machine-readable.

    The portal also publishes ``rhna_progress`` (permits issued against the allocation). That
    column is deliberately dropped: Hard constraint 5 and Gov. Code Sec. 65584.04(e)(2)(B)
    forbid prior production from entering any factor, and the safest way to honour that is for
    the number never to reach the feature table at all.

    Source:
        SANDAG Open Data Portal, "6th Cycle RHNA by Jurisdiction - Long Format", dataset
        ``t9sh-dzf3``. Planning period 2021-04-30 to 2029-04-30.

    Returns:
        Long format: ``jurisdiction``, ``income_category``, ``units``. 76 rows.

    Raises:
        ValueError: If the download does not sum to the RHND of 171,685, or does not cover 19
            jurisdictions in 4 categories. Either means the portal changed under us.
    """
    path = cache.fetch(SOURCES["sandag_rhna6_allocations"], refresh=refresh)
    records = json.loads(path.read_text())
    raw = pd.DataFrame.from_records(records)

    names = load_jurisdictions().set_index("sandag_open_data_name")["jurisdiction"]
    out = pd.DataFrame(
        {
            "jurisdiction": raw["jurisdiction"].str.strip().map(names),
            "income_category": raw["income_level"].map(SANDAG_INCOME_LABELS),
            "units": pd.to_numeric(raw["rhna"]).astype("int64"),
        }
    )

    if out["jurisdiction"].isna().any():
        unknown = sorted(set(raw.loc[out["jurisdiction"].isna(), "jurisdiction"]))
        raise ValueError(f"unmapped jurisdiction names from SANDAG open data: {unknown}")
    if out["income_category"].isna().any():
        unknown = sorted(set(raw.loc[out["income_category"].isna(), "income_level"]))
        raise ValueError(f"unmapped income labels from SANDAG open data: {unknown}")

    total = int(out["units"].sum())
    if total != RHND_6TH_CYCLE_TOTAL:
        raise ValueError(
            f"adopted allocation sums to {total:,}, expected the 6th-cycle RHND of "
            f"{RHND_6TH_CYCLE_TOTAL:,}. The open-data dataset has changed."
        )
    if out["jurisdiction"].nunique() != 19 or out["income_category"].nunique() != 4:
        raise ValueError(
            f"expected 19 jurisdictions x 4 categories, got "
            f"{out['jurisdiction'].nunique()} x {out['income_category'].nunique()}"
        )

    out = out.sort_values(["jurisdiction", "income_category"], ignore_index=True)
    out.to_parquet(INTERIM / "sixth_cycle_adopted_allocation.parquet", index=False)
    return out


def adopted_allocation_wide() -> pd.DataFrame:
    """The adopted allocation as a jurisdiction-by-category matrix, with a ``total`` column."""
    wide = (
        load_adopted_allocation()
        .pivot(index="jurisdiction", columns="income_category", values="units")
        .reindex(columns=INCOME_4)
    )
    wide.columns.name = None
    wide["total"] = wide.sum(axis=1)
    return wide


def load_published_allocation() -> pd.DataFrame:
    """The adopted allocation as printed in the Final RHNA Plan, for cross-checking the portal.

    This duplicates :func:`load_adopted_allocation` on purpose. The open-data portal is a
    convenience layer that SANDAG can revise; Table 4.7 of the adopted Plan is the legal
    instrument. :func:`check_allocation_sources_agree` asserts they still match, which turns any
    future silent revision of the portal into a failed run.

    Source:
        SANDAG, *Final 6th Cycle RHNA Plan* (2020-07-10), Table 4.7 (Allocation per Income
        Category), p. 26.

    Returns:
        Jurisdiction-indexed matrix with one column per category in :data:`config.INCOME_4`.
    """
    verify_source_documents()
    df = pd.read_csv(REFERENCE / "sixth_cycle_allocation_published.csv").set_index("jurisdiction")
    return df.reindex(columns=INCOME_4)


def check_allocation_sources_agree() -> None:
    """Assert the open-data portal and the adopted Plan report the same allocation.

    Raises:
        ValueError: If any of the 76 cells disagree, with the offending cells listed.
    """
    portal = adopted_allocation_wide()[INCOME_4]
    plan = load_published_allocation().reindex(index=portal.index)
    diff = portal - plan
    if (diff != 0).any().any():
        offenders = diff[(diff != 0).any(axis=1)]
        raise ValueError(
            "SANDAG open-data portal disagrees with Table 4.7 of the adopted RHNA Plan:\n"
            f"{offenders.to_string()}"
        )
