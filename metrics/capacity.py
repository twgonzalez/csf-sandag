"""The Capacity Map — a tract-level companion to the CTCAC/HCD Opportunity Map.

Gov. Code Sec. 65584.04(e) requires a council of governments to consider several families of
physical capacity constraint. There is no published map of them. This module builds one.

``docs/capacity_indicators.md`` is the authoritative specification: every objective measure, data
source, spatial join path, and open decision. This module implements it. If the two disagree, the
specification is right.

Three design rules run through everything here.

**Marginal, not stock.** Each indicator asks what the *next increment* of housing costs, not how
much is already present. "100 units is 8% of Del Mar" is the prohibited stable-population
argument; "100 units adds six minutes of clearance time for 2,400 existing residents" is a
physical fact about the increment, and Sec. 65584.04(e) names evacuation route capacity by name.

**Density is demand, never capacity.** No indicator takes density as an input except as the
numerator of a ratio whose denominator is an independently measured capacity. Density alone as a
constraint is the prohibited argument wearing arithmetic.

**Scored by the Opportunity Map's own rule.** Count the indicators on which a tract is at or above
the regional median, add one -- the rule verified exactly against TCAC's published output in
:mod:`metrics.opportunity`. Identical construction means the two maps cross-tabulate on one page,
the scoring cannot be attacked as ad hoc, and nothing is weighted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from allocate.guardrails import screen_factor


@dataclass(frozen=True)
class CapacityIndicator:
    """One indicator in the Capacity Map. See ``docs/capacity_indicators.md`` for the full spec.

    Attributes:
        name: Stable column name for the **scored** form, oriented so higher is more capacity.
        label: How it reads in a report heading.
        measure: The objective measure, as a formula a reader can check.
        reported_as: The interpretable continuous value published alongside the score, with its
            unit. Often the reciprocal or complement of the scored form.
        statutory_basis: The clause of Gov. Code Sec. 65584.04(e) it answers, or why it has none.
        source: Publisher and dataset, as it appears in the methodology appendix.
        url: Where the data comes from.
        scored: Whether it enters the composite. ``False`` means diagnostic only.
        available: Whether the ingest is built yet.
        gap: If unavailable, what is missing and what it would take.
        caution: A known risk in using it, carried into every report that scores it.
    """

    name: str
    label: str
    measure: str
    reported_as: str
    statutory_basis: str
    source: str
    url: str
    scored: bool = True
    available: bool = False
    gap: str = ""
    caution: str = ""


@dataclass(frozen=True)
class CapacityDomain:
    """A group of indicators answering one clause of the statute."""

    key: str
    label: str
    statutory_text: str
    indicators: list[CapacityIndicator] = field(default_factory=list)


CAPACITY_DOMAINS: list[CapacityDomain] = [
    CapacityDomain(
        key="evacuation",
        label="Evacuation",
        statutory_text="Emergency evacuation route capacity",
        indicators=[
            CapacityIndicator(
                name="evacuation_units_accommodatable",
                label="Evacuation headroom, in dwelling units",
                measure=(
                    "min over bottlenecks b on the tract's evacuation routes of: "
                    "headroom_share(t, b) * (capacity_b - assigned_load_b) "
                    "/ (vehicles_per_unit * share_of_tract_flow_through_b)"
                ),
                reported_as=(
                    "Dwelling units addable before the first bottleneck the tract depends on "
                    "saturates, under the pro-rata sharing rule; the solo upper bound is "
                    "published alongside, and the full bottleneck ledger (link, capacity, "
                    "assigned load, contributing tracts and shares) as CSV"
                ),
                statutory_basis="Gov. Code 65584.04(e), emergency evacuation route capacity",
                source=(
                    "OpenStreetMap road network; ACS Table B25044 vehicles per household; "
                    "NRC NUREG/CR-7002 Rev. 1 evacuation methodology; FHWA HPMS Field Manual "
                    "Appendix N capacity parameters"
                ),
                url="https://www.nrc.gov/docs/ML2101/ML21013A504.pdf",
                available=False,
                gap=(
                    "Phase 4. Bottleneck attribution, not per-tract max flow: max flow computed "
                    "independently per tract double-counts shared links -- every Coronado tract "
                    "sees the bridge's full capacity in its own max-flow -- and so overstates "
                    "capacity exactly where many tracts share one outlet. All tracts are routed "
                    "simultaneously (all-or-nothing shortest paths to the exit set), each link's "
                    "load is attributed to the tracts whose vehicles use it, and a tract's "
                    "headroom is its share of the remaining room at its binding bottleneck. Two "
                    "named parameters: exit_set (default freeway mainline plus county boundary) "
                    "and headroom_share (default pro-rata to existing contribution)."
                ),
                caution=(
                    "If dense urban tracts route through saturated urban interchanges they can "
                    "score poorly merely for being dense, which would steer housing away from "
                    "the lower-resource urban cores. Measure in Phase 3 before this carries "
                    "weight. The static all-hazard network and all-or-nothing assignment are "
                    "deliberate simplifications, stated in every report."
                ),
            ),
        ],
    ),
    CapacityDomain(
        key="infrastructure",
        label="Infrastructure",
        statutory_text=(
            "Lack of capacity for sewer or water service due to federal or state laws, "
            "regulations or regulatory actions, or supply and distribution decisions"
        ),
        indicators=[
            CapacityIndicator(
                name="sewer_units_accommodatable",
                label="Sewer headroom, in dwelling units",
                measure=(
                    "(permitted_capacity_mgd - current_average_flow_mgd) * 1e6 "
                    "/ per_unit_wastewater_gpd"
                ),
                reported_as="Dwelling units of remaining permitted treatment capacity",
                statutory_basis=(
                    "Gov. Code 65584.04(e), sewer capacity from state or federal action"
                ),
                source=(
                    "EPA ECHO NPDES permit limits and Discharge Monitoring Reports; "
                    "SWRCB CIWQS enforcement orders as a hard override"
                ),
                url="https://echo.epa.gov/",
                available=False,
                gap=(
                    "Phase 2. Plant capacity is public; sewer service area boundaries are the "
                    "question. If SanGIS does not publish district boundaries this loses tract "
                    "resolution and should drop out of scoring rather than be smeared."
                ),
                caution=(
                    "Sanitary sewer overflow records are evidence of strain, not a state-imposed "
                    "restriction, and must never be used as the factor itself."
                ),
            ),
            CapacityIndicator(
                name="water_units_accommodatable",
                label="Water supply headroom, in dwelling units",
                measure="supply_headroom_acre_feet_per_year / per_unit_demand_af_per_year",
                reported_as="Dwelling units of remaining supply headroom",
                statutory_basis="Gov. Code 65584.04(e), water supply and distribution decisions",
                source=(
                    "DWR Urban Water Management Plans via WUEdata; State Water Project Table A "
                    "allocations; US Bureau of Reclamation Colorado River shortage declarations"
                ),
                url="https://wuedata.water.ca.gov/",
                available=False,
                gap="Phase 2. Per-unit demand factors must be sourced from UWMPs, not assumed.",
                caution=(
                    "Expect this to do very little. The County Water Authority has diversified "
                    "supply for two decades specifically so it can report sufficiency. A "
                    "near-uniform indicator redistributes nothing; that is a finding, not a "
                    "failure, and the weight structure must not assume this one lands."
                ),
            ),
        ],
    ),
    CapacityDomain(
        key="land",
        label="Land availability",
        statutory_text=(
            "The availability of land suitable for urban development or for conversion to "
            "residential use, and lands protected under federal or state programs"
        ),
        indicators=[
            CapacityIndicator(
                name="share_land_unprotected",
                label="Share of tract land not permanently protected",
                measure="1 - (protected_area / tract_land_area)",
                reported_as="Share of tract land available, 0 to 1",
                statutory_basis="Gov. Code 65584.04(e), protected lands",
                source=(
                    "California Protected Areas Database (CPAD) and California Conservation "
                    "Easement Database (CCED), GreenInfo Network"
                ),
                url="https://www.calands.org/",
                available=True,
                gap="",
                caution=(
                    "Protection means a federal, state or private conservation instrument. A "
                    "local open-space designation is not protection for this purpose; counting "
                    "it would be prohibited zoning reasoning."
                ),
            ),
            CapacityIndicator(
                name="share_outside_floodway",
                label="Share of residential land outside the regulatory floodway",
                measure="1 - (residential_land_in_floodway / residential_land_area)",
                reported_as="Share of residential land outside the floodway, 0 to 1",
                statutory_basis="Gov. Code 65584.04(e), land suitable for urban development",
                source="FEMA National Flood Hazard Layer, zone designation FLOODWAY",
                url="https://www.fema.gov/flood-maps/national-flood-hazard-layer",
                available=True,
                gap="",
                caution=(
                    "The regulatory floodway, not the 100-year floodplain. The floodplain is "
                    "buildable with mitigation and holds a great deal of existing California "
                    "housing; using it would exclude far more land than the statute "
                    "contemplates and would read as constraint-shopping."
                ),
            ),
        ],
    ),
    CapacityDomain(
        key="hazard",
        label="Hazard",
        statutory_text="Wildfire risk, sea level rise, and other impacts caused by climate change",
        indicators=[
            CapacityIndicator(
                name="share_outside_vhfhsz",
                label="Share of residential land outside Very High Fire Hazard Severity Zone",
                measure="1 - (residential_land_in_VHFHSZ / residential_land_area)",
                reported_as="Share of residential land outside VHFHSZ, 0 to 1",
                statutory_basis="Gov. Code 65584.04(e), wildfire risk",
                source=(
                    "CAL FIRE Office of the State Fire Marshal Fire Hazard Severity Zones, "
                    "State Responsibility Area effective 2024-04-01 and Local Responsibility "
                    "Area as recommended 2025-03-24"
                ),
                url=(
                    "https://osfm.fire.ca.gov/what-we-do/"
                    "community-wildfire-preparedness-and-mitigation/fire-hazard-severity-zones"
                ),
                available=True,
                gap="",
                caution=(
                    "Hazard is the one family where stock and marginal converge: because units "
                    "are allocated to tracts, a tract 80% in VHFHSZ gives an added unit roughly "
                    "an 80% chance of landing in it, so the share is the marginal exposure. "
                    "Whether exposure is reported raw or mitigation-adjusted is unresolved."
                ),
            ),
            CapacityIndicator(
                name="share_outside_slr_inundation",
                label="Share of residential land outside modelled sea level rise inundation",
                measure="1 - (residential_land_in_inundation / residential_land_area)",
                reported_as="Share of residential land outside inundation, 0 to 1",
                statutory_basis="Gov. Code 65584.04(e), sea level rise",
                source="USGS Coastal Storm Modeling System (CoSMoS)",
                url="https://www.usgs.gov/centers/pcmsc/science/coastal-storm-modeling-system-cosmos",
                available=False,
                gap="Phase 2.",
                caution=(
                    "The scenario is a parameter, not a constant. CoSMoS publishes several sea "
                    "level rise and storm scenarios; which one is pinned is a policy choice that "
                    "changes the result, and every report must state which produced its numbers."
                ),
            ),
        ],
    ),
    CapacityDomain(
        key="diagnostic",
        label="Diagnostic (not scored)",
        statutory_text="Not named in Gov. Code 65584.04(e)",
        indicators=[
            CapacityIndicator(
                name="circuit_headroom",
                label="Electrical distribution circuit headroom",
                measure="available_circuit_capacity_mw / per_unit_coincident_load_mw",
                reported_as="Dwelling units of remaining circuit capacity",
                statutory_basis=(
                    "None. Section 65584.04(e) names sewer and water; it does not name "
                    "electrical capacity."
                ),
                source=(
                    "CPUC-required Integration Capacity Analysis maps; SDG&E Grid Needs "
                    "Assessment and Distribution Deferral Opportunity Report"
                ),
                url="https://www.cpuc.ca.gov/",
                scored=False,
                available=False,
                gap="Diagnostic only. Not on any phase's critical path.",
                caution=(
                    "Deliberately unscored. A methodology that moves a jurisdiction's units on "
                    "electrical grounds invites the question 'under which subdivision?' and "
                    "there is no clean answer. Integration Capacity Analysis is also built for "
                    "distributed energy interconnection rather than load growth, so it is an "
                    "awkward fit technically as well as legally. Report it; do not weight it."
                ),
            ),
        ],
    ),
]

ALL_CAPACITY_INDICATORS = [i for d in CAPACITY_DOMAINS for i in d.indicators]

#: Indicators that enter the composite score. Diagnostics are excluded by construction.
SCORED_INDICATORS = [i for i in ALL_CAPACITY_INDICATORS if i.scored]

#: Concepts that may never enter this map, with the reason.
EXCLUDED_CONCEPTS = {
    "zoned capacity": (
        "Gov. Code 65584.04(e)(2)(B) — a local land use decision, not a physical constraint"
    ),
    "sites inventory": "Gov. Code 65584.04(e)(2)(B) — derived from local zoning",
    "general plan buildout": "Gov. Code 65584.04(e)(2)(B) — a local policy limit",
    "permit history": "Gov. Code 65584.04(e)(2)(B) — prior underproduction",
    "observed residential density": (
        "Not prohibited by name, but 'already built out' is the stable-population justification "
        "wearing an empirical hat. A tract that is dense today is not a tract that physically "
        "cannot hold more. Density may enter only as the numerator of a ratio whose denominator "
        "is an independently measured capacity."
    ),
    "share of allocation relative to existing stock": (
        "Proportional-to-stock reasoning protects small jurisdictions as a class. In this region "
        "small jurisdictions are disproportionately affluent and coastal, so the rule is "
        "AFFH-regressive by construction."
    ),
}


def check_guardrails() -> list[str]:
    """Screen every registered indicator against the statutory prohibitions.

    Returns:
        Refusal explanations. Empty means every indicator is permissible.
    """
    return [
        refusal.explain()
        for indicator in ALL_CAPACITY_INDICATORS
        for refusal in screen_factor(
            indicator.name, source=indicator.source, description=indicator.measure
        )
    ]


def check_orientation(table: pd.DataFrame) -> list[str]:
    """Confirm every share indicator is oriented so higher means more capacity.

    Share indicators are complements of a constraint, so they must lie in ``[0, 1]``. Anything
    outside that range has been stored as the constraint rather than its complement, and the
    composite would come out backwards without any single number looking implausible.
    """
    problems = []
    for indicator in ALL_CAPACITY_INDICATORS:
        if indicator.name not in table.columns or not indicator.name.startswith("share_"):
            continue
        column = table[indicator.name].dropna()
        if len(column) and (column.min() < 0 or column.max() > 1):
            problems.append(
                f"{indicator.name} ranges [{column.min():.3f}, {column.max():.3f}], outside "
                "[0, 1]. Share indicators must be stored as the complement of the constraint."
            )
    return problems


def scoring_set(table: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Split registered scored indicators into those usable for scoring and those excluded.

    Rule:
        Only indicators present and complete for **every** tract in the region are scored. A
        tract scored on four indicators and one scored on six are not comparable, and a
        fraction-of-available scheme hides that behind a number that looks meaningful.

    Args:
        table: Candidate capacity feature table.

    Returns:
        ``(usable, excluded)`` -- lists of indicator names.
    """
    usable, excluded = [], []
    for indicator in SCORED_INDICATORS:
        if indicator.name in table.columns and table[indicator.name].notna().all():
            usable.append(indicator.name)
        else:
            excluded.append(indicator.name)
    return usable, excluded


