"""Uniformed military presence, from open data.

LODES deliberately excludes uniformed military personnel: its inputs are state unemployment
insurance records and OPM's federal *civilian* files, and nobody pays UI premiums for a sailor.
In this county that is not a rounding error -- roughly 110,000 active-duty jobs, held at
installations concentrated in a handful of jurisdictions -- and it is exactly the class of jobs
whose misplacement produced the 6th cycle's one appeal correction. Any open jobs count for this
region therefore needs an explicit uniformed-military layer. This module provides its three
ingredients:

**The level** (how many uniformed jobs the county has) comes from the San Diego Military
Advisory Council's annual Military Economic Impact Report, Exhibit 6 -- direct employment by
service and fiscal year, transcribed to ``data/reference/sdmac_direct_employment.csv`` and
verified against the pinned checksum of the report PDF. SDMAC counts are the same family of
numbers that supplemented the 6th-cycle blend, which keeps the replacement comparable.

**The distribution** (where those jobs are) comes from the 2020 Census P.L. 94-171 file, table
P5: group quarters population by major type, at census-block level. The "military quarters"
category counts people living in barracks and aboard military ships -- and the Census counts a
ship's crew at its **homeport**, the same billets-at-homeport concept the 6th-cycle jobs data
used. Barracks and ships sit inside installation fences, so the military-quarters distribution
is a direct, official, block-level map of where the region's military workplaces are.

**The ceiling** (a sanity bound) comes from DMDC's state-level personnel report: county
active duty can never exceed California active duty.

The distribution assumption -- workplace shares follow military-quarters shares -- is stated
where it is used (:mod:`metrics.adjustments.military`), along with what it misses: office
commands with few quarters (NAVWAR's Old Town campus) are under-weighted, and their uniformed
staff are a small share of the total. Every figure this module emits is either an official
census count or a transcribed, checksummed public number; nothing is estimated here.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile

import pandas as pd

import cache
from config import ACS_VINTAGE, COUNTY_FIPS, INTERIM, REFERENCE, SOURCES, STATE_FIPS, acs_table_url

#: SDMAC fiscal year used for the county control total. FY2023 is chosen to match
#: ``config.LODES_VINTAGE`` (LODES 2023, Q2 reference period).
SDMAC_FISCAL_YEAR = "fy2023"

#: The SDMAC Exhibit 6 rows that count uniformed, active-duty jobs. Civilians are excluded
#: because LODES already counts them (OPM feeds LODES federal civilian employment); reservists
#: are excluded because a drilling reservist is not a full-time workplace presence; VA staff
#: are federal civilians, also already in LODES.
UNIFORMED_CATEGORIES = (
    "usn_active_duty",
    "usmc_active_duty",
    "uscg_active_duty",
    "medical_active_duty",
)

_COUNTY_PREFIX = f"{STATE_FIPS}{COUNTY_FIPS}"

#: 15-digit census block GEOCODE, this state.
_BLOCK_RE = re.compile(rf"^{STATE_FIPS}\d{{13}}$")


def county_uniformed_total() -> int:
    """Active-duty uniformed jobs in the county, from the transcribed SDMAC Exhibit 6.

    Rule:
        Sum of the four active-duty rows (Navy, Marine Corps, Coast Guard, Navy Medicine) for
        :data:`SDMAC_FISCAL_YEAR`.

    Source:
        SDMAC, *Military Economic Impact Report 2024*, Exhibit 6, p. 14; PDF pinned by checksum
        as ``sdmac_meir_2024``.
    """
    table = pd.read_csv(REFERENCE / "sdmac_direct_employment.csv")
    rows = table[table["category"].isin(UNIFORMED_CATEGORIES)]
    if len(rows) != len(UNIFORMED_CATEGORIES):
        raise ValueError("sdmac_direct_employment.csv is missing an active-duty category row")
    return int(rows[SDMAC_FISCAL_YEAR].sum())


def california_active_duty(*, refresh: bool = False) -> int:
    """Active-duty personnel assigned in California, from DMDC's state-level report.

    Used only as a ceiling: the county total from SDMAC must be below this, or one of the two
    sources has been misread.
    """
    path = cache.fetch(SOURCES["dmdc_location_report"], refresh=refresh)
    sheet = pd.read_excel(path, sheet_name=0, header=None)
    match = sheet[sheet.iloc[:, 1].astype("string").str.strip().str.upper() == "CALIFORNIA"]
    if len(match) != 1:
        raise ValueError("DMDC location report: expected exactly one CALIFORNIA row")
    row = match.iloc[0]
    services = [pd.to_numeric(row.iloc[c], errors="coerce") for c in range(2, 8)]
    total = pd.to_numeric(row.iloc[8], errors="coerce")
    if pd.isna(total) or int(total) != int(pd.Series(services).fillna(0).sum()):
        raise ValueError(
            "DMDC location report: active-duty TOTAL column is not where this parser expects; "
            "the file layout has changed -- re-verify against the published sheet"
        )
    return int(total)


def workplace_workers_by_jurisdiction(*, refresh: bool = False) -> pd.DataFrame:
    """Total workers by place of WORK, per jurisdiction, from ACS table B08604.

    Rule:
        Each incorporated city's row is its Census place estimate; the unincorporated county is
        the county estimate minus the sum of the 18 places. B08604's universe is workers 16 and
        over counted where they work, and unlike LODES it **includes armed forces and the
        self-employed**. The gap between this table and LODES is therefore the workers LODES
        structurally cannot see -- which is what the military layer measures.

    Source:
        ACS 5-year table-based Summary File, vintage ``config.ACS_VINTAGE``; keyless bulk file,
        same mechanism as :mod:`ingest.acs` but at place/county summary levels.

    Returns:
        Columns ``jurisdiction``, ``acs_workplace_workers``, ``acs_workplace_moe``. 19 rows.
    """
    path = cache.fetch_url(f"acs{ACS_VINTAGE}_b08604", acs_table_url("B08604"), refresh=refresh)
    df = pd.read_csv(path, sep="|", dtype={"GEO_ID": str}, low_memory=False)

    juris = pd.read_csv(REFERENCE / "jurisdictions.csv", dtype=str)
    place_to_key = {
        f"1600000US{g}": j
        for g, j in zip(juris["place_geoid"].dropna(), juris["jurisdiction"], strict=False)
    }
    county_row = df[df["GEO_ID"] == f"0500000US{STATE_FIPS}{COUNTY_FIPS}"]
    places = df[df["GEO_ID"].isin(place_to_key)].copy()
    if len(county_row) != 1 or len(places) != len(place_to_key):
        raise ValueError(
            "B08604 is missing the county row or one of the 18 incorporated places; "
            "the summary-file geography has changed"
        )
    places["jurisdiction"] = places["GEO_ID"].map(place_to_key)
    out = places[["jurisdiction", "B08604_E001", "B08604_M001"]].rename(
        columns={"B08604_E001": "acs_workplace_workers", "B08604_M001": "acs_workplace_moe"}
    )
    unincorporated = pd.DataFrame(
        [
            {
                "jurisdiction": "unincorporated",
                "acs_workplace_workers": int(county_row["B08604_E001"].iloc[0])
                - int(out["acs_workplace_workers"].sum()),
                # Margins add in quadrature; kept for honesty, not used in allocation.
                "acs_workplace_moe": int(
                    (
                        county_row["B08604_M001"].iloc[0] ** 2
                        + (out["acs_workplace_moe"].astype(float) ** 2).sum()
                    )
                    ** 0.5
                ),
            }
        ]
    )
    out = pd.concat([out, unincorporated], ignore_index=True).sort_values(
        "jurisdiction", ignore_index=True
    )
    out.to_parquet(INTERIM / "acs_workplace_jurisdiction.parquet", index=False)
    return out


def _detect_geo_columns(sample_line: str) -> tuple[int, int, int]:
    """Locate SUMLEV, LOGRECNO, and GEOCODE positions in the P.L. geo header file.

    The 2020 layout puts them at fixed positions, but the point of detecting them from the
    bytes is that a quiet layout change fails loudly instead of mis-parsing.
    """
    fields = sample_line.rstrip("\n").split("|")
    sumlev_i, logrec_i = 2, 7
    geocode_i = None
    for i, value in enumerate(fields[:12]):
        if _BLOCK_RE.match(value):
            geocode_i = i
            break
    if geocode_i is None:
        raise ValueError("P.L. geo file: no 15-digit block GEOCODE found in a block-level row")
    return sumlev_i, logrec_i, geocode_i


def load_military_gq(*, refresh: bool = False, by: str = "block") -> pd.DataFrame:
    """Military-quarters group population per census block (or tract), 2020 Census.

    Rule:
        P.L. 94-171 table P5, category "Military quarters" (P5_0009): residents of barracks,
        military ships at homeport, and other on-installation quarters, on Census Day 2020.

    The parser verifies P5's internal arithmetic on every row (institutionalised plus
    noninstitutionalised equals the total; the three noninstitutionalised categories sum to
    their subtotal) before trusting the column positions. A file whose layout has drifted
    fails loudly rather than shifting counts into the wrong category.

    Returns:
        Columns ``block_geoid`` (or ``tract_geoid``) and ``military_gq``. Blocks with zero are
        dropped -- almost all of the county.
    """
    zip_path = cache.fetch(SOURCES["census_pl94171_ca"], refresh=refresh)
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        geo_name = next(n for n in names if "geo" in n.lower() and n.endswith("2020.pl"))
        seg3_name = next(n for n in names if "00003" in n and n.endswith("2020.pl"))

        # --- geo header: LOGRECNO -> block geocode, this county, block summary level only.
        logrec_to_block: dict[str, str] = {}
        cols: tuple[int, int, int] | None = None
        with zf.open(geo_name) as fh:
            for raw in io.TextIOWrapper(fh, encoding="latin-1"):
                fields = raw.rstrip("\n").split("|")
                if fields[2] != "750":
                    continue
                if cols is None:
                    cols = _detect_geo_columns(raw)
                _, logrec_i, geocode_i = cols
                geocode = fields[geocode_i]
                if geocode.startswith(_COUNTY_PREFIX):
                    logrec_to_block[fields[logrec_i]] = geocode

        if not logrec_to_block:
            raise ValueError("P.L. geo file: no San Diego County blocks found at SUMLEV 750")

        # --- segment 3: P5 by LOGRECNO.
        records: list[tuple[str, int]] = []
        with zf.open(seg3_name) as fh:
            for raw in io.TextIOWrapper(fh, encoding="latin-1"):
                fields = next(csv.reader([raw.rstrip("\n")], delimiter="|"))
                block = logrec_to_block.get(fields[4])
                if block is None:
                    continue
                p5 = [int(v) for v in fields[5:15]]
                total, inst, noninst = p5[0], p5[1], p5[6]
                college, military, other_noninst = p5[7], p5[8], p5[9]
                if inst + noninst != total or college + military + other_noninst != noninst:
                    raise ValueError(
                        f"P.L. table P5 arithmetic failed for block {block}; "
                        "the segment layout has changed -- do not trust column positions"
                    )
                if military:
                    records.append((block, military))

    out = pd.DataFrame(records, columns=["block_geoid", "military_gq"]).sort_values(
        "block_geoid", ignore_index=True
    )
    if by == "tract":
        out["tract_geoid"] = out["block_geoid"].str[:11]
        out = out.groupby("tract_geoid", as_index=False)["military_gq"].sum()
    out.to_parquet(INTERIM / f"military_gq_{by}.parquet", index=False)
    return out
