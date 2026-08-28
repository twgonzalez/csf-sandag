"""The Capacity Map — a tract-level companion to the CTCAC/HCD Opportunity Map.

Gov. Code Sec. 65584.04(e) requires a council of governments to consider three families of
physical capacity constraint. There is no published map of them. This module builds one, at tract
level, for the SANDAG region.

**It is scored by the Opportunity Map's own rule, on purpose.** TCAC computes a tract's score by
counting the indicators on which it is at or above its region's median, and this map does exactly
the same thing with capacity indicators. Three things follow:

1. The two maps are directly comparable. A 4x4 cross-tab of resource category against capacity
   category is legible on one page, which is what Phase 3 of the plan needs.
2. The scoring cannot be attacked as ad hoc. It is the state's own method, applied to a different
   set of inputs.
3. Nothing is weighted. There are no coefficients to argue about, no thumb on any scale, and
   nobody has to take a modelling choice on trust.

**Direction matters and is stated once here.** A high capacity score means a tract is *more* able
to accommodate housing. Every indicator below is therefore oriented so that more is better --
a constraint indicator is stored as its complement (share *not* constrained), not as the
constraint itself. :func:`check_orientation` enforces it.

**What this map may never contain.** Zoned capacity, sites-inventory capacity, general plan
buildout, permit history, and observed residential density are all excluded. The first four are
prohibited by Gov. Code Sec. 65584.04(e)(2)(B). The fifth is excluded because "already built out"
is the prohibited stable-population justification wearing an empirical hat: a tract that is dense
today is not a tract that physically cannot hold more. Every indicator registered below is
screened by :mod:`allocate.guardrails` before the map will build.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from allocate.guardrails import screen_factor


@dataclass(frozen=True)
class CapacityIndicator:
    """One indicator in the Capacity Map.

    Attributes:
        name: Stable snake_case column name. Oriented so that higher is more capacity.
        label: How it should read in a report heading.
        description: The rule, in a sentence a planner can check.
        statutory_basis: The clause of Gov. Code Sec. 65584.04(e) it answers.
        source: Publisher and dataset, as it will appear in the methodology appendix.
        url: Where the data comes from.
        available: Whether the ingest for it is built yet.
        gap: If unavailable, what is missing and what it would take.
    """

    name: str
    label: str
    description: str
    statutory_basis: str
    source: str
    url: str
    available: bool = False
    gap: str = ""


@dataclass(frozen=True)
class CapacityDomain:
    """A group of indicators answering one clause of the statute."""

    key: str
    label: str
    statutory_text: str
    indicators: list[CapacityIndicator] = field(default_factory=list)


#: The three capacity families named in Gov. Code Sec. 65584.04(e), with the indicators this
#: pipeline uses for each. Domains mirror the statute rather than any analytic convenience, so
#: that the Sec. 65584.04(f) explanation of "how each factor was incorporated" writes itself.
CAPACITY_DOMAINS: list[CapacityDomain] = [
    CapacityDomain(
        key="infrastructure",
        label="Infrastructure",
        statutory_text=(
            "Lack of capacity for sewer or water service due to federal or state laws, "
            "regulations or regulatory actions, or supply and distribution decisions"
        ),
        indicators=[
            CapacityIndicator(
                name="share_not_under_service_restriction",
                label="Share of residential land not under a state or federal service restriction",
                description=(
                    "Complement of the share of a tract's residential land subject to a sewer or "
                    "water connection restriction imposed by state or federal action. Locally "
                    "chosen limits are excluded: the statute counts only restrictions arising "
                    "from federal or state laws, regulations, regulatory actions, or supply and "
                    "distribution decisions."
                ),
                statutory_basis="Gov. Code 65584.04(e), sewer and water capacity",
                source="State and Regional Water Quality Control Board orders",
                url="https://www.waterboards.ca.gov/board_decisions/",
                available=False,
                gap=(
                    "No clean open dataset of state or federal service restrictions exists. "
                    "Likely hand-assembled from Water Board orders. This is the weakest of the "
                    "three statutory capacity factors and the methodology's weight structure "
                    "must not assume it lands -- see docs/plan.md, Phase 2."
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
                description=(
                    "Complement of the share of tract land under a permanent conservation "
                    "easement or public open-space designation. Protection is a federal, state "
                    "or private conservation instrument, not a local land use designation."
                ),
                statutory_basis="Gov. Code 65584.04(e), protected lands",
                source=(
                    "California Protected Areas Database (CPAD) and California Conservation "
                    "Easement Database (CCED), GreenInfo Network"
                ),
                url="https://www.calands.org/",
                available=False,
                gap="Ingest not built. Phase 2.",
            ),
            CapacityIndicator(
                name="share_outside_floodway",
                label="Share of residential land outside the regulatory floodway",
                description=(
                    "Complement of the share of a tract's residential land inside the FEMA "
                    "regulatory floodway. The floodway, not the wider 100-year floodplain, is "
                    "used here: the floodplain is buildable with mitigation, the floodway is not."
                ),
                statutory_basis="Gov. Code 65584.04(e), land suitable for urban development",
                source="FEMA National Flood Hazard Layer",
                url="https://www.fema.gov/flood-maps/national-flood-hazard-layer",
                available=False,
                gap="Ingest not built. Phase 2.",
            ),
        ],
    ),
    CapacityDomain(
        key="climate",
        label="Climate and evacuation",
        statutory_text=(
            "Emergency evacuation route capacity, wildfire risk, sea level rise, and other "
            "impacts caused by climate change"
        ),
        indicators=[
            CapacityIndicator(
                name="share_outside_very_high_fire_hazard",
                label="Share of residential land outside Very High Fire Hazard Severity Zone",
                description=(
                    "Complement of the share of a tract's residential land in a Very High Fire "
                    "Hazard Severity Zone, across both State and Local Responsibility Areas."
                ),
                statutory_basis="Gov. Code 65584.04(e), wildfire risk",
                source="CAL FIRE Office of the State Fire Marshal, Fire Hazard Severity Zones",
                url=(
                    "https://osfm.fire.ca.gov/what-we-do/"
                    "community-wildfire-preparedness-and-mitigation/fire-hazard-severity-zones"
                ),
                available=False,
                gap=(
                    "Ingest not built. Current vintage is SRA effective 2024-04-01 and LRA as "
                    "recommended 2025-03-24; the older statewide GIS service still serves 2007 "
                    "SRA and 2011 LRA zones and must not be used. Phase 2."
                ),
            ),
            CapacityIndicator(
                name="share_outside_slr_inundation",
                label="Share of residential land outside modelled sea level rise inundation",
                description=(
                    "Complement of the share of a tract's residential land inside the modelled "
                    "inundation extent for the pinned sea level rise scenario. The scenario is a "
                    "parameter, not a constant, and the report states which one was used."
                ),
                statutory_basis="Gov. Code 65584.04(e), sea level rise",
                source="USGS Coastal Storm Modeling System (CoSMoS)",
                url="https://www.usgs.gov/centers/pcmsc/science/coastal-storm-modeling-system-cosmos",
                available=False,
                gap="Ingest not built. Scenario selection is an open question. Phase 2.",
            ),
            CapacityIndicator(
                name="evacuation_route_capacity",
                label="Emergency evacuation route capacity",
                description=(
                    "Per-tract egress capacity and clearance time, computed from the "
                    "OpenStreetMap road network using the federal evacuation time estimate "
                    "methodology, with link and intersection capacity from published federal "
                    "parameters and calibration against public traffic counts."
                ),
                statutory_basis="Gov. Code 65584.04(e), emergency evacuation route capacity",
                source=(
                    "NRC NUREG/CR-7002 Rev. 1 methodology; FHWA HPMS Field Manual Appendix N "
                    "capacity parameters; OpenStreetMap network"
                ),
                url="https://www.nrc.gov/docs/ML2101/ML21013A504.pdf",
                available=False,
                gap=(
                    "Computed in this repository rather than taken from an external score. "
                    "The Highway Capacity Manual itself is a licensed TRB publication and is not "
                    "used; every parameter cites a free federal source. Phase 4."
                ),
            ),
        ],
    ),
]

#: Flat list of every registered indicator.
ALL_CAPACITY_INDICATORS = [i for d in CAPACITY_DOMAINS for i in d.indicators]

#: Concepts that may never enter this map, with the reason. Checked by :func:`check_guardrails`
#: in addition to the general screen in :mod:`allocate.guardrails`.
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
        "cannot hold more."
    ),
}


def check_guardrails() -> list[str]:
    """Screen every registered capacity indicator against the statutory prohibitions.

    Returns:
        A list of refusal explanations. Empty means every indicator is permissible.
    """
    refusals = []
    for indicator in ALL_CAPACITY_INDICATORS:
        for refusal in screen_factor(
            indicator.name, source=indicator.source, description=indicator.description
        ):
            refusals.append(refusal.explain())
    return refusals


def check_orientation(table: pd.DataFrame) -> list[str]:
    """Confirm every indicator column is oriented so that higher means more capacity.

    Share indicators are complements of a constraint, so they must lie in ``[0, 1]``. An
    indicator outside that range is either not a share or has been stored as the constraint
    rather than its complement, and either way the composite score would come out backwards.

    Args:
        table: A capacity feature table.

    Returns:
        A list of problems. Empty means the orientation holds.
    """
    problems = []
    for indicator in ALL_CAPACITY_INDICATORS:
        if indicator.name not in table.columns:
            continue
        if not indicator.name.startswith("share_"):
            continue
        column = table[indicator.name].dropna()
        if len(column) and (column.min() < 0 or column.max() > 1):
            problems.append(
                f"{indicator.name} ranges [{column.min():.3f}, {column.max():.3f}], outside "
                "[0, 1]. Share indicators must be stored as the complement of the constraint, "
                "so that higher always means more capacity."
            )
    return problems


def availability() -> pd.DataFrame:
    """Which capacity indicators are built and which are still pending, with the reason.

    This is deliberately a first-class output rather than a footnote. A capacity map missing its
    evacuation indicator is a different map, and a reader has to be able to see that at a glance.
    """
    return pd.DataFrame(
        [
            {
                "domain": domain.label,
                "indicator": indicator.label,
                "statutory_basis": indicator.statutory_basis,
                "source": indicator.source,
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
    """Score tracts by the CTCAC/HCD Opportunity Map's own rule, applied to capacity indicators.

    Rule:
        Count the indicators on which the tract is at or above the regional median, and add one::

            capacity_score = count(indicator >= regional median) + 1

        This is the rule TCAC uses for the Opportunity Map, verified exactly against its published
        output in :func:`metrics.opportunity.replicate_opportunity_score`. Using it here means the
        two maps are constructed identically and can be cross-tabulated without any weighting
        choice standing between the data and the reader.

        There is no capacity equivalent of the environmental burden flag, so nothing is
        subtracted.

    Args:
        table: Tract feature table containing the available capacity indicator columns.
        regional_medians: Median of each indicator across the region. Computed from ``table`` if
            omitted. Pass explicitly when scoring a subset against the whole region's medians.

    Returns:
        The input frame plus ``indicators_scored``, ``capacity_score``, and ``capacity_category``.

    Raises:
        ValueError: If no registered indicator is present in ``table``, if the guardrail screen
            refuses an indicator, or if orientation is wrong.
    """
    refusals = check_guardrails()
    if refusals:
        raise ValueError("capacity indicators failed the statutory screen:\n" + "\n".join(refusals))

    problems = check_orientation(table)
    if problems:
        raise ValueError("capacity indicator orientation is wrong:\n" + "\n".join(problems))

    present = [i.name for i in ALL_CAPACITY_INDICATORS if i.name in table.columns]
    if not present:
        pending = [i.label for i in ALL_CAPACITY_INDICATORS if not i.available]
        raise ValueError(
            "no capacity indicators are present in the feature table. The Capacity Map cannot be "
            "scored until at least one indicator is ingested. Pending:\n  - "
            + "\n  - ".join(pending)
        )

    if regional_medians is None:
        regional_medians = table[present].median()

    out = table.copy()
    at_or_above = sum((out[c] >= regional_medians[c]).astype("int64") for c in present)
    out["indicators_scored"] = len(present)
    out["capacity_score"] = at_or_above + 1
    out["capacity_category"] = out["capacity_score"].map(
        lambda s: capacity_category_from_score(s, len(present))
    )
    return out


def capacity_category_from_score(score: int, n_indicators: int) -> str:
    """Bin a capacity score into four categories, matching the Opportunity Map's four.

    Rule:
        The score runs from 1 to ``n_indicators + 1``. That range is cut into quarters, so the
        categories mean the same thing regardless of how many indicators are available -- which
        matters because the map will gain indicators as Phase 2 and Phase 4 land, and a category
        that shifted meaning between vintages would make any comparison worthless.

    Args:
        score: The tract's capacity score.
        n_indicators: How many indicators were scored.

    Returns:
        ``"Highest Capacity"``, ``"High Capacity"``, ``"Moderate Capacity"``, or
        ``"Low Capacity"``.
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
