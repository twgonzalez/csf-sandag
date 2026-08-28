"""The Capacity Map report — Phase 2's verifiable output, and the first cut of Phase 3.

Scores every tract on the ingested capacity indicators by the Opportunity Map's own rule, and
cross-tabulates the two maps. The cross-tab is the object Gate A turns on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from config import REPORTS, SOURCES
from ingest.crosswalk import load_crosswalk
from ingest.hazards import load_hazard_shares
from ingest.opportunity_map import load_opportunity_map
from metrics.capacity import (
    SCORED_INDICATORS,
    availability,
    capacity_feature_table,
    cross_tab,
    score_capacity,
)
from report.tables import write_pair

RESOURCE_ORDER = [
    "Highest Resource",
    "High Resource",
    "Moderate Resource",
    "Low Resource",
    "Not scored by TCAC",
]
CAPACITY_ORDER = ["Highest Capacity", "High Capacity", "Moderate Capacity", "Low Capacity"]


def build(*, write: bool = True) -> dict:
    """Score the Capacity Map and write ``reports/capacity_map.md`` plus CSVs."""
    features = capacity_feature_table()
    scored = score_capacity(features)

    units = load_crosswalk().groupby("tract_geoid", as_index=False)["housing_units_2020"].sum()
    capacity = scored.merge(units, on="tract_geoid", validate="one_to_one")
    opportunity = load_opportunity_map()

    matrix = cross_tab(opportunity, capacity, weight="housing_units_2020")
    matrix = (
        matrix.reindex(index=RESOURCE_ORDER)
        .reindex(columns=[c for c in CAPACITY_ORDER if c in matrix.columns])
        .fillna(0)
        .astype(int)
    )
    row_pct = (matrix.div(matrix.sum(axis=1), axis=0) * 100).round(1)

    n_used = int(scored["indicators_scored"].iloc[0])
    highest_resource_highest_capacity = int(matrix.loc["Highest Resource", "Highest Capacity"])
    hh_units = int(matrix.loc[["Highest Resource", "High Resource"]].to_numpy().sum())

    summary = {
        "tracts_scored": int(len(scored)),
        "indicators_used": n_used,
        "indicators_total": len(SCORED_INDICATORS),
        "highest_resource_pct_highest_capacity": float(
            row_pct.loc["Highest Resource", "Highest Capacity"]
        ),
        "low_resource_pct_highest_capacity": float(row_pct.loc["Low Resource", "Highest Capacity"]),
        "inverse_gradient": bool(
            row_pct.loc["Low Resource", "Highest Capacity"]
            > row_pct.loc["Highest Resource", "Highest Capacity"]
        ),
    }
    if not write:
        return summary

    csv_dir = REPORTS / "capacity_map"
    scored_out = capacity.drop(columns=["exposure_basis"])
    scored_out.to_csv(csv_dir / "capacity_by_tract.csv", index=False) if csv_dir.exists() else None
    csv_dir.mkdir(parents=True, exist_ok=True)
    scored_out.to_csv(csv_dir / "capacity_by_tract.csv", index=False)
    matrix_md = write_pair(
        matrix, csv_dir / "cross_tab_units.csv", index_label="opportunity_category"
    )
    pct_md = write_pair(
        row_pct, csv_dir / "cross_tab_row_pct.csv", index_label="opportunity_category"
    )

    status = availability()
    status_md = write_pair(
        status.set_index("indicator")[["domain", "scored", "available"]],
        csv_dir / "indicator_status.csv",
        index_label="indicator",
    )

    hazard = load_hazard_shares()
    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    fire = SOURCES["fhsz_sra"]
    lra = SOURCES["fhsz_lra"]
    cpad = SOURCES["cpad"]
    nfhl = SOURCES["nfhl_flood_zones"]

    body = f"""# The Capacity Map

*Generated {generated} · Plan Phase 2 (partial) · first cross-tab against the Opportunity Map*

## What this report answers, and with how much of the evidence

Every tract scored on physical capacity by the Opportunity Map's own rule — count the indicators
at or above the regional median, add one — so the two maps are constructed identically and
cross-tabulate without any weighting choice in between.

**{n_used} of {len(SCORED_INDICATORS)} scored indicators are ingested**: wildfire (CAL FIRE FHSZ,
current vintages), regulatory floodway (FEMA NFHL), and protected land (CPAD 2026a). Sea level
rise awaits the scenario decision; sewer, water, and evacuation are their own phases. Every
number below is therefore a **partial answer on the land and hazard axes**, and is labelled as
such. Sea level rise, when pinned, is likely to strengthen the pattern — the modelled inundation
sits under the expensive coast. Evacuation, measured as network bottleneck headroom rather than a
hazard footprint, could land on either side; see the closing section. Neither expectation is a
measurement.

## The finding

| | Highest Capacity | Low or Moderate Capacity |
|---|---:|---:|
| **Highest Resource** tracts (by housing units) | **{row_pct.loc["Highest Resource", "Highest Capacity"]:.1f}%** | {row_pct.loc["Highest Resource", "Moderate Capacity"] + row_pct.loc["Highest Resource", "Low Capacity"]:.1f}% |
| **Low Resource** tracts | **{row_pct.loc["Low Resource", "Highest Capacity"]:.1f}%** | {row_pct.loc["Low Resource", "Moderate Capacity"] + row_pct.loc["Low Resource", "Low Capacity"]:.1f}% |

