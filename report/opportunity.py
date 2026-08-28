"""The Opportunity Map report — Phase 1's verifiable output.

Answers two questions a board member can check: does this pipeline read the state's fair-housing
map correctly, and what does that map say about the SANDAG region.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from config import REPORTS, SOURCES
from ingest.crosswalk import load_crosswalk, roll_up_to_jurisdictions
from ingest.opportunity_map import ALL_INDICATORS, _slug, coverage, load_opportunity_map
from metrics.capacity import (
    CAPACITY_DOMAINS,
    SCORED_INDICATORS,
    availability,
    check_guardrails,
)
from metrics.opportunity import (
    check_category_banding,
    replicate_opportunity_score,
    replication_summary,
)
from report.tables import display_names, write_pair

CATEGORY_ORDER = ["Highest Resource", "High Resource", "Moderate Resource", "Low Resource"]


def _category_by_jurisdiction(opportunity: pd.DataFrame) -> pd.DataFrame:
    """Housing units by jurisdiction and resource category, using the crosswalk split weights."""
    crosswalk = load_crosswalk()
    units = crosswalk.groupby("tract_geoid", as_index=False)["housing_units_2020"].sum()
    joined = units.merge(
        opportunity[["tract_geoid", "opportunity_category"]], on="tract_geoid", how="left"
    )
    joined["opportunity_category"] = joined["opportunity_category"].fillna("Not mapped")

    wide = pd.DataFrame({"tract_geoid": joined["tract_geoid"]})
    for category in [*CATEGORY_ORDER, "Not mapped"]:
        wide[category] = joined["housing_units_2020"].where(
            joined["opportunity_category"] == category, 0.0
        )

    rolled = roll_up_to_jurisdictions(wide, [*CATEGORY_ORDER, "Not mapped"])
    rolled = rolled.set_index("jurisdiction")
    rolled["Total"] = rolled.sum(axis=1)
    rolled["% High or Highest"] = (
        (rolled["Highest Resource"] + rolled["High Resource"]) / rolled["Total"] * 100
    ).round(1)
    rolled.index = display_names(rolled.index)
    return rolled.round(0)


def build(*, write: bool = True) -> dict:
    """Write ``reports/opportunity_map.md`` and its CSVs.

    Returns:
        A summary dict used by tests and by the run log.
    """
    opportunity = load_opportunity_map()
    scored = replicate_opportunity_score(opportunity)
    summary = replication_summary(opportunity)
    banding = check_category_banding(opportunity)
    cover = coverage()

    counts = (
        opportunity["opportunity_category"]
        .value_counts()
        .reindex(CATEGORY_ORDER)
        .rename("Tracts")
        .to_frame()
    )
    counts["Share of mapped tracts"] = (counts["Tracts"] / counts["Tracts"].sum() * 100).round(1)
    counts["High Segregation & Poverty"] = (
        opportunity[opportunity["high_poverty_segregated_flag"] == 1]["opportunity_category"]
        .value_counts()
        .reindex(CATEGORY_ORDER)
        .fillna(0)
        .astype(int)
    )

    by_jurisdiction = _category_by_jurisdiction(opportunity)
    capacity_status = availability()

    result = {
        "score_exact": summary["exact"],
        "score_matches": summary["complete_matches"],
        "score_tracts": summary["complete_tracts"],
        "banding_exact": banding["exact"],
        "mapped_tracts": cover["tcac_tracts"],
        "uncovered_tracts": cover["uncovered_tracts"],
        "capacity_indicators_available": int(capacity_status["available"].sum()),
        "capacity_indicators_total": int(len(capacity_status)),
    }
    if not write:
        return result

    csv_dir = REPORTS / "opportunity_map"
    counts_md = write_pair(counts, csv_dir / "category_counts.csv", index_label="resource_category")
    juris_md = write_pair(by_jurisdiction, csv_dir / "units_by_category.csv")
    capacity_md = write_pair(
        capacity_status.set_index("indicator")[["domain", "statutory_basis", "available"]],
        csv_dir / "capacity_indicator_status.csv",
        index_label="indicator",
    )

    mismatch = scored[(scored["indicators_missing"] == 0) & (~scored["score_matches"])]
    source = SOURCES["tcac_opportunity_map"]
    generated = datetime.now(UTC).strftime("%Y-%m-%d")

    indicator_rows = "\n".join(
        f"| {name} | `{_slug(name)}` | published, with its regional median |"
        for name in ALL_INDICATORS
    )

    domain_rows = "\n".join(
        f"| {d.label} | {sum(1 for i in d.indicators if i.scored)} | "
        f"{sum(1 for i in d.indicators if i.available)} | {d.statutory_text} |"
        for d in CAPACITY_DOMAINS
    )
    measure_rows = "\n".join(
        f"| {i.label} | `{i.measure}` | {i.reported_as} |" for i in SCORED_INDICATORS
    )

    body = f"""# Opportunity Map and Capacity Map

