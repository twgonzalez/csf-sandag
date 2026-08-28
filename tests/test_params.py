"""Tests for the methodology parameter loader — milestone D1.1.

The loader is the enforcement point for Hard constraints 2 and 5, so these tests are the
acceptance criteria in docs/workplan_delta.md: a prohibited factor refuses the file, the
6th-cycle file still loads under its replication flag, and a jurisdiction-scored file without
that flag is refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from allocate.guardrails import ProhibitedFactor
from allocate.params import Factor, InvalidMethodology, Methodology, load_methodology


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "candidate.toml"
    path.write_text(body)
    return path


VALID = """
[methodology]
name = "candidate"
label = "A lawful tract-scored candidate"
geography = "tract"

[factors.opportunity_bin]
weight = 0.7
source = "CTCAC/HCD Opportunity Map, 2026"
description = "Lower-income units weighted toward High and Highest Resource tracts"

[factors.jobs_housing_fit]
weight = 0.3
source = "LODES WAC CE01+CE02 and ACS B25056"
description = "Lower-wage jobs per unit affordable to lower-wage workers"

[income_split]
rule = "inverse_ratio_equity"

[parameters]
floor_weight = 0.01
mass_base = "housing_units_2020"
"""


def test_valid_tract_methodology_loads(tmp_path: Path) -> None:
    m = load_methodology(_write(tmp_path, VALID))
    assert isinstance(m, Methodology)
    assert m.geography == "tract"
    assert not m.replication_only
    assert [f.name for f in m.factors] == ["opportunity_bin", "jobs_housing_fit"]
    assert m.parameters["floor_weight"] == 0.01
    assert m.income_split["rule"] == "inverse_ratio_equity"


def test_prohibited_factor_refuses_the_whole_file(tmp_path: Path) -> None:
    """Hard constraint 5: the statute, not taste."""
    body = (
        VALID
        + """
[factors.rhna_progress]
weight = 0.0
source = "HCD Annual Progress Reports"
description = "Permits issued against the 6th-cycle allocation"
"""
    )
    with pytest.raises(ProhibitedFactor) as caught:
        load_methodology(_write(tmp_path, body))
    assert any(r.factor == "rhna_progress" for r in caught.value.refusals)


def test_prohibited_source_under_neutral_name_is_refused(tmp_path: Path) -> None:
    body = (
        VALID
        + """
[factors.developable_acres]
weight = 0.0
source = "City general plan buildout and zoning capacity"
description = "Acres available for development"
"""
    )
    with pytest.raises(ProhibitedFactor):
        load_methodology(_write(tmp_path, body))


def test_jurisdiction_geography_without_replication_flag_is_refused(tmp_path: Path) -> None:
    """Hard constraint 2: jurisdictions are never scored directly."""
    body = VALID.replace('geography = "tract"', 'geography = "jurisdiction"')
    with pytest.raises(InvalidMethodology, match="Hard constraint 2"):
        load_methodology(_write(tmp_path, body))


def test_sixth_cycle_file_loads_under_replication_flag() -> None:
    """The archived adopted method is jurisdiction-scored and must still load — as an archive."""
    m = load_methodology("sixth_cycle")
    assert m.geography == "jurisdiction"
    assert m.replication_only
    assert pytest.approx(sum(f.weight for f in m.factors)) == 1.0


def test_uncited_factor_is_refused(tmp_path: Path) -> None:
    """The §65584.04(f) appendix is generated from these fields; an empty citation is a defect."""
    body = (
        VALID
        + """
[factors.mystery]
weight = 0.0
description = "A factor with no source"
"""
    )
    with pytest.raises(InvalidMethodology, match="cite its source"):
        load_methodology(_write(tmp_path, body))


def test_malformed_toml_gets_a_schema_error_not_a_statutory_one(tmp_path: Path) -> None:
    with pytest.raises(InvalidMethodology, match="not valid TOML"):
        load_methodology(_write(tmp_path, "[methodology\nname ="))


def test_missing_file_is_a_clear_error() -> None:
    with pytest.raises(InvalidMethodology, match="no parameter file"):
        load_methodology("does_not_exist")


def test_missing_methodology_table_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidMethodology, match="methodology"):
        load_methodology(_write(tmp_path, "[factors]\n"))


def test_factor_dataclass_is_frozen() -> None:
    f = Factor(name="x", weight=0.5, source="s", description="d")
    with pytest.raises(AttributeError):
        f.weight = 0.9  # type: ignore[misc]
