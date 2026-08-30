"""American Community Survey 5-year estimates, at tract level.

**Two paths to the same numbers.** The Census Data API now redirects keyless requests to a
"Missing Key" page, so a planner cloning this repository with no credentials must be able to get
ACS data some other way. The table-based Summary File serves the identical estimates as
pipe-delimited flat files over plain HTTPS with no key, and that is the path this module takes by
default. It is not free: those files are national, so the keyless path downloads about 472 MB of
ACS to use roughly a megabyte of it.

If ``CENSUS_API_KEY`` is set -- in the environment or in a gitignored ``.env`` -- the same tables
are fetched as county-scoped API queries instead, and the download drops to about a megabyte.
The key is a **speed-up, never a correctness dependency**: ``tests/test_census_api.py`` runs both
paths over real tables and fails if a single cell disagrees. Which path a run used is recorded in
``data/interim/acs_provenance.json`` and reported in the run log, so a reader can tell.

**What is and is not in these numbers.** ACS 5-year estimates are a rolling five-year average,
not a point-in-time count, and every estimate carries a margin of error that this module keeps
alongside it. At tract level those margins are often large -- a tract-level count of 200 with a
margin of 90 is common. Metrics built on these numbers should carry the margin forward rather
than treat the estimate as exact; :mod:`metrics.housing` does.

Source:
    U.S. Census Bureau, American Community Survey 5-Year Estimates, table-based Summary File.
    https://www.census.gov/programs-surveys/acs/data/summary-file.html
"""

from __future__ import annotations

import json

import pandas as pd

import cache
from config import ACS_TABLES, ACS_VINTAGE, COUNTY_FIPS, INTERIM, STATE_FIPS, acs_table_url
from ingest import census_api

#: Summary-file GEO_IDs for census tracts are the summary level 140 prefix plus the tract GEOID.
_TRACT_PREFIX = f"1400000US{STATE_FIPS}{COUNTY_FIPS}"


def _record_provenance(table: str, path: str) -> None:
    """Note which path supplied a table, so a run can state how its ACS numbers were obtained."""
    record_path = INTERIM / "acs_provenance.json"
    existing = json.loads(record_path.read_text()) if record_path.exists() else {}
    existing[table] = path
    record_path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")


def provenance() -> dict[str, str]:
    """Which path supplied each ACS table in the most recent run: ``"api"`` or ``"bulk"``."""
    record_path = INTERIM / "acs_provenance.json"
    return json.loads(record_path.read_text()) if record_path.exists() else {}


def load_table_from_bulk(
    table: str, *, vintage: str = ACS_VINTAGE, refresh: bool = False
) -> pd.DataFrame:
    """Load one ACS table from the keyless table-based Summary File.

    This is the reference implementation. The API path in :func:`load_table` is checked against
    it by ``tests/test_census_api.py``; if they ever diverge, this one is right.

    Args:
        table: ACS table ID, e.g. ``"B25070"``. Must be one of :data:`config.ACS_TABLES`, so that
            the methodology appendix can list every table the pipeline reads.
        vintage: ACS 5-year end year.
        refresh: Re-download even if cached.

    Returns:
        One row per tract. Column ``tract_geoid``, then the table's estimate columns named
        ``{table}_E{nnn}`` and their margins of error named ``{table}_M{nnn}``, exactly as the
        Census Bureau names them. The raw names are kept on purpose: a reader checking a number
        against data.census.gov needs the Bureau's own variable ID, not a friendly rename.

    Raises:
        KeyError: If ``table`` is not registered in :data:`config.ACS_TABLES`.
        ValueError: If the file contains no San Diego County tracts, which means the summary
            level or the county FIPS has changed.
    """
    if table not in ACS_TABLES:
        raise KeyError(
            f"{table} is not registered in config.ACS_TABLES. Add it there, with a note on why "
            "the pipeline needs it, so it appears in the methodology appendix."
        )

    path = cache.fetch_url(
        f"acs{vintage}_{table.lower()}", acs_table_url(table, vintage), refresh=refresh
    )
    df = pd.read_csv(path, sep="|", dtype={"GEO_ID": str}, low_memory=False)
    df = df[df["GEO_ID"].str.startswith(_TRACT_PREFIX)].copy()
    if df.empty:
        raise ValueError(
            f"no San Diego County tracts found in the {vintage} summary file for {table}. "
            f"Expected GEO_IDs beginning '{_TRACT_PREFIX}'."
        )

    df.insert(0, "tract_geoid", df["GEO_ID"].str.removeprefix("1400000US"))
    df = df.drop(columns=["GEO_ID"]).sort_values("tract_geoid", ignore_index=True)

    # The Bureau uses negative sentinels for suppressed and non-applicable values; they are not
    # counts and must not be summed. -666666666 is the most common but there are several.
    numeric = [c for c in df.columns if c != "tract_geoid"]
    df[numeric] = df[numeric].apply(pd.to_numeric, errors="coerce")
    df[numeric] = df[numeric].mask(df[numeric] < -100_000_000)

    df.to_parquet(INTERIM / f"acs{vintage}_{table.lower()}.parquet", index=False)
    _record_provenance(table, "bulk")
    return df