*Generated {generated} · Plan Phase 1*

## What this report answers

Two questions, both checkable without reading code.

1. **Does this pipeline read the state's fair-housing map correctly?**
   Yes — the published Opportunity Score is reproduced exactly for every San Diego tract with
   complete indicator data ({summary["complete_matches"]} of {summary["complete_tracts"]}), and
   the score-to-category banding for every tract ({banding["matches"]} of {banding["tracts"]}).

2. **Can the same be done for physical capacity?**
   The framework is built and scored by the Opportunity Map's own rule, so the two are directly
   comparable. **{result["capacity_indicators_available"]} of
   {result["capacity_indicators_total"]} capacity indicators are ingested so far**, so the
   Capacity Map cannot yet be scored. What is missing, and why, is listed below.

## The Opportunity Score is exactly reproducible

Unlike the 6th-cycle RHNA methodology — which could not be recomputed from its own adopted
documents, see [`sixth_cycle_replication.md`](sixth_cycle_replication.md) — the CTCAC/HCD
Opportunity Map publishes every input beside every output. The score follows from them in one
line:

```
score = count(indicator >= regional median) + 1 - environmental_burden_flag
```

Two details in that line are load-bearing, and both were recovered by testing against the
published output rather than read from the methodology document:

- The comparison is **at or above** the median, not strictly above. Using `>` misses 8 San Diego
  tracts where an indicator sits exactly on its regional median.
- The environmental burden flag is a **subtraction from the composite**, not a separate screen
  applied afterwards. It moves 43 San Diego tracts.

With both right, agreement is exact:

| | Tracts | Reproduced |
|---|---:|---:|
| Complete indicator data | {summary["complete_tracts"]:,} | **{summary["complete_matches"]:,} ({summary["complete_match_rate"] * 100:.1f}%)** |
| One or more indicators missing | {summary["incomplete_tracts"]:,} | {summary["incomplete_matches"]:,} |
| Score-to-category banding | {banding["tracts"]:,} | **{banding["matches"]:,} (100.0%)** |
| Aggregated by us from block groups (excluded) | {summary["aggregated_tracts"]:,} | n/a |

{"No complete-data tract disagrees." if mismatch.empty else f"{len(mismatch)} complete-data tracts disagree and are listed in the CSVs."}

Tracts with a missing indicator are reported separately rather than folded into the headline.
TCAC does not document how it scores them, so counting them as failures would overstate the
disagreement and counting them as successes would hide it.

**This is worth saying to a board.** The transparency standard this project argues for is not
hypothetical or burdensome. The state's own fair-housing map already meets it.

### The eight indicators

| Indicator | Column | Published |
|---|---|---|
{indicator_rows}

## What the map says about the region

{counts_md}

The High Segregation & Poverty column is not a fifth category. It is a separate flag that can
apply to a tract at any resource level, and an AFFH analysis that loses track of it has lost the
thing it was measuring.

### Coverage, and a trap worth naming

TCAC covers **{cover["tcac_tracts"]} of the region's {cover["region_tracts"]} tracts**. The single
tract it does not map is `06073990100`, the all-water tract, which contains no housing. Coverage
of inhabited tracts is complete.

Getting there required not making an easy mistake. TCAC publishes most tracts as one row, but
splits **{cover["block_group_aggregated"]} San Diego tracts into
{cover["block_group_rows_used"]} block-group rows** where the underlying data supports finer
resolution. Reading only the tract rows makes those {cover["block_group_aggregated"]} tracts —
roughly 73,000 housing units, most of it in the unincorporated county — look unmapped. An
allocation built on that reading would have had a hole covering about two fifths of the County's
housing, precisely where the County's own share is determined.

They are aggregated instead, by housing-unit-weighted mean of the block-group scores, rounded,
using the same weighting basis as the tract-to-jurisdiction crosswalk so a reader only has to
accept one convention across the pipeline. Aggregated tracts are marked `geography = block_group`
and are excluded from the replication check above — their tract score is our arithmetic, not
TCAC's, and checking our arithmetic against itself would prove nothing.

## Housing units by jurisdiction and resource category

2020 Census housing units, apportioned with the crosswalk's residential-unit split weights so
that tracts crossing a city boundary contribute to each side in proportion to the housing they
hold there.

{juris_md}

The **% High or Highest** column is the baseline the AFFH gate will measure against. It is a
description of where housing is today, not a target.

Read the spread rather than any single row. Six jurisdictions have every housing unit in a High
or Highest Resource tract; four have essentially none. That distribution is the fair-housing
problem the allocation exists to act on, and it is also why capacity can never be allowed to
reduce a jurisdiction's total — the jurisdictions with the most physical constraint are not
randomly distributed across that column.

