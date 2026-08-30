"""Historical fire perimeters — the validation zones nobody chose.

Large fires (15,000 acres and up, 2000 onward) that touched San Diego County, from CAL FIRE's
FRAP perimeter database. These are **validation scenarios, never an indicator**: each perimeter
is replayed as an evacuation — every tract the fire actually touched leaves at once on an
otherwise open network — and the shed measure's predicted chokepoints are checked against the
replay's. The defensibility is the point: the test zones are not drawn by an analyst; they are
fires that happened.
"""

from __future__ import annotations

import json

import geopandas as gpd
import requests

import cache
from config import RAW, SOURCES

_BBOX = "-117.63,32.49,-116.07,33.52"
_WHERE = "YEAR_>=2000 AND GIS_ACRES>=15000"
PERIMETERS_PATH = RAW / "fire_perimeters_sd.geojson"


def load_fire_perimeters(*, refresh: bool = False) -> gpd.GeoDataFrame:
    """San Diego County's large fires since 2000, as polygons with name, year, and acreage."""
    if not PERIMETERS_PATH.exists() or refresh:
        source = SOURCES["fire_perimeters"]
        params = {
            "where": _WHERE,
            "geometry": _BBOX,
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "FIRE_NAME,YEAR_,GIS_ACRES",
            "outSR": "4326",
            "f": "geojson",
        }
        response = requests.get(f"{source.url}/query", params=params, timeout=180)
        response.raise_for_status()
        payload = response.json()
        if "features" not in payload or not payload["features"]:
            raise ValueError("fire perimeter query returned no features; service changed?")
        PERIMETERS_PATH.write_text(json.dumps(payload, sort_keys=True))
        cache.record_assembled(
            "fire_perimeters",
            PERIMETERS_PATH,
            url=f"{source.url}/query?where={_WHERE}",
            vintage=source.vintage,
            notes=f"{len(payload['features'])} perimeters, San Diego County bbox",
        )

    gdf = gpd.read_file(PERIMETERS_PATH)
    gdf = gdf.rename(columns={"FIRE_NAME": "fire_name", "YEAR_": "year", "GIS_ACRES": "acres"})
    return gdf[["fire_name", "year", "acres", "geometry"]].sort_values(
        ["year", "fire_name"], ignore_index=True
    )