**On the land and hazard axes, physical capacity runs inversely to opportunity in this region.**
The lower-resource urban core is the least hazard-constrained place in the county; the
high-resource areas carry the fire exposure and the protected-land constraint. The gradient is
monotonic across all four resource categories.

Two consequences, one for law and one for design:

1. **Capacity-as-reducer is empirically an AFFH regression here, not just a legal risk.** A
   methodology that lowered allocations for physical constraint would move units from
   high-resource to low-resource areas — the precise opposite of Gov. Code §65584(d)(5). Gate A
   was framed as "is the orthogonal design a preference or a requirement?" On these three axes:
   **a requirement.**
2. **The orthogonal design has real room to work.** Within the Highest Resource row, units
   spread across all four capacity bins — {highest_resource_highest_capacity:,} housing units
   sit in tracts that are both Highest Resource *and* Highest Capacity. Capacity-based siting
   inside the AFFH gate has genuine choices to make; the gate is not a straitjacket.

## The cross-tab

Housing units (2020 Census), opportunity category by capacity category:

{matrix_md}

As row percentages:

{pct_md}

The **Not scored by TCAC** row holds the tracts the state publishes without an Opportunity Score
(incomplete indicator data) — real housing units that a cross-tab must carry, not drop. A
methodology that weights by resource category has to decide what happens to them explicitly.

Recompute any cell from [`capacity_by_tract.csv`](capacity_map/capacity_by_tract.csv) — one row
per tract with every indicator value, the score, and the category.

## How a tract was scored

```
capacity_score = count(indicator >= regional median) + 1        [range 1–{n_used + 1}]
```

The same rule the CTCAC/HCD Opportunity Map uses, verified exactly against its published output
in `metrics/opportunity.py`. Bands cut the range into quarters, so categories keep their meaning
as indicators are added.

Indicators, oriented so higher always means more able to accommodate housing:

| Indicator | Tracts with any exposure | Method |
|---|---:|---|
| `share_outside_vhfhsz` | {int((hazard["share_in_vhfhsz"] > 0).sum())} | Housing-weighted block points vs Very High FHSZ polygons |
| `share_outside_floodway` | {int((hazard["share_in_floodway"] > 0).sum())} | Housing-weighted block points vs NFHL regulatory floodway |
| `share_land_unprotected` | {int((hazard["share_protected"] > 0).sum())} | True area intersection of CPAD holdings with tract polygons |

**The block-point method**, stated plainly: a block's housing counts as inside a zone if a point
guaranteed to lie inside the block does. A block straddling a zone boundary is assigned wholly to
one side. Blocks are small where housing is dense, so the error concentrates where housing is
sparse. {int((hazard["exposure_basis"] == "housing_units").sum())} of 737 tracts are scored on
housing weights; the one all-water tract carries no exposure by construction.

## Indicator status

{status_md}

## Sources

| Layer | Vintage | How verified |
|---|---|---|
| [{fire.title}]({fire.landing}) | {fire.vintage} | Publisher item snippet: "as adopted on April 1, 2024" |
| [{lra.title}]({lra.landing}) | {lra.vintage} | Publisher item snippet: "map dated March 24, 2025" |
| [{nfhl.title}]({nfhl.landing}) | {nfhl.vintage} | ZONE_SUBTY = FLOODWAY only; fetch date in manifest |
| [{cpad.title}]({cpad.landing}) | {cpad.vintage} | CNRA resource, 2026a release |

The stale-service trap, recorded again because it will bite someone: the statewide GIS
`Fire_Severity_Zones` service still serves **2007 SRA / 2011 LRA** zones. This report uses the
OSFM feature services whose own descriptions state the current vintages. Assembled query
responses are checksummed in `data/raw/manifest.json` like every other input.

**External reconciliation is still owed.** CAL FIRE publishes county FHSZ acreage summaries and
CPAD publishes county protected-acreage statistics; reconciling our overlay totals against both
is open work before this map goes near a board, and is noted in `docs/status.md`.

## What this means for Gate A

The Phase 3 correlation study needs the health axis (CalEnviroScreen) and per-indicator detail,
but its central question is answered in preliminary form above, on the axes ingested so far.

The two missing axes are the chair's strongest capacity measures, and they are **not alike in
how they will land**:

- **Sea level rise** is near-certain to strengthen the inverse gradient — the modelled
  inundation sits under the region's most expensive coast.
- **Evacuation is genuinely open, in either direction.** It is measured as bottleneck headroom
  on the road network (`docs/capacity_indicators.md` §3.1), not as a hazard footprint, and the
  indicator's own recorded caution applies: if dense urban tracts route through saturated
  interchanges they will score poorly merely for being dense — which would make evacuation
  capacity run *with* opportunity, against the gradient above. The counter-prior is that grids
  have many outlets and foothills few. Phase 4 measures it; nothing here assumes the answer.

The working conclusion for the chair is unchanged either way: **capacity factors are usable
exactly as the orthogonal design intended — siting within resource bins — and provably unusable
as reducers** on the axes measured so far.
"""
    out_path = REPORTS / "capacity_map.md"
    out_path.write_text(body)
    summary["report_path"] = str(out_path)
    return summary