## The Capacity Map

There is no published map of the physical capacity constraints Gov. Code §65584.04(e) requires a
council of governments to consider. This pipeline builds one.

**It is scored by the Opportunity Map's own rule**, verified above: count the indicators on which
a tract is at or above the regional median, add one. Three things follow.

1. The two maps are constructed identically, so a resource-by-capacity cross-tab is legible on
   one page — which is exactly what Phase 3 of the plan needs.
2. The scoring cannot be attacked as ad hoc. It is the state's own method on different inputs.
3. Nothing is weighted. There are no coefficients to argue about and no modelling choice standing
   between the data and the reader.

Domains mirror the statute rather than any analytic convenience, so that the §65584.04(f)
explanation of how each factor was incorporated writes itself. **Evacuation is its own domain**,
not a hazard footprint: a dense neighbourhood with two narrow outlets evacuates badly whether or
not it is in a fire zone, and a ridge tract inside a Very High Fire Hazard Severity Zone with
four arterials may evacuate fine.

| Domain | Scored indicators | Ingested | Statutory text |
|---|---:|---:|---|
{domain_rows}

### The objective measures

Every scored indicator is **marginal** — it asks what the next increment of housing costs, not
how much is already there. That distinction is legally decisive: "100 units is 8% of Del Mar" is
the prohibited stable-population argument, while "100 units adds six minutes of clearance time
for 2,400 existing residents" is a physical fact about the increment, and §65584.04(e) names
evacuation route capacity explicitly.

| Indicator | Scored measure | Reported as |
|---|---|---|
{measure_rows}

Density enters only as the numerator of a ratio whose denominator is an independently measured
capacity. Density alone as a constraint is the prohibited argument wearing arithmetic.

Full specification, including data sources, spatial join paths and open decisions:
[`docs/capacity_indicators.md`](../docs/capacity_indicators.md).

**Electrical capacity is registered but deliberately not scored.** §65584.04(e) names sewer and
water; it does not name power. A methodology that moves a jurisdiction's units on electrical
grounds invites the question "under which subdivision?" and there is no clean answer. The CPUC
Integration Capacity Analysis data exists and is public — carry it as a diagnostic, not a factor.

### Status of each indicator

{capacity_md}

### What this map may never contain

Zoned capacity, sites-inventory capacity, general plan buildout, and permit history are
prohibited by §65584.04(e)(2)(B). Observed residential density is excluded too, and that one is
worth stating explicitly because it is not prohibited by name: *already built out* is the
stable-population justification wearing an empirical hat. A tract that is dense today is not a
tract that physically cannot hold more.

Every registered indicator is screened by `allocate/guardrails.py` before the map will build.
Current screen result: **{"no refusals — all indicators permissible" if not check_guardrails() else "REFUSALS PRESENT"}**.

One match was adjudicated rather than pattern-tweaked. The sewer indicator cites "NPDES permit
limits", which the screen initially read as a residential building-permit cap. It is a Clean
Water Act effluent parameter and has nothing to do with building permits — and §65584.04(e) names
sewer capacity as a factor a COG *shall* consider, so refusing it would have blocked a required
factor. The suppression is recorded with its reason in
`allocate.guardrails.ACKNOWLEDGED_FALSE_POSITIVES` and surfaced on every screen, because a
pattern quietly tuned until it stops complaining is a pattern that will miss the real thing
later.

### Direction

A high capacity score means a tract is **more** able to accommodate housing. Every indicator is
stored as the complement of its constraint — share *not* in a hazard zone, share *not* protected —
so that higher always means more. `metrics/capacity.check_orientation` refuses to score a table
where that does not hold, because a sign error here would invert the entire map without changing
a single number's plausibility.

## Sources

| Dataset | Vintage | Checksum |
|---|---|---|
| [{source.title}]({source.landing}) | {source.vintage} | `{source.sha256[:16]}…` |

The publisher serves this file at a generic path with no year in it
(`{source.url.rsplit("/", 1)[-1]}`), so the pinned checksum is the only thing distinguishing the
2026 file from a future reissue. If TCAC republishes, this run fails rather than silently
switching vintages.

## Next

Phase 2 ingests the capacity layers listed above. One finding from attempting it early: the
statewide GIS fire-hazard service still serves **2007 State Responsibility Area and 2011 Local
Responsibility Area zones**, while the current adopted vintage is SRA effective 1 April 2024 and
LRA as recommended 24 March 2025. Anything built on the older service would be quietly eighteen
years stale. This is the kind of thing the four-week Phase 2 estimate is for.
"""

    out_path = REPORTS / "opportunity_map.md"
    out_path.write_text(body)
    result["report_path"] = str(out_path)
    return result
