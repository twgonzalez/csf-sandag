"""Equivalence tests for the optional Census API path.

The API key is a speed-up, never a correctness dependency. These tests are what make that claim
true rather than hopeful: they run both paths over real data and fail if a single cell disagrees.

The redaction tests run everywhere. The equivalence tests are skipped when no key is configured,
because there is nothing to compare against -- a machine without a key only ever takes the bulk
path, which is the reference implementation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ingest import census_api

# ---------------------------------------------------------------------------------------------
# Key handling. These run with or without a key configured.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "https://api.census.gov/data/x?get=Y&key=abc123",
            "https://api.census.gov/data/x?get=Y&key=REDACTED",
        ),
        ("key=abc123&for=tract:*", "key=REDACTED&for=tract:*"),
        ("KEY=abc123", "KEY=REDACTED"),
        ('{"url": "?key=abc123"}', '{"url": "?key=REDACTED"}'),
        ("no key here", "no key here"),
    ],
)
def test_redaction_masks_the_key(text: str, expected: str) -> None:
    assert census_api.redact(text) == expected


def test_redaction_leaves_other_parameters_intact() -> None:
    url = "https://api.census.gov/data/2023/acs/acs5?get=group(B25001)&key=SECRET&for=tract:*"
    redacted = census_api.redact(url)
    assert "SECRET" not in redacted
    assert "get=group(B25001)" in redacted
    assert "for=tract:*" in redacted


def test_error_without_a_key_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(census_api, "api_key", lambda: None)
    with pytest.raises(census_api.CensusApiError, match="keyless bulk path"):
        census_api.query("2023/acs/acs5", get=["NAME"], for_geography="state:06")


def test_env_file_is_gitignored() -> None:
    """A committed key would be a real incident; assert the ignore rule is present."""
    from config import ROOT

    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in [line.strip() for line in ignored]


# ---------------------------------------------------------------------------------------------
# Equivalence. Skipped when no key is configured.
# ---------------------------------------------------------------------------------------------

needs_key = pytest.mark.skipif(
    not census_api.is_available(), reason="no CENSUS_API_KEY configured; bulk path is the default"
)

pytestmark_network = pytest.mark.network


@needs_key
@pytest.mark.network
@pytest.mark.parametrize("table", ["B25001", "B25070", "B25014"])
def test_acs_api_matches_bulk_exactly(table: str) -> None:
    """Every estimate and margin must agree to the unit across all 737 tracts."""
    from ingest.acs import load_table, load_table_from_bulk

    api = load_table(table, prefer_api=True).set_index("tract_geoid").sort_index()
    bulk = load_table_from_bulk(table).set_index("tract_geoid").sort_index()

    assert api.index.equals(bulk.index)
    assert set(api.columns) == set(bulk.columns)
    pd.testing.assert_frame_equal(api, bulk[api.columns], check_dtype=False)


@needs_key
@pytest.mark.network
def test_block_housing_api_matches_tiger_exactly() -> None:
    """The API block counts must reproduce TIGER's HOUSING20 for every block in the county."""
    from ingest.crosswalk import _block_housing_from_tiger

    api = census_api.block_housing_units().set_index("block_geoid").sort_index()
    tiger = _block_housing_from_tiger(refresh=False).set_index("block_geoid").sort_index()

    assert api.index.equals(tiger.index)
    assert (api["housing_units_2020"] == tiger["housing_units_2020"]).all()


@needs_key
@pytest.mark.network
def test_crosswalk_is_identical_on_both_paths() -> None:
    """The split weights are what the allocation actually rides on, so compare them directly."""
    from ingest.crosswalk import build_crosswalk

    columns = ["tract_geoid", "jurisdiction", "housing_units_2020", "weight", "is_split"]
    sort = ["tract_geoid", "jurisdiction"]

    api = build_crosswalk(prefer_api=True)[columns].sort_values(sort).reset_index(drop=True)
    bulk = build_crosswalk(prefer_api=False)[columns].sort_values(sort).reset_index(drop=True)

    pd.testing.assert_frame_equal(api, bulk)


@needs_key
@pytest.mark.network
def test_allocation_is_unchanged_by_the_api_path() -> None:
    """The end-to-end guarantee: which path supplied the data cannot move a single unit."""
    from allocate.sixth_cycle import allocate_sixth_cycle
    from ingest.crosswalk import build_crosswalk

    build_crosswalk(prefer_api=True)
    with_api = allocate_sixth_cycle()

    build_crosswalk(prefer_api=False)
    with_bulk = allocate_sixth_cycle()

    pd.testing.assert_frame_equal(with_api, with_bulk)
