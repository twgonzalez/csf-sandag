"""Hazard and protected-land layers — Phase 2 of the plan, feeding the Capacity Map.

Three of the seven scored capacity indicators come from here: wildfire (CAL FIRE FHSZ, current
vintages), regulatory floodway (FEMA NFHL), and protected land (CPAD). Sea level rise waits on
the scenario decision (open question); sewer, water and evacuation are their own phases.

**How a polygon layer becomes a tract share.** The residential-exposure indicators use the
block-point method: every 2020 census block is represented by a point guaranteed inside its
polygon, carrying its 2020 housing-unit count; a block's housing is "inside" a hazard zone if
its point is. Tract share = housing units inside / tract housing units. This is a documented
simplification -- a block straddling a zone boundary is assigned wholly to one side -- chosen
because it is fast, deterministic, and uses the same housing-unit weighting convention as the
crosswalk, so a reader accepts one convention for the whole pipeline. Blocks are small in
urbanized areas (median well under 0.1 sq km), so the straddling error is small exactly where
the housing is.

For a tract with **no housing at all**, residential exposure is undefined; the share falls back
to block land-area weighting, and to 1.0 (no residential exposure) for the one tract with no
land either. The basis is recorded per tract in ``exposure_basis``, same discipline as the
crosswalk's ``weight_basis``.

The protected-land indicator is different on purpose: the statute speaks of *land* availability,
so it is a true polygon intersection of CPAD holdings with tract boundaries, by area, in an
equal-area projection.
"""

from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import requests

import cache
from config import COUNTY_FIPS, INTERIM, RAW, SOURCES, WORKING_CRS

#: San Diego County envelope in EPSG:4326, used to scope feature-service queries.
_COUNTY_BBOX = "-117.63,32.49,-116.07,33.52"

#: FHSZ class code for Very High, per the FHSZ_Description field ("3 - Very High").
VERY_HIGH = 3


def _fetch_arcgis_geojson(
    key: str, *, where: str = "1=1", out_fields: str = "*", refresh: bool = False
) -> gpd.GeoDataFrame:
    """Fetch one feature-service layer for San Diego County, paginated, and cache the result.

    The assembled GeoJSON is written to ``data/raw/`` and recorded in the manifest with the
    SHA-256 of the assembled bytes, so a run can state exactly which service response it used
    even though the service itself is live.
    """
    source = SOURCES[key]
    dest = RAW / f"{key}.geojson"
    if dest.exists() and not refresh:
        return gpd.read_file(dest)

    features: list[dict] = []
    offset = 0
    while True:
        params = {
            "where": where,
            "outFields": out_fields,
            "geometry": _COUNTY_BBOX,
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": str(offset),
            "resultRecordCount": "1000",
        }
        response = requests.get(f"{source.url}/query", params=params, timeout=300)
        response.raise_for_status()
        payload = response.json()
        if "error" in payload:
            raise RuntimeError(f"{key}: feature service error: {payload['error']}")
        page = payload.get("features", [])
        features.extend(page)
        if not payload.get("properties", {}).get("exceededTransferLimit") and len(page) < 1000:
            break
        offset += len(page)

    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    cache.record_assembled(
        key,
        dest,
        url=f"{source.url}/query (county envelope {_COUNTY_BBOX}, where={where})",
        vintage=source.vintage,
        notes=f"{len(features)} features assembled from paginated query",
    )
    return gpd.read_file(dest)


