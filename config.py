"""Pinned data vintages, source URLs, and region constants.

This is the only file that names an external URL or a data vintage. Changing a vintage here
changes it everywhere, and the change shows up in the generated methodology appendix, which is
what HCD reviews under Gov. Code Sec. 65584.04(f).

Every entry carries the date it was last verified to resolve. Nothing here is proprietary: each
URL is fetchable by anyone with a browser and no login (Hard constraint 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RAW = DATA / "raw"  # byte-for-byte downloads, never edited
INTERIM = DATA / "interim"  # per-source tidy parquet (Layer 1 output)
PROCESSED = DATA / "processed"  # tract feature table, allocations (Layers 2-3)
REFERENCE = DATA / "reference"  # tables transcribed from cited PDFs, committed to the repo
PARAMS = ROOT / "params"
REPORTS = ROOT / "reports"

for _d in (RAW, INTERIM, PROCESSED, REPORTS):
    _d.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------------------
# Region
# --------------------------------------------------------------------------------------

STATE_FIPS = "06"
COUNTY_FIPS = "073"  # San Diego County
STATE_ABBR = "ca"

#: The SANDAG region is San Diego County: 18 incorporated cities plus the unincorporated county.
#: Gov. Code Sec. 65584 makes the county itself a jurisdiction for the unincorporated area.
N_JURISDICTIONS = 19

#: Projected CRS for all distance and area work. NAD83 / California Albers (meters).
#: Chosen because it is equal-area, which matters for the hazard-share and land-area metrics.
WORKING_CRS = "EPSG:3310"
GEOGRAPHIC_CRS = "EPSG:4326"

#: Census tract vintage. Hard constraint 2 fixes this at 2020; TIGER files from 2021 onward
#: all carry 2020-vintage tract boundaries.
TRACT_VINTAGE = 2020


# --------------------------------------------------------------------------------------
# Source registry
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Source:
    """One public data source, pinned to a vintage.

    Attributes:
        key: Stable identifier used for cache filenames and report citations.
        url: Direct download URL. Must resolve without authentication.
        vintage: The data year or release the URL is pinned to.
        publisher: Who publishes it, as it should appear in a citation.
        title: Human-readable name, as it should appear in a citation.
        landing: Human-browsable page documenting the file, for a reader who wants context.
        verified: ISO date this URL was last confirmed to return HTTP 200.
        sha256: Expected checksum, where the publisher guarantees a stable file. ``None`` means
            the file is versioned by the publisher without a stable hash; the checksum of what
            was actually downloaded is still recorded in the run log.
        notes: Anything a planner reading the appendix needs to know about the file.
    """

    key: str
    url: str
    vintage: str
    publisher: str
    title: str
    landing: str
    verified: str
    sha256: str | None = None
    notes: str = ""


#: Latest LODES release and vintage. LODES8 uses 2020-vintage census blocks, which is what
#: Hard constraint 2 requires. Vintage 2023 is the newest year published for California as of
#: the verification date below.
LODES_RELEASE = "LODES8"
LODES_VINTAGE = "2023"

#: American Community Survey 5-year vintage. 2023 is used rather than 2024 so that every table
#: in the pipeline shares one vintage; see docs/status.md before changing.
ACS_VINTAGE = "2023"

#: TIGER/Line vintage for boundary files.
TIGER_VINTAGE = "2023"


def _lodes(kind: str, segment: str, jobtype: str = "JT00") -> str:
    """Build a LODES download URL.

    Args:
        kind: ``wac`` (workplace), ``rac`` (residence), or ``od`` (origin-destination).
        segment: Workforce segment, e.g. ``S000`` (all jobs) or ``SE01``/``SE02``/``SE03``
            (earnings bands). For ``od`` this is ``main`` or ``aux`` instead.
        jobtype: ``JT00`` is all jobs; see the LODES technical documentation.
    """
    base = f"https://lehd.ces.census.gov/data/lodes/{LODES_RELEASE}/{STATE_ABBR}/{kind}"
    if kind == "od":
        return f"{base}/{STATE_ABBR}_od_{segment}_{jobtype}_{LODES_VINTAGE}.csv.gz"
    return f"{base}/{STATE_ABBR}_{kind}_{segment}_{jobtype}_{LODES_VINTAGE}.csv.gz"


LODES_DOC = "https://lehd.ces.census.gov/data/lodes/LODES8/LODESTechDoc8.2.pdf"

#: LODES earnings bands. These are the only wage split LODES publishes, and they are nominal
#: dollars that are NOT indexed to inflation across vintages. Treated as a proxy for the RHNA
#: income categories only after the explicit mapping in metrics/jobs.py.
LODES_EARNINGS_SEGMENTS = {
    "SE01": "Jobs with earnings $1,250/month or less",
    "SE02": "Jobs with earnings $1,251/month to $3,333/month",
    "SE03": "Jobs with earnings greater than $3,333/month",
}

SOURCES: dict[str, Source] = {
    # ---------------------------------------------------------------- validation baseline
    "sandag_rhna6_allocations": Source(
        key="sandag_rhna6_allocations",
        url="https://opendata.sandag.org/resource/t9sh-dzf3.json?$limit=5000",
        vintage="6th Cycle (2021-2029), adopted 2020-07-10",
        publisher="San Diego Association of Governments",
        title="6th Cycle RHNA by Jurisdiction - Long Format",
        landing="https://opendata.sandag.org/Land-and-People-/6th-Cycle-RHNA-by-Jurisdiction-Long-Format/t9sh-dzf3",
        verified="2026-08-27",
        notes=(
            "76 rows = 19 jurisdictions x 4 income categories. The ``rhna`` column is the "
            "adopted final allocation and sums to 171,685. The ``rhna_progress`` column is "
            "permits issued to date and is NOT used by this pipeline -- Hard constraint 5 "
            "forbids prior production from entering any factor."
        ),
    ),
    "sandag_rhna6_plan": Source(
        key="sandag_rhna6_plan",
        url=(
            "https://www.sandag.org/-/media/SANDAG/Documents/PDF/projects-and-programs/"
            "regional-initiatives/housing-land-use/"
            "6th-cycle-regional-housing-needs-assessment-plan-2020-07-10.pdf"
        ),
        vintage="Final, adopted 2020-07-10 (Resolution 2021-02)",
        publisher="San Diego Association of Governments",
        title="Final 6th Cycle Regional Housing Needs Assessment Plan",
        landing=(
            "https://www.sandag.org/projects-and-programs/regional-initiatives/"
            "housing-and-land-use/regional-housing-needs-assessment"
        ),
        verified="2026-08-27",
        sha256="e04319b2695c037b1aef4efe2770ecaf2848307b53725d0dc9fbc270f91dbb3f",
        notes=(
            "The document that produced the adopted allocation. Table 4.1 (transit) is "
            "unchanged from the methodology; Table 4.2 (jobs) carries the post-appeal military "
            "jobs correction; Table 4.7 is the adopted allocation. Because the appeals changed "
            "an INPUT rather than transferring units, this Plan -- not the November 2019 "
            "methodology -- is the primary reference for the replication milestone."
        ),
    ),
    "sandag_methodology_6th": Source(
        key="sandag_methodology_6th",
        url=(
            "https://www.sandag.org/-/media/SANDAG/Documents/PDF/projects-and-programs/"
            "regional-initiatives/housing-land-use/regional-housing-needs-assessment/"
            "6th-cycle-regional-housing-needs-assessment-methodology-2019-11-22.pdf"
        ),
        vintage="Final, adopted 2019-11-22",
        publisher="San Diego Association of Governments",
        title="6th Cycle Regional Housing Needs Assessment Methodology",
        landing=(
            "https://www.sandag.org/projects-and-programs/regional-initiatives/"
            "housing-and-land-use/regional-housing-needs-assessment"
        ),
        verified="2026-08-27",
        sha256="d96716fc4234dc6c26a575da5ecfc63194c975e3276590c8f7b3f13c73630e32",
        notes=(
            "Source of the adopted 6th-cycle rule and of Tables 1, 2 and 4, which are the only "
            "public form of the SANDAG ABM and Employment Estimates inputs. Transcribed into "
            "data/reference/ and verified against this PDF's checksum."
        ),
    ),
    # ---------------------------------------------------------------- geography
    "lodes_xwalk": Source(
        key="lodes_xwalk",
        url=f"https://lehd.ces.census.gov/data/lodes/{LODES_RELEASE}/{STATE_ABBR}/{STATE_ABBR}_xwalk.csv.gz",
        vintage=f"{LODES_RELEASE} (2020-vintage blocks)",
        publisher="U.S. Census Bureau, Center for Economic Studies",
        title="LODES Geographic Crosswalk, California",
        landing="https://lehd.ces.census.gov/data/",
        verified="2026-08-27",
        notes=(
            "Authoritative block -> tract (``trct``) and block -> incorporated place "
            "(``stplc``) assignment. Blocks with stplc 9999999 are unincorporated and belong "
            "to the County jurisdiction for RHNA purposes."
        ),
    ),
    "tiger_blocks_2020": Source(
        key="tiger_blocks_2020",
        url=f"https://www2.census.gov/geo/tiger/TIGER{TRACT_VINTAGE}/TABBLOCK20/tl_2020_{STATE_FIPS}_tabblock20.zip",
        vintage="2020 Census tabulation blocks",
        publisher="U.S. Census Bureau",
        title="TIGER/Line Shapefile, 2020 Census Tabulation Blocks, California",
        landing="https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
        verified="2026-08-27",
        notes=(
            "Carries HOUSING20 (2020 Census housing units) and POP20 per block. Used to split "
            "tracts that cross a jurisdiction boundary by residential-unit share rather than "
            "by area, as Hard constraint 2 requires. ~382 MB; downloaded once and cached. "
            "Chosen over the Census Data API because the API now requires a registration key "
            "and this file does not (see docs/status.md, 'Census API key')."
        ),
    ),
    "tiger_places": Source(
        key="tiger_places",
        url=f"https://www2.census.gov/geo/tiger/TIGER{TIGER_VINTAGE}/PLACE/tl_{TIGER_VINTAGE}_{STATE_FIPS}_place.zip",
        vintage=TIGER_VINTAGE,
        publisher="U.S. Census Bureau",
        title="TIGER/Line Shapefile, Incorporated Places, California",
        landing="https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
        verified="2026-08-27",
        notes="Jurisdiction boundaries for the 18 incorporated cities in the region.",
    ),
    "tiger_tracts": Source(
        key="tiger_tracts",
        url=f"https://www2.census.gov/geo/tiger/TIGER{TIGER_VINTAGE}/TRACT/tl_{TIGER_VINTAGE}_{STATE_FIPS}_tract.zip",
        vintage=f"{TIGER_VINTAGE} (2020-vintage tract boundaries)",
        publisher="U.S. Census Bureau",
        title="TIGER/Line Shapefile, Census Tracts, California",
        landing="https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
        verified="2026-08-27",
    ),
    "tiger_county": Source(
        key="tiger_county",
        url=f"https://www2.census.gov/geo/tiger/TIGER{TIGER_VINTAGE}/COUNTY/tl_{TIGER_VINTAGE}_us_county.zip",
        vintage=TIGER_VINTAGE,
        publisher="U.S. Census Bureau",
        title="TIGER/Line Shapefile, Counties",
        landing="https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
        verified="2026-08-27",
    ),
    # ---------------------------------------------------------------- opportunity (AFFH)
    "tcac_opportunity_map": Source(
        key="tcac_opportunity_map",
        url="https://www.treasurer.ca.gov/sites/default/files/2025-11/summary_file.zip",
        vintage="2026 map, adopted December 2025",
        publisher=(
            "California Tax Credit Allocation Committee and "
            "California Department of Housing and Community Development"
        ),
        title="CTCAC/HCD Opportunity Map, Statewide Summary Table",
        landing="https://www.treasurer.ca.gov/ctcac/opportunity",
        verified="2026-08-27",
        sha256="70c102bc41620308803e7d84f914555b4adae883554b234df4320142449527f2",
        notes=(
            "Contains final_opp_2026_public.xlsx: every input indicator, every regional median, "
            "the composite Opportunity Score, the Opportunity Category, and the High-Poverty & "
            "Segregated flag, for 11,337 California tracts and block groups. Because TCAC "
            "publishes the inputs alongside the outputs, the score is exactly reproducible -- "
            "see metrics/opportunity.py. Note the publisher serves this at a generic filename "
            "(summary_file.zip) with no year in the path, so the pinned checksum is the only "
            "thing distinguishing the 2026 file from a future reissue."
        ),
    ),
    "tcac_opportunity_methodology": Source(
        key="tcac_opportunity_methodology",
        url="https://www.treasurer.ca.gov/sites/default/files/2025-11/Draft-2026-OM-Methodology.pdf",
        vintage="2026 map methodology",
        publisher="California Tax Credit Allocation Committee and California HCD",
        title="Methodology for the 2026 CTCAC/HCD Opportunity Map",
        landing="https://www.treasurer.ca.gov/ctcac/opportunity",
        verified="2026-08-27",
        notes=(
            "The publisher serves this under a 'Draft-2026' filename although the accompanying "
            "data file is named final_opp_2026_public.xlsx. Naming inconsistency is the "
            "publisher's, not ours."
        ),
    ),
    # ---------------------------------------------------------------- jobs
    "lodes_wac": Source(
        key="lodes_wac",
        url=_lodes("wac", "S000"),
        vintage=f"{LODES_RELEASE}, {LODES_VINTAGE}",
        publisher="U.S. Census Bureau, Center for Economic Studies",
        title="LEHD Origin-Destination Employment Statistics, Workplace Area Characteristics",
        landing="https://lehd.ces.census.gov/data/#lodes",
        verified="2026-08-27",
        notes=(
            "Jobs counted at the WORKPLACE block. Reference period is the second quarter "
            "(April-June) of the vintage year, so a single-quarter snapshot -- not an annual "
            "average. Annualising it to FTE is specified as metrics/adjustments/seasonality.py, "
            "which is NOT YET BUILT -- see docs/status.md."
        ),
    ),
    "lodes_rac": Source(
        key="lodes_rac",
        url=_lodes("rac", "S000"),
        vintage=f"{LODES_RELEASE}, {LODES_VINTAGE}",
        publisher="U.S. Census Bureau, Center for Economic Studies",
        title="LEHD Origin-Destination Employment Statistics, Residence Area Characteristics",
        landing="https://lehd.ces.census.gov/data/#lodes",
        verified="2026-08-27",
        notes="Jobs counted at the worker's RESIDENCE block. Q2 reference period, as WAC.",
    ),
    "lodes_od_main": Source(
        key="lodes_od_main",
        url=_lodes("od", "main"),
        vintage=f"{LODES_RELEASE}, {LODES_VINTAGE}",
        publisher="U.S. Census Bureau, Center for Economic Studies",
        title="LEHD Origin-Destination Employment Statistics, Origin-Destination (main)",
        landing="https://lehd.ces.census.gov/data/#lodes",
        verified="2026-08-27",
        notes="Commute flows where both home and work are in California. Q2 reference period.",
    ),
    "lodes_od_aux": Source(
        key="lodes_od_aux",
        url=_lodes("od", "aux"),
        vintage=f"{LODES_RELEASE}, {LODES_VINTAGE}",
        publisher="U.S. Census Bureau, Center for Economic Studies",
        title="LEHD Origin-Destination Employment Statistics, Origin-Destination (aux)",
        landing="https://lehd.ces.census.gov/data/#lodes",
        verified="2026-08-27",
        notes="Commute flows into California from out of state. Q2 reference period.",
    ),
}

# The segment-specific WAC/RAC files (ca_wac_SE01_*, etc.) are deliberately NOT fetched. The
# S000 "all jobs" file already carries the three earnings bands as columns CE01/CE02/CE03 and the
# twenty NAICS sector groups as CNS01-CNS20, so one 6 MB download gives both cuts. Fetching the
# SE files as well would triple the download for no additional information and would introduce a
# second, redundant path to the same numbers.


# --------------------------------------------------------------------------------------
# ACS
# --------------------------------------------------------------------------------------

#: ACS tables the pipeline reads, with the reason each is needed. Keyed by table ID.
ACS_TABLES: dict[str, str] = {
    "B25001": "Housing units (tract denominator for jobs-housing balance)",
    "B25003": "Tenure (owner/renter split)",
    "B25041": "Bedrooms",
    "B25010": "Average household size by tenure",
    "B25070": "Gross rent as a percentage of household income (renter cost burden)",
    "B25091": "Mortgage status by owner costs as a percentage of income (owner cost burden)",
    "B25014": "Tenure by occupants per room (overcrowding)",
    "B19001": "Household income in the past 12 months (income distribution)",
    "B25056": "Contract rent (affordability level of the existing stock)",
    "B25077": "Median home value",
}


def acs_table_url(table: str, vintage: str = ACS_VINTAGE) -> str:
    """URL for one ACS 5-year table in the table-based Summary File.

    The table-based Summary File is used in preference to the Census Data API because the API
    began requiring a registration key, and Hard constraint 6 plus the "no manual steps"
    requirement mean the default path must work with nothing but an internet connection. These
    ``.dat`` files are pipe-delimited, national in scope, and need no key.

    Args:
        table: ACS table ID, e.g. ``B25070``.
        vintage: ACS 5-year end year.

    Returns:
        A direct download URL.
    """
    return (
        f"https://www2.census.gov/programs-surveys/acs/summary_file/{vintage}/"
        f"table-based-SF/data/5YRData/acsdt5y{vintage}-{table.lower()}.dat"
    )


ACS_GEOS_URL = (
    f"https://www2.census.gov/programs-surveys/acs/summary_file/{ACS_VINTAGE}/"
    f"table-based-SF/documentation/Geos{ACS_VINTAGE}5YR.txt"
)

ACS_LANDING = "https://www.census.gov/programs-surveys/acs/data/summary-file.html"


# --------------------------------------------------------------------------------------
# Income categories
# --------------------------------------------------------------------------------------

#: The four income categories used in the 6th cycle, in the order HCD reports them.
INCOME_4 = ["very_low", "low", "moderate", "above_moderate"]

#: The six categories required for the 7th cycle (Hard constraint 3), in ascending order.
#: Acutely low and extremely low are carved out of very low; see allocate/income.py.
INCOME_6 = [
    "acutely_low",
    "extremely_low",
    "very_low",
    "low",
    "moderate",
    "above_moderate",
]

#: Maps the income_level strings SANDAG publishes in its open-data portal to our keys.
SANDAG_INCOME_LABELS = {
    "d) Very Low Income": "very_low",
    "c) Low Income": "low",
    "b) Moderate Income": "moderate",
    "a) Above Moderate Income": "above_moderate",
}

#: The 6th-cycle RHNA Determination issued by HCD on 2018-07-05 for the 2021-2029 period.
#: Used as the control total for the replication milestone. Source: SANDAG 6th Cycle RHNA
#: Methodology, p. 2, and the adopted RHNA Plan of 2020-07-10.
RHND_6TH_CYCLE_TOTAL = 171_685

#: Regional share of households by income category, from the HCD Determination letter, as
#: reproduced in SANDAG 6th Cycle RHNA Methodology, Table 3, p. 6. These are the percentages
#: HCD used to split the Determination, and they are the control column totals.
RHND_6TH_CYCLE_SHARES = {
    "very_low": 0.247,
    "low": 0.155,
    "moderate": 0.173,
    "above_moderate": 0.425,
}

#: The 6th-cycle Determination as HCD actually issued it, in units. Table 3 of the SANDAG
#: methodology prints the shares rounded to one decimal (24.7%, 15.5%, 17.3%, 42.5%), which do
#: not reproduce these counts: 0.247 x 171,685 is 42,406, but HCD's very-low total is 42,332.
#: The counts are the control totals; the printed percentages are a rounded description of them.
#: Source: SANDAG, *Final 6th Cycle RHNA Plan* (2020-07-10), Table 4.7 region row, p. 26.
RHND_6TH_CYCLE_BY_CATEGORY = {
    "very_low": 42_332,
    "low": 26_627,
    "moderate": 29_734,
    "above_moderate": 72_992,
}
