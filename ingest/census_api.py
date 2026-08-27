"""Optional Census Data API client.

The pipeline does not need this. Every number it fetches is also available from the keyless bulk
files in :mod:`ingest.acs` and :mod:`ingest.crosswalk`, and those remain the default. What the
API buys is bandwidth: the bulk ACS files are national and the bulk block file is statewide, so
the keyless path downloads about 1.5 GB to use a few megabytes of it. With a key, the same
numbers arrive as county-scoped queries in about 135 MB total.

That trade is deliberately *not* made a requirement. A jurisdiction appealing under Gov. Code
Sec. 65584.05 has 45 days, and an HCD reviewer auditing the methodology under Sec. 65584.04(i)
should be able to clone this repository and run it. Neither should first have to register for
credentials. So: key present, use the API; key absent, use the bulk files; and
``tests/test_census_api.py`` asserts the two agree to the unit.

**Key handling.** The Census API takes its key as a query parameter, which means the key ends up
inside a URL that could otherwise reach a log, a traceback, or the raw-download manifest that
this project publishes for auditability. Every path out of this module runs through
:func:`redact` first. The key is read from the environment or from a gitignored ``.env``, is
never written to disk, and is never included in a cached filename or a manifest entry.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from config import COUNTY_FIPS, ROOT, STATE_FIPS

#: Matches the key wherever it appears in a URL or message, so it can be masked before display.
_KEY_IN_TEXT = re.compile(r"(key=)[^&\s\"']+", re.IGNORECASE)

_ENV_FILE = ROOT / ".env"

#: Cached so a malformed ``.env`` is reported once rather than on every call.
_env_cache: dict[str, str] | None = None


def redact(text: str) -> str:
    """Mask an API key anywhere it appears in a string.

    Every URL, error message and log line that leaves this module passes through here. It is a
    plain string substitution rather than anything clever precisely so that it cannot fail open.
    """
    return _KEY_IN_TEXT.sub(r"\1REDACTED", text)


def _read_env_file() -> dict[str, str]:
    """Parse a minimal ``KEY=value`` ``.env`` file, if one exists.

    Deliberately hand-rolled rather than pulling in a dotenv dependency: the format this project
    needs is two lines of shell-style assignment, and a pinned dependency that reads secrets is a
    larger surface than the ten lines it replaces.
    """
    global _env_cache
    if _env_cache is not None:
        return _env_cache

    values: dict[str, str] = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip().strip("'\"")
    _env_cache = values
    return values


def api_key() -> str | None:
    """The Census Data API key, if one is configured.

    Looked up in the process environment first, then in a gitignored ``.env`` at the repository
    root. Returns ``None`` when absent or blank, which is the signal for callers to take the
    keyless bulk path.
    """
    key = os.environ.get("CENSUS_API_KEY") or _read_env_file().get("CENSUS_API_KEY", "")
    key = key.strip()
    return key or None


def is_available() -> bool:
    """Whether the API path can be used on this machine."""
    return api_key() is not None


class CensusApiError(RuntimeError):
    """An API request failed. The message is always redacted before it is raised."""


def query(
    dataset: str,
    *,
    get: list[str],
    for_geography: str,
    in_geography: dict[str, str] | None = None,
    timeout: int = 120,
) -> pd.DataFrame:
    """Run one Census Data API query and return it as a frame.

    Args:
        dataset: Dataset path, e.g. ``"2023/acs/acs5"`` or ``"2020/dec/pl"``.
        get: Variables to retrieve, e.g. ``["B25001_001E", "B25001_001M"]``.
        for_geography: The ``for`` clause, e.g. ``"tract:*"``.
        in_geography: The ``in`` clause as a mapping, e.g. ``{"state": "06", "county": "073"}``.
        timeout: Request timeout in seconds.

    Returns:
        One row per geography, columns as requested plus the geography identifier columns the
        API appends.

    Raises:
        CensusApiError: If no key is configured, or the request fails. The message never contains
            the key.
    """
    key = api_key()
    if key is None:
        raise CensusApiError(
            "no Census API key configured. Set CENSUS_API_KEY in the environment or in .env, "
            "or use the keyless bulk path (which is the default)."
        )

    params: dict[str, str] = {"get": ",".join(get), "for": for_geography, "key": key}
    if in_geography:
        params["in"] = " ".join(f"{k}:{v}" for k, v in in_geography.items())

    url = f"https://api.census.gov/data/{dataset}"
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        payload: Any = response.json()
    except requests.HTTPError as exc:
        # response.text can echo the query string back, so redact both parts of the message.
        detail = redact(str(exc))
        body = redact(exc.response.text[:400]) if exc.response is not None else ""
        raise CensusApiError(f"Census API request failed: {detail}\n{body}") from None
    except ValueError as exc:
        raise CensusApiError(
            f"Census API returned a non-JSON response for {dataset}: {redact(str(exc))}"
        ) from None
    except requests.RequestException as exc:
        raise CensusApiError(f"Census API request failed: {redact(str(exc))}") from None

    if not payload or len(payload) < 2:
        raise CensusApiError(
            f"Census API returned no rows for {dataset} (for={for_geography}). "
            "Check that the geography and vintage exist."
        )

    header, *rows = payload
    return pd.DataFrame(rows, columns=header)


#: The API names a variable ``B25001_001E``; the bulk Summary File names the same variable
#: ``B25001_E001``. Neither is more correct, but the pipeline has to pick one, and it picks the
#: bulk form so that the keyless path stays the reference and the API path is the one that
#: translates. This regex does that translation.
_API_VARIABLE = re.compile(r"^([A-Z0-9]+)_(\d{3})([EM])$")


def _to_bulk_variable_names(frame: pd.DataFrame) -> pd.DataFrame:
    """Rename API variable columns to the bulk Summary File convention, dropping annotations.

    The API returns an annotation column alongside every estimate and margin (``..._001EA``,
    ``..._001MA``) carrying symbols like ``(X)`` for suppressed cells. The bulk files encode the
    same information as negative sentinels, which :func:`acs_table` already masks, so the
    annotation columns are redundant here and are dropped rather than carried in two forms.
    """
    renames = {}
    for column in frame.columns:
        match = _API_VARIABLE.match(column)
        if match:
            table, number, kind = match.groups()
            renames[column] = f"{table}_{kind}{number}"
    return frame[list(renames)].rename(columns=renames)


def acs_table(table: str, *, vintage: str) -> pd.DataFrame:
    """Fetch one whole ACS 5-year table for San Diego County tracts.

    Returns the same schema as the keyless :func:`ingest.acs.load_table`, so the two are
    interchangeable and ``tests/test_census_api.py`` can assert they agree cell for cell.

    Args:
        table: ACS table ID, e.g. ``"B25070"``.
        vintage: ACS 5-year end year.

    Returns:
        Columns ``tract_geoid`` then every estimate and margin in the table, named the bulk way
        (``B25070_E001``, ``B25070_M001``, ...), numeric, with the Census Bureau's negative
        sentinels masked to null exactly as the bulk path masks them.
    """
    frame = query(
        f"{vintage}/acs/acs5",
        get=[f"group({table})"],
        for_geography="tract:*",
        in_geography={"state": STATE_FIPS, "county": COUNTY_FIPS},
    )
    if "GEO_ID" not in frame.columns:
        raise CensusApiError(f"Census API response for {table} has no GEO_ID column")

    geoids = frame["GEO_ID"].str.removeprefix("1400000US")
    out = _to_bulk_variable_names(frame)
    out.insert(0, "tract_geoid", geoids)

    numeric = [c for c in out.columns if c != "tract_geoid"]
    out[numeric] = out[numeric].apply(pd.to_numeric, errors="coerce")
    out[numeric] = out[numeric].mask(out[numeric] < -100_000_000)
    return out.sort_values("tract_geoid", ignore_index=True)


def block_housing_units() -> pd.DataFrame:
    """2020 Census housing units per block for San Diego County.

    This is the API replacement for the 365 MB statewide TIGER block shapefile, which the
    crosswalk downloads solely to read its ``HOUSING20`` column. ``H1_001N`` in the 2020
    redistricting file is the same count from the same census.

    Rule:
        2020 Census Redistricting Data (PL 94-171), table H1, variable ``H1_001N``: total housing
        units. Block geography requires state, county and tract, with wildcards permitted on the
        last two, so the whole county comes back in one request.

    Source:
        U.S. Census Bureau, 2020 Census Redistricting Data (P.L. 94-171) Summary File.
        https://api.census.gov/data/2020/dec/pl

    Returns:
        Columns ``block_geoid`` (15-digit) and ``housing_units_2020``.
    """
    frame = query(
        "2020/dec/pl",
        get=["H1_001N"],
        for_geography="block:*",
        in_geography={"state": STATE_FIPS, "county": COUNTY_FIPS, "tract": "*"},
    )
    frame["block_geoid"] = frame["state"] + frame["county"] + frame["tract"] + frame["block"]
    out = frame[["block_geoid", "H1_001N"]].rename(columns={"H1_001N": "housing_units_2020"})
    out["housing_units_2020"] = pd.to_numeric(out["housing_units_2020"]).astype("int64")
    return out.sort_values("block_geoid", ignore_index=True)


def describe_source() -> str:
    """One line for the run log and the methodology appendix, naming which path is in use."""
    if is_available():
        return "Census Data API (CENSUS_API_KEY set; equivalence to bulk files asserted by tests)"
    return "Census bulk files (no API key configured)"


def env_file_path() -> Path:
    """Where the optional ``.env`` is looked for. Exposed for the setup check in the CLI."""
    return _ENV_FILE