def load_very_high_fire_hazard(*, refresh: bool = False) -> gpd.GeoDataFrame:
    """Very High Fire Hazard Severity Zone polygons, SRA and LRA combined.

    Source vintages (verified against the publisher's own item descriptions on 2026-08-28):
    SRA as adopted 2024-04-01; LRA from the map dated 2025-03-24, all rollout phases. The FHSZ
    class field is filtered to code 3, Very High, per docs/capacity_indicators.md 3.6.
    """
    sra = _fetch_arcgis_geojson("fhsz_sra", where=f"FHSZ = {VERY_HIGH}", refresh=refresh)
    lra = _fetch_arcgis_geojson("fhsz_lra", where=f"FHSZ = {VERY_HIGH}", refresh=refresh)
    combined = pd.concat(
        [sra.assign(responsibility_area="SRA"), lra.assign(responsibility_area="LRA")],
        ignore_index=True,
    )
    return gpd.GeoDataFrame(combined, crs=sra.crs)


def load_floodway(*, refresh: bool = False) -> gpd.GeoDataFrame:
    """Regulatory floodway polygons from the NFHL.

    The floodway, not the 100-year floodplain: the floodplain is buildable with mitigation, the
    floodway is where construction is prohibited (docs/capacity_indicators.md 3.5).
    """
    return _fetch_arcgis_geojson(
        "nfhl_flood_zones",
        where="ZONE_SUBTY LIKE '%FLOODWAY%'",
        out_fields="FLD_ZONE,ZONE_SUBTY",
        refresh=refresh,
    )


def load_protected_lands(*, refresh: bool = False) -> gpd.GeoDataFrame:
    """CPAD holdings for San Diego County.

    Holdings are fee-owned protected lands under a federal, state, local-agency or private
    conservation instrument. A local open-space *zoning designation* is not in CPAD, which is
    exactly why CPAD is the right source: the prohibited local-policy layer never enters.
    """
    archive = cache.fetch(SOURCES["cpad"], refresh=refresh)
    extracted = cache.unzip(archive)
    shp = next(p for p in sorted(extracted.rglob("*.shp")) if "holding" in p.name.lower())
    holdings = gpd.read_file(shp)
    county_col = next(c for c in holdings.columns if c.upper().startswith("COUNTY"))
    return holdings[holdings[county_col].astype(str).str.contains("San Diego", na=False)].copy()


def _block_points() -> gpd.GeoDataFrame:
    """One point per 2020 block, guaranteed inside its polygon, with housing units and tract."""
    path = INTERIM / "block_points.parquet"
    if path.exists():
        return gpd.read_parquet(path)

    blocks_dir = cache.unzip(cache.fetch(SOURCES["tiger_blocks_2020"]))
    shp = next(blocks_dir.glob("*.shp"))
    blocks = gpd.read_file(shp, bbox=tuple(float(x) for x in _COUNTY_BBOX.split(",")))
    blocks = blocks[blocks["COUNTYFP20"] == COUNTY_FIPS]

    points = gpd.GeoDataFrame(
        {
            "block_geoid": blocks["GEOID20"],
            "tract_geoid": blocks["GEOID20"].str[:11],
            "housing_units_2020": blocks["HOUSING20"].astype("int64"),
            "land_area_m2": blocks["ALAND20"].astype("int64"),
        },
        geometry=blocks.geometry.representative_point(),
        crs=blocks.crs,
    ).to_crs(WORKING_CRS)
    points.to_parquet(path)
    return points


def _exposure_share(points: gpd.GeoDataFrame, zone: gpd.GeoDataFrame) -> pd.DataFrame:
    """Housing-weighted share of each tract inside a zone, with the fallback ladder.

    Basis per tract: ``housing_units`` where the tract has housing; ``land_area`` where it has
    land but no housing; ``no_land`` (share 0.0 inside, i.e. unexposed) for the all-water tract.
    """
    zone_proj = zone.to_crs(WORKING_CRS)
    inside = gpd.sjoin(points, zone_proj[["geometry"]], how="left", predicate="within")
    inside = inside[~inside.index.duplicated(keep="first")]  # a point in overlapping polygons
    flags = inside["index_right"].notna()

    frame = pd.DataFrame(
        {
            "tract_geoid": points["tract_geoid"],
            "housing": points["housing_units_2020"],
            "land": points["land_area_m2"],
            "inside": flags.to_numpy(),
        }
    )
    grouped = frame.groupby("tract_geoid").apply(_one_tract_share, include_groups=False)
    return grouped.reset_index()