def availability() -> pd.DataFrame:
    """Which indicators are built, which are pending, and which are diagnostic only."""
    return pd.DataFrame(
        [
            {
                "domain": domain.label,
                "indicator": indicator.label,
                "measure": indicator.measure,
                "statutory_basis": indicator.statutory_basis,
                "source": indicator.source,
                "scored": indicator.scored,
                "available": indicator.available,
                "gap": indicator.gap,
            }
            for domain in CAPACITY_DOMAINS
            for indicator in domain.indicators
        ]
    )


def score_capacity(
    table: pd.DataFrame, *, regional_medians: pd.Series | None = None
) -> pd.DataFrame:
    """Score tracts by the Opportunity Map's own rule, applied to capacity indicators.

    Rule:
        ``capacity_score = count(indicator >= regional median) + 1``

        This is the rule TCAC uses, verified exactly against its published output in
        :func:`metrics.opportunity.replicate_opportunity_score`. There is no capacity equivalent
        of the environmental burden flag, so nothing is subtracted.

        Medians are unweighted across tracts, matching TCAC's own basis, and are taken over the
        same tract population.

    Args:
        table: Tract feature table containing capacity indicator columns.
        regional_medians: Median of each usable indicator. Computed from ``table`` if omitted.

    Returns:
        The input frame plus ``indicators_scored``, ``indicators_excluded``, ``capacity_score``,
        and ``capacity_category``.

    Raises:
        ValueError: If an indicator fails the statutory screen, orientation is wrong, or no
            indicator is usable.
    """
    refusals = check_guardrails()
    if refusals:
        raise ValueError("capacity indicators failed the statutory screen:\n" + "\n".join(refusals))

    problems = check_orientation(table)
    if problems:
        raise ValueError("capacity indicator orientation is wrong:\n" + "\n".join(problems))

    usable, excluded = scoring_set(table)
    if not usable:
        pending = [i.label for i in SCORED_INDICATORS if not i.available]
        raise ValueError(
            "no capacity indicator is complete for every tract, so the Capacity Map cannot be "
            "scored. Pending ingest:\n  - " + "\n  - ".join(pending)
        )

    if regional_medians is None:
        regional_medians = table[usable].median()

    out = table.copy()
    at_or_above = sum((out[c] >= regional_medians[c]).astype("int64") for c in usable)
    out["indicators_scored"] = len(usable)
    out["indicators_excluded"] = ", ".join(excluded)
    out["capacity_score"] = at_or_above + 1
    out["capacity_category"] = out["capacity_score"].map(
        lambda s: capacity_category_from_score(s, len(usable))
    )
    return out


