"""California School Directory: the public roster behind the school-district HQ correction.

LODES assigns a job to the census block of the employer's *reporting unit*. For a school
district that reports centrally, several thousand teachers can land on the block holding the
district office while the schools they actually work at show nothing. The California School
Directory is the open roster that breaks that: every public school and every district office,
with status and coordinates, maintained by the state.

This module reduces the statewide directory to two tidy county tables -- active schools and
district offices -- each with the census tract it sits in, found by point-in-polygon against
the pinned TIGER tract boundaries. Rows without usable coordinates are dropped and counted,
never guessed.

Source:
    California Department of Education, California School Directory full export
    (``cde_school_directory`` in ``config.SOURCES``). Live export; the fetched bytes are
    recorded in the run manifest.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

import cache
from config import GEOGRAPHIC_CRS, INTERIM, SOURCES, STATE_FIPS

_COUNTY_NAME = "San Diego"

#: Directory columns this module needs. Parsing by name, not position, so a new column in the
#: export cannot silently shift meanings.
_COLUMNS = [
    "CDSCode",
    "StatusType",
    "County",
    "District",
    "School",
    "City",
    "EILCode",
    "Latitude",
    "Longitude",
]


def _tract_polygons() -> gpd.GeoDataFrame:
    tracts_dir = cache.unzip(cache.fetch(SOURCES["tiger_tracts"]))
    shp = next(tracts_dir.glob("*.shp"))
    tracts = gpd.read_file(shp)
    return tracts[["GEOID", "geometry"]].rename(columns={"GEOID": "tract_geoid"})


def load_school_roster(*, refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Active public schools and district offices in the county, each located to a tract.

    Rule:
        A directory row is a **district office** when its CDS code ends in seven zeros (the
        state's convention for district-level records) and a **school** otherwise. Only rows
        with ``StatusType == "Active"`` in this county are kept.

    Returns:
        ``(schools, offices, log)``. Both frames carry ``cds_code``, ``district``, ``name``,
        ``tract_geoid``. ``log`` counts what was dropped and why.
    """
    path = cache.fetch(SOURCES["cde_school_directory"], refresh=refresh)
    raw = pd.read_csv(path, sep="\t", encoding="latin-1", dtype=str, low_memory=False)
    missing = [c for c in _COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"CDE directory export is missing expected columns: {missing}")

    county = raw[(raw["County"] == _COUNTY_NAME) & (raw["StatusType"] == "Active")].copy()
    county["Latitude"] = pd.to_numeric(county["Latitude"], errors="coerce")
    county["Longitude"] = pd.to_numeric(county["Longitude"], errors="coerce")
    no_coords = county[county["Latitude"].isna() | county["Longitude"].isna()]
    county = county.dropna(subset=["Latitude", "Longitude"])

    points = gpd.GeoDataFrame(
        county,
        geometry=gpd.points_from_xy(county["Longitude"], county["Latitude"]),
        crs=GEOGRAPHIC_CRS,
    )
    located = gpd.sjoin(points, _tract_polygons().to_crs(GEOGRAPHIC_CRS), how="left")
    outside = located[located["tract_geoid"].isna()]
    located = located.dropna(subset=["tract_geoid"])
    located = located[located["tract_geoid"].str.startswith(STATE_FIPS)]

    tidy = pd.DataFrame(
        {
            "cds_code": located["CDSCode"],
            "district": located["District"],
            "name": located["School"].fillna(located["District"]),
            "tract_geoid": located["tract_geoid"],
        }
    )
    is_office = tidy["cds_code"].str.endswith("0000000")
    offices = tidy[is_office].reset_index(drop=True)
    schools = tidy[~is_office].reset_index(drop=True)

    schools.to_parquet(INTERIM / "cde_schools.parquet", index=False)
    offices.to_parquet(INTERIM / "cde_district_offices.parquet", index=False)
    log = {
        "county_active_rows": int(len(county) + len(no_coords)),
        "dropped_no_coordinates": int(len(no_coords)),
        "dropped_outside_tracts": int(len(outside)),
        "schools": int(len(schools)),
        "district_offices": int(len(offices)),
    }
    return schools, offices, log