def _one_tract_share(group: pd.DataFrame) -> pd.Series:
    if group["housing"].sum() > 0:
        share = group.loc[group["inside"], "housing"].sum() / group["housing"].sum()
        basis = "housing_units"
    elif group["land"].sum() > 0:
        share = group.loc[group["inside"], "land"].sum() / group["land"].sum()
        basis = "land_area"
    else:
        share, basis = 0.0, "no_land"
    return pd.Series({"share_inside": float(share), "exposure_basis": basis})


def _protected_share(tracts: gpd.GeoDataFrame, protected: gpd.GeoDataFrame) -> pd.DataFrame:
    """True area intersection: share of each tract's land under a CPAD holding."""
    tracts_proj = tracts.to_crs(WORKING_CRS)
    protected_union = gpd.GeoDataFrame(
        geometry=[protected.to_crs(WORKING_CRS).union_all()], crs=WORKING_CRS
    )
    overlay = gpd.overlay(tracts_proj, protected_union, how="intersection", keep_geom_type=True)
    protected_area = overlay.assign(a=overlay.geometry.area).groupby("tract_geoid")["a"].sum()

    out = pd.DataFrame(
        {
            "tract_geoid": tracts_proj["tract_geoid"],
            "tract_area_m2": tracts_proj.geometry.area,
        }
    )
    out["protected_area_m2"] = out["tract_geoid"].map(protected_area).fillna(0.0)
    out["share_protected"] = (out["protected_area_m2"] / out["tract_area_m2"]).clip(0.0, 1.0)
    return out


def _tract_polygons() -> gpd.GeoDataFrame:
    tracts_dir = cache.unzip(cache.fetch(SOURCES["tiger_tracts"]))
    shp = next(tracts_dir.glob("*.shp"))
    tracts = gpd.read_file(shp)
    tracts = tracts[tracts["COUNTYFP"] == COUNTY_FIPS]
    return gpd.GeoDataFrame(
        {"tract_geoid": tracts["GEOID"]}, geometry=tracts.geometry, crs=tracts.crs
    )


def build_hazard_shares(*, refresh: bool = False) -> pd.DataFrame:
    """The three hazard/land capacity indicators, per tract, oriented so higher = more capacity.

    Returns:
        One row per tract: ``share_outside_vhfhsz``, ``share_outside_floodway``,
        ``share_land_unprotected``, the underlying raw shares, and ``exposure_basis``.
    """
    points = _block_points()

    fire = _exposure_share(points, load_very_high_fire_hazard(refresh=refresh)).rename(
        columns={"share_inside": "share_in_vhfhsz", "exposure_basis": "exposure_basis"}
    )
    flood = _exposure_share(points, load_floodway(refresh=refresh)).rename(
        columns={"share_inside": "share_in_floodway"}
    )[["tract_geoid", "share_in_floodway"]]
    protected = _protected_share(_tract_polygons(), load_protected_lands(refresh=refresh))[
        ["tract_geoid", "share_protected"]
    ]

    out = fire.merge(flood, on="tract_geoid", validate="one_to_one").merge(
        protected, on="tract_geoid", validate="one_to_one"
    )
    out["share_outside_vhfhsz"] = 1.0 - out["share_in_vhfhsz"]
    out["share_outside_floodway"] = 1.0 - out["share_in_floodway"]
    out["share_land_unprotected"] = 1.0 - out["share_protected"]
    out = out.sort_values("tract_geoid", ignore_index=True)
    out.to_parquet(INTERIM / "hazard_shares.parquet", index=False)
    return out


def load_hazard_shares() -> pd.DataFrame:
    path = INTERIM / "hazard_shares.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return build_hazard_shares()