def load_table(
    table: str, *, vintage: str = ACS_VINTAGE, refresh: bool = False, prefer_api: bool = True
) -> pd.DataFrame:
    """Load one ACS table for San Diego County tracts, by whichever path is available.

    Uses the Census Data API when a key is configured, and the keyless bulk Summary File
    otherwise. The two return identical frames; see the module docstring.

    Args:
        table: ACS table ID, e.g. ``"B25070"``.
        vintage: ACS 5-year end year.
        refresh: Re-download even if cached. Only meaningful on the bulk path; API responses are
            not cached as raw files.
        prefer_api: Set False to force the bulk path even when a key is configured. Used by the
            equivalence test and by anyone reproducing a run without credentials.

    Returns:
        One row per tract. Column ``tract_geoid``, then the table's estimate columns named
        ``{table}_E{nnn}`` and their margins named ``{table}_M{nnn}``.

    Raises:
        KeyError: If ``table`` is not registered in :data:`config.ACS_TABLES`.
    """
    if table not in ACS_TABLES:
        raise KeyError(
            f"{table} is not registered in config.ACS_TABLES. Add it there, with a note on why "
            "the pipeline needs it, so it appears in the methodology appendix."
        )

    # A table already tidied this run or a prior one is read from disk: every successful load
    # writes the interim parquet, so downstream rebuilds are offline. refresh=True bypasses.
    cached = INTERIM / f"acs{vintage}_{table.lower()}.parquet"
    if cached.exists() and not refresh:
        return pd.read_parquet(cached)

    if not (prefer_api and census_api.is_available()):
        return load_table_from_bulk(table, vintage=vintage, refresh=refresh)

    try:
        df = census_api.acs_table(table, vintage=vintage)
    except census_api.CensusApiError:
        # The key is a speed-up, never a dependency: a flaky or unreachable API falls back to
        # the keyless bulk path, which the equivalence tests prove returns identical numbers.
        return load_table_from_bulk(table, vintage=vintage, refresh=refresh)
    df.to_parquet(INTERIM / f"acs{vintage}_{table.lower()}.parquet", index=False)
    _record_provenance(table, "api")
    return df


def load_all(*, vintage: str = ACS_VINTAGE, refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Load every ACS table the pipeline uses.

    Returns:
        Table ID -> tract-level frame, for each entry in :data:`config.ACS_TABLES`.
    """
    return {t: load_table(t, vintage=vintage, refresh=refresh) for t in ACS_TABLES}


def estimate(table: pd.DataFrame, variable: str) -> pd.Series:
    """Pull one estimate column, indexed by tract.

    Args:
        table: A frame from :func:`load_table`.
        variable: An ACS variable ID such as ``"B25070_007"``. The ``E``/``M`` suffix is added
            here, so callers name the variable the way the Census Bureau's documentation does.

    Returns:
        Tract-indexed estimate.
    """
    prefix, number = variable.split("_")
    return table.set_index("tract_geoid")[f"{prefix}_E{number}"].rename(variable)


def margin(table: pd.DataFrame, variable: str) -> pd.Series:
    """Pull the margin of error for one estimate, indexed by tract. See :func:`estimate`."""
    prefix, number = variable.split("_")
    return table.set_index("tract_geoid")[f"{prefix}_M{number}"].rename(f"{variable}_moe")


def sum_variables(table: pd.DataFrame, variables: list[str]) -> pd.Series:
    """Sum several estimate columns, propagating the margin of error is left to the caller.

    ACS margins on a sum combine in quadrature, not by addition; :func:`combined_margin` does
    that. They are separate functions because summing estimates is always right and combining
    margins is only approximately right, and the distinction should be visible at the call site.
    """
    return sum(estimate(table, v) for v in variables)


def combined_margin(table: pd.DataFrame, variables: list[str]) -> pd.Series:
    """Approximate margin of error for a sum of ACS estimates.

    Rule:
        The Census Bureau's published approximation for the margin of a sum is the square root of
        the sum of the squared component margins. It understates the true margin when the
        components are positively correlated, which they often are within a table, so treat it as
        a floor.

    Source:
        U.S. Census Bureau, *Understanding and Using American Community Survey Data*, appendix on
        calculating measures of error.
        https://www.census.gov/programs-surveys/acs/library/handbooks/general.html
    """
    squared = sum(margin(table, v) ** 2 for v in variables)
    return (squared**0.5).rename("moe")