def capacity_category_from_score(score: int, n_indicators: int) -> str:
    """Bin a capacity score into four categories, matching the Opportunity Map's four.

    Rule:
        The score runs from 1 to ``n_indicators + 1``. That range is cut into quarters, so a
        category means the same thing regardless of how many indicators were available -- which
        matters because the map gains indicators as Phase 2 and Phase 4 land, and a category that
        shifted meaning between vintages would make any comparison worthless.
    """
    span = n_indicators + 1
    fraction = (score - 1) / span if span else 0.0
    if fraction >= 0.75:
        return "Highest Capacity"
    if fraction >= 0.50:
        return "High Capacity"
    if fraction >= 0.25:
        return "Moderate Capacity"
    return "Low Capacity"


def capacity_feature_table() -> pd.DataFrame:
    """Tract capacity features from every ingested indicator, ready for :func:`score_capacity`.

    Grows a column per phase: today the three hazard/land indicators from
    :mod:`ingest.hazards`; sea level rise waits on the scenario decision, sewer and water on
    their source work, evacuation on Phase 4.
    """
    from ingest.hazards import load_hazard_shares

    shares = load_hazard_shares()
    return shares[
        [
            "tract_geoid",
            "share_outside_vhfhsz",
            "share_outside_floodway",
            "share_land_unprotected",
            "exposure_basis",
        ]
    ].copy()


def cross_tab(opportunity: pd.DataFrame, capacity: pd.DataFrame, *, weight: str) -> pd.DataFrame:
    """The 4x4 resource-by-capacity matrix that Phase 3 turns on.

    Args:
        opportunity: Frame with ``tract_geoid`` and ``opportunity_category``.
        capacity: Frame with ``tract_geoid`` and ``capacity_category``.
        weight: Column in ``capacity`` to sum in each cell, e.g. 2020 housing units. Pass a
            column of ones for tract counts.

    Returns:
        Opportunity categories as rows, capacity categories as columns.
    """
    joined = opportunity[["tract_geoid", "opportunity_category"]].merge(
        capacity[["tract_geoid", "capacity_category", weight]], on="tract_geoid", how="right"
    )
    # Tracts TCAC publishes without a score (incomplete indicator data) and any tract absent
    # from the map entirely must appear as their own row, not silently drop out of the pivot --
    # they hold real housing units, and a cross-tab that loses units cannot be reconciled.
    joined["opportunity_category"] = joined["opportunity_category"].fillna("Not scored by TCAC")
    return joined.pivot_table(
        index="opportunity_category",
        columns="capacity_category",
        values=weight,
        aggfunc="sum",
        fill_value=0,
    )
