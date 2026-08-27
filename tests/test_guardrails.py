"""Tests for the statutory guardrails.

Hard constraint 5 and Gov. Code Sec. 65584.04(e)(2)(B). These tests exist so that a future
contributor adding a plausible-sounding factor cannot quietly reintroduce a prohibited one.
"""

from __future__ import annotations

import pytest

from allocate.guardrails import ProhibitedFactor, enforce, screen_factor


@pytest.mark.parametrize(
    "name",
    [
        "growth_cap",
        "growth-control",
        "permit_quota",
        "voter_approved_limit",
        "zoned_capacity",
        "remaining_density_limit",
        "urban_growth_boundary",
    ],
)
def test_local_permit_limits_are_refused(name: str) -> None:
    refusals = screen_factor(name)
    assert refusals
    assert "local permit limits" in refusals[0].statute


@pytest.mark.parametrize(
    "name",
    ["prior_underproduction", "rhna_progress", "permits_issued", "unbuilt_rhna", "carryover"],
)
def test_prior_underproduction_is_refused(name: str) -> None:
    refusals = screen_factor(name)
    assert refusals
    assert "prior underproduction" in refusals[0].statute


@pytest.mark.parametrize("name", ["stable_population", "no_growth", "built_out", "flat_population"])
def test_stable_population_is_refused(name: str) -> None:
    refusals = screen_factor(name)
    assert refusals
    assert "stable population" in refusals[0].statute


@pytest.mark.parametrize(
    ("name", "source", "description"),
    [
        ("jobs_housing_fit", "LODES WAC + ACS B25056", "low-wage jobs per affordable unit"),
        ("opportunity_bin", "TCAC/HCD Opportunity Map", "composite resource category"),
        ("hazard_constraint_index", "CAL FIRE FHSZ, FEMA NFHL", "share of land in a hazard zone"),
        ("transit_access", "GTFS", "jobs reachable in 45 minutes by transit"),
        ("cost_burdened_households", "ACS B25070", "households paying 30% or more of income"),
    ],
)
def test_permissible_factors_pass(name: str, source: str, description: str) -> None:
    assert screen_factor(name, source=source, description=description) == []


def test_prohibited_source_under_a_neutral_name_is_caught() -> None:
    """A prohibited input can arrive wearing a neutral label; the source is screened too."""
    refusals = screen_factor(
        "developable_acres",
        source="City of Poway General Plan buildout capacity",
        description="acres still available under current zoning",
    )
    assert refusals


def test_enforce_reports_every_refusal_at_once() -> None:
    parameters = {
        "factors": {
            "growth_cap": {},
            "rhna_progress": {},
            "jobs_housing_fit": {"source": "LODES"},
        }
    }
    with pytest.raises(ProhibitedFactor) as caught:
        enforce(parameters)

    refused = {r.factor for r in caught.value.refusals}
    assert refused == {"growth_cap", "rhna_progress"}


def test_enforce_accepts_a_clean_parameter_file() -> None:
    enforce({"factors": {"jobs_housing_fit": {"source": "LODES WAC + ACS B25056"}}})


def test_sixth_cycle_parameter_file_passes_the_guardrails() -> None:
    """The adopted 6th-cycle methodology must itself be lawful under the screen."""
    import tomllib
    from pathlib import Path

    from config import PARAMS

    parameters = tomllib.loads(Path(PARAMS / "sixth_cycle.toml").read_text())
    enforce(parameters)
