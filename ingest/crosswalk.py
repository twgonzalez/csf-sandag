"""Tract-to-jurisdiction crosswalk, split by residential-unit share.

Hard constraint 2 makes the census tract the computation geography and the jurisdiction the
output geography. Those two do not nest: 2020 tracts routinely straddle a city boundary. Rolling
a tract's allocation up to whichever jurisdiction contains most of its *area* would hand units to
whichever side of the line holds the open space, so this module splits by *residential units*
instead, from 2020 Census block counts.

Two public files do the work:

``LODES geographic crosswalk`` (``ca_xwalk.csv.gz``)
    The Census Bureau's own block-to-tract and block-to-incorporated-place assignment. Using it
    rather than a spatial join means the pipeline inherits the Bureau's boundary decisions
    instead of inventing its own, and it needs no geometry.

``2020 Census housing units per block``
    The split weight itself. Two interchangeable sources, verified against each other by
    ``tests/test_census_api.py`` to be identical across all 28,633 blocks in the county:

    * With a Census API key: ``H1_001N`` from the 2020 redistricting file, one county-scoped
      request, about a megabyte.
    * Without one: ``HOUSING20`` from the statewide TIGER/Line 2020 tabulation-block shapefile,
      365 MB, downloaded once and cached. This file also carries ``ALAND20``, used only as a
      fallback weight for a tract with no housing at all.

Blocks whose place code is absent (LODES writes ``9999999``) are unincorporated and belong to
the County of San Diego, which Gov. Code Sec. 65584 treats as the nineteenth jurisdiction.

One trap is worth naming, because getting it wrong would move thousands of units. The ``stplc``
field covers **census designated places as well as incorporated cities** -- San Diego County has
39 CDPs (Alpine, Bonita, Fallbrook, Lakeside, Ramona, Spring Valley, and so on). A CDP is a
statistical convenience with no government; its land is unincorporated county and its housing is
the County's RHNA responsibility. This module therefore maps only the 18 GEOIDs listed in
``data/reference/jurisdictions.csv`` and treats every other place code, CDP codes included, as
unincorporated. :func:`validate_place_codes` checks those 18 against the names the Census Bureau
publishes, so a mistyped GEOID fails the run instead of quietly reassigning a city.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

import cache
from config import COUNTY_FIPS, INTERIM, SOURCES, STATE_FIPS
from ingest import census_api
from ingest.sixth_cycle import load_jurisdictions

#: LODES writes this in ``stplc`` for a block that is not in any incorporated place.
LODES_NO_PLACE = "9999999"

#: Key used for the unincorporated county jurisdiction throughout the pipeline.
UNINCORPORATED = "unincorporated"


def validate_place_codes(county_xwalk: pd.DataFrame) -> None:
    """Confirm each pinned place GEOID is the city we think it is.

    The GEOIDs in ``data/reference/jurisdictions.csv`` are hand-entered, and a transposed digit
    would silently reassign an entire city's housing to the unincorporated county. This checks
    every one against the ``stplcname`` the Census Bureau ships in the same file the codes are
    used against, e.g. ``0616378`` must be named ``Coronado city, CA``.

    Args:
        county_xwalk: The LODES crosswalk already filtered to San Diego County, with ``stplc``
            and ``stplcname`` columns.

    Raises:
        ValueError: If a pinned GEOID is absent from the county or names a different place.
    """
    published = (
        county_xwalk.dropna(subset=["stplcname"])
        .drop_duplicates("stplc")
        .set_index("stplc")["stplcname"]
        .to_dict()
    )
    problems = []
    for row in load_jurisdictions().itertuples():
        if row.kind != "city":
            continue
        actual = published.get(row.place_geoid)
        expected = f"{row.name} city, CA"
        if actual is None:
            problems.append(
                f"  {row.jurisdiction}: GEOID {row.place_geoid} not in San Diego County"
            )
        elif actual != expected:
            problems.append(
                f"  {row.jurisdiction}: GEOID {row.place_geoid} is '{actual}', "
                f"expected '{expected}'"
            )
    if problems:
        raise ValueError(
            "place GEOIDs in data/reference/jurisdictions.csv do not match the Census Bureau:\n"
            + "\n".join(problems)
        )


def _block_housing_from_tiger(*, refresh: bool) -> pd.DataFrame:
    """Housing units and land area per block, from the statewide TIGER block shapefile."""
    blocks_dir = cache.unzip(cache.fetch(SOURCES["tiger_blocks_2020"], refresh=refresh))
    shp = next(blocks_dir.glob("*.shp"))
    tiger = gpd.read_file(
        shp,
        columns=["GEOID20", "COUNTYFP20", "HOUSING20", "ALAND20"],
        ignore_geometry=True,
    )
    tiger = tiger[tiger["COUNTYFP20"] == COUNTY_FIPS]
    return tiger.rename(
        columns={
            "GEOID20": "block_geoid",
            "HOUSING20": "housing_units_2020",
            "ALAND20": "land_area_m2",
        }
    )[["block_geoid", "housing_units_2020", "land_area_m2"]]


def _block_housing_from_api() -> pd.DataFrame:
    """Housing units per block from the Census API. Land area is not served and comes back null.

    Land area is only ever consulted for a tract with no housing units anywhere in it, and in the
    current vintage the single such tract in the county is the all-water tract 06073990100, which
    has no land area either and splits evenly under both paths. If a future vintage produces a
    zero-housing tract that *does* have land, the two paths would diverge -- which is exactly
    what ``tests/test_census_api.py`` compares the whole crosswalk to catch.
    """
    api = census_api.block_housing_units()
    api["land_area_m2"] = pd.NA
    return api


def load_block_geography(*, refresh: bool = False, prefer_api: bool = True) -> pd.DataFrame:
    """Block-level geography for San Diego County: tract, jurisdiction, and housing units.

    Args:
        refresh: Re-download the source files even if cached.
        prefer_api: Use the Census API for block housing units when a key is configured, avoiding
            the 365 MB TIGER download. Set False to force the keyless path.

    Returns:
        One row per 2020 Census block in the county. Columns:

        ``block_geoid``
            15-digit 2020 block GEOID.
        ``tract_geoid``
            11-digit 2020 tract GEOID.
        ``jurisdiction``
            Our stable jurisdiction key, or ``unincorporated``.
        ``housing_units_2020``
            ``HOUSING20`` from TIGER: housing units counted in the 2020 Census.
        ``land_area_m2``
            ``ALAND20``: land area in square metres, used only as a fallback weight.
    """
    xwalk_path = cache.fetch(SOURCES["lodes_xwalk"], refresh=refresh)
    xwalk = pd.read_csv(
        xwalk_path,
        compression="gzip",
        usecols=["tabblk2020", "st", "cty", "trct", "stplc", "stplcname"],
        dtype=str,
        low_memory=False,
    )
    xwalk = xwalk[xwalk["cty"] == f"{STATE_FIPS}{COUNTY_FIPS}"].copy()
    validate_place_codes(xwalk)

    jurisdictions = load_jurisdictions()
    place_to_key = (
        jurisdictions.dropna(subset=["place_geoid"])
        .set_index("place_geoid")["jurisdiction"]
        .to_dict()
    )
    # A block in an incorporated place OUTSIDE the region cannot occur here because we already
    # filtered to San Diego County; anything unmapped is therefore unincorporated county land.
    xwalk["jurisdiction"] = xwalk["stplc"].map(place_to_key).fillna(UNINCORPORATED).astype("string")

    if prefer_api and census_api.is_available():
        housing = _block_housing_from_api()
    else:
        housing = _block_housing_from_tiger(refresh=refresh)

    out = xwalk.merge(
        housing.rename(columns={"block_geoid": "tabblk2020"}),
        on="tabblk2020",
        how="left",
        validate="one_to_one",
    )

    missing = int(out["housing_units_2020"].isna().sum())
    if missing:
        raise ValueError(
            f"{missing:,} blocks in the LODES crosswalk have no matching 2020 Census housing "
            "count. The LODES release and the block vintage have diverged; re-pin them in "
            "config.py so both use 2020 blocks."
        )

    out = out.rename(columns={"tabblk2020": "block_geoid", "trct": "tract_geoid"})[
        ["block_geoid", "tract_geoid", "jurisdiction", "housing_units_2020", "land_area_m2"]
    ]
    out["housing_units_2020"] = out["housing_units_2020"].astype("int64")
    out["land_area_m2"] = out["land_area_m2"].astype("Int64")  # nullable: absent on the API path
    out = out.sort_values("block_geoid", ignore_index=True)
    out.to_parquet(INTERIM / "block_geography.parquet", index=False)
    return out


def build_crosswalk(*, refresh: bool = False, prefer_api: bool = True) -> pd.DataFrame:
    """Build the tract-to-jurisdiction crosswalk with residential-unit split weights.

    Rule:
        For a tract that lies in more than one jurisdiction, the share of the tract assigned to
        each jurisdiction is that jurisdiction's share of the tract's 2020 Census housing units.
        Where a tract contains no housing units at all -- pure industrial, military, or open
        space -- unit share is undefined and the weight falls back, first to land area and then,
        if the tract has no land either, to an even split. Every pair records which of the three
        applied in ``weight_basis``, so a reader can see exactly what fell back and check whether
        it mattered.

    Args:
        refresh: Re-download the source files even if cached.
        prefer_api: Use the Census API for block housing units when a key is configured.

    Returns:
        One row per (tract, jurisdiction) pair. Columns:

        ``tract_geoid``, ``jurisdiction``
            The pair.
        ``weight``
            Share of the tract assigned to this jurisdiction. Sums to 1.0 within each tract.
        ``housing_units_2020``
            2020 Census housing units in the intersection.
        ``land_area_m2``
            Land area of the intersection, in square metres.
        ``weight_basis``
            ``"housing_units"`` or ``"land_area"``.
        ``is_split``
            True where the tract crosses a jurisdiction boundary.

    Raises:
        ValueError: If weights do not sum to 1.0 within every tract, or if the crosswalk does not
            cover all 19 jurisdictions.
    """
    blocks = load_block_geography(refresh=refresh, prefer_api=prefer_api)

    pairs = (
        blocks.groupby(["tract_geoid", "jurisdiction"], as_index=False)[
            ["housing_units_2020", "land_area_m2"]
        ]
        .sum()
        .sort_values(["tract_geoid", "jurisdiction"], ignore_index=True)
    )

    tract_units = pairs.groupby("tract_geoid")["housing_units_2020"].transform("sum")
    tract_area = pairs.groupby("tract_geoid")["land_area_m2"].transform("sum")
    pair_count = pairs.groupby("tract_geoid")["jurisdiction"].transform("size")

    # Three bases, in strict precedence: housing units, then land area, then an even split. Each
    # is recorded rather than silently applied, because a tract that fell back is a tract whose
    # jurisdiction split is an assumption rather than a measurement.
    has_units = tract_units > 0
    has_area = (tract_area > 0).fillna(False)

    pairs["weight_basis"] = "housing_units"
    pairs.loc[~has_units & has_area, "weight_basis"] = "land_area"
    pairs.loc[~has_units & ~has_area, "weight_basis"] = "equal_split"

    weight = pairs["housing_units_2020"] / tract_units
    weight = weight.where(has_units, pairs["land_area_m2"] / tract_area)
    weight = weight.where(has_units | has_area, 1.0 / pair_count)
    pairs["weight"] = weight.astype("float64")

    pairs["is_split"] = pairs.groupby("tract_geoid")["jurisdiction"].transform("size") > 1

    sums = pairs.groupby("tract_geoid")["weight"].sum()
    bad = sums[(sums - 1.0).abs() > 1e-9]
    if len(bad):
        raise ValueError(f"{len(bad)} tracts have split weights that do not sum to 1.0:\n{bad}")

    covered = set(pairs["jurisdiction"])
    expected = set(load_jurisdictions()["jurisdiction"])
    if covered != expected:
        raise ValueError(
            f"crosswalk covers {len(covered)} jurisdictions, expected 19. "
            f"Missing: {sorted(expected - covered)}; unexpected: {sorted(covered - expected)}"
        )

    pairs.to_parquet(INTERIM / "tract_jurisdiction_crosswalk.parquet", index=False)
    return pairs


def load_crosswalk() -> pd.DataFrame:
    """Read the cached crosswalk, building it if it does not exist yet."""
    path = INTERIM / "tract_jurisdiction_crosswalk.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return build_crosswalk()


def roll_up_to_jurisdictions(tract_values: pd.DataFrame, value_columns: list[str]) -> pd.DataFrame:
    """Roll tract-level values up to jurisdictions using the split weights.

    This is the only sanctioned way to move from the computation geography to the output
    geography. Multiplying by ``weight`` before summing means a tract straddling a city line
    contributes to each side in proportion to the housing it holds there.

    Args:
        tract_values: Frame with a ``tract_geoid`` column and one row per tract.
        value_columns: Columns to apportion and sum.

    Returns:
        One row per jurisdiction, with the same value columns.

    Raises:
        ValueError: If the input is not one row per tract, or if apportioning changes the
            regional total by more than a rounding tolerance (that would mean the crosswalk has
            lost or duplicated tracts).
    """
    if tract_values["tract_geoid"].duplicated().any():
        raise ValueError("tract_values must have exactly one row per tract")

    xwalk = load_crosswalk()
    merged = xwalk.merge(tract_values, on="tract_geoid", how="left", validate="many_to_one")

    for col in value_columns:
        merged[col] = merged[col].fillna(0.0) * merged["weight"]

    out = merged.groupby("jurisdiction", as_index=False)[value_columns].sum()

    for col in value_columns:
        before = float(tract_values[col].fillna(0.0).sum())
        after = float(out[col].sum())
        if abs(before - after) > max(1e-6, abs(before) * 1e-9):
            raise ValueError(
                f"apportioning '{col}' changed the regional total: {before:,.6f} -> {after:,.6f}. "
                "The crosswalk does not cover every tract in the input."
            )

    return out.sort_values("jurisdiction", ignore_index=True)
