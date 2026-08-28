"""CTCAC/HCD Opportunity Map — the AFFH measuring stick.

This is the map California uses to decide what counts as a high-opportunity neighbourhood. It is
the accepted currency for fair-housing analysis in this state, and it is what HCD will expect a
7th-cycle methodology to be measured against under Gov. Code Sec. 65584(d)(5).

**It is already open, and that matters for how this repository treats it.** Unlike the SANDAG
Activity Based Model and Employment Estimates, TCAC publishes every input indicator, every
regional median, and the resulting score in one spreadsheet. :mod:`metrics.opportunity`
reproduces the published score exactly from those inputs.

So this module ingests TCAC's map as **authoritative**, and the replication in ``metrics/`` is a
*verification*, not a substitute. That distinction is deliberate. A council of governments that
published its own rival opportunity index would be asked why, and no answer to that question is
better than using the state's. The replication earns something different: it proves the pipeline
reads the map correctly, it makes the map's own arithmetic legible to a board member, and it lets
a future vintage be recomputed and diffed rather than swallowed.

Source:
    California Tax Credit Allocation Committee and California Department of Housing and Community
    Development, *CTCAC/HCD Opportunity Map*, 2026 edition, adopted December 2025.
    https://www.treasurer.ca.gov/ctcac/opportunity
"""

from __future__ import annotations

import pandas as pd

import cache
from config import INTERIM, SOURCES

#: The eight indicators the composite score is built from, in the order TCAC lists them, grouped
#: by domain. Each has a matching ``Regional Median - {name}`` column in the same file.
OPPORTUNITY_INDICATORS: dict[str, list[str]] = {
    "economic": [
        "Share >200% Poverty",
        "Share with Bachelors+",
        "Employment Rate",
        "Median Home Value",
    ],
    "education": [
        "Share Proficient in Math",
        "Share Proficient in Reading",
        "High School Grad Rate",
        "Students Not in Poverty",
    ],
}

#: Flat list of all eight, for scoring.
ALL_INDICATORS = [c for group in OPPORTUNITY_INDICATORS.values() for c in group]

#: The five categories TCAC assigns, from most to least resourced. "High Segregation & Poverty"
#: is not a sixth rank -- it is a separate flag that can apply to a tract in any category, and it
#: is the one an AFFH analysis must never lose track of.
OPPORTUNITY_CATEGORIES = [
    "Highest Resource",
    "High Resource",
    "Moderate Resource",
    "Low Resource",
]

COLUMN_RENAMES = {
    "Census Tract": "tract_geoid",
    "Census Block Group": "block_group",
    "County": "county",
    "Region": "tcac_region",
    "Environmental Burden Flag": "environmental_burden_flag",
    "Opportunity Score": "opportunity_score",
    "Opportunity Category": "opportunity_category",
    "High-Poverty & Segregated Flag": "high_poverty_segregated_flag",
}


def load_opportunity_map(*, refresh: bool = False) -> pd.DataFrame:
    """Tract-level CTCAC/HCD Opportunity Map for San Diego County.

    TCAC publishes most tracts as a single row, but splits some into **block groups** where the
    underlying data supports finer resolution -- 39 San Diego tracts, across 106 block groups.
    Those must be aggregated up, not dropped. Dropping them makes 39 tracts holding roughly
    73,000 housing units look unmapped, which is wrong and would understate the map's coverage of
    the unincorporated county badly enough to distort an allocation.

    Rule for aggregation:
        A split tract's score is the **housing-unit-weighted mean of its block-group scores,
        rounded to the nearest whole score**, using 2020 Census housing units per block group.
        Housing-unit weighting is the same basis the tract-to-jurisdiction crosswalk uses, so a
        reader only has to accept one weighting convention across the whole pipeline. The
        category is then derived from the rounded score using the banding verified in
        :func:`metrics.opportunity.check_category_banding`.

        Where a split tract has no housing at all in any block group, the plain mean is used, and
        the tract is flagged ``geography="block_group_unweighted"``.

    Args:
        refresh: Re-download even if cached.

    Returns:
        One row per tract, including the aggregated split tracts. Columns: ``tract_geoid``,
        ``county``, ``tcac_region``, the eight indicator columns, their eight
        ``regional_median_*`` counterparts, ``environmental_burden_flag``,
        ``opportunity_score``, ``opportunity_category``, ``high_poverty_segregated_flag``, and
        ``geography`` recording whether the row came from a tract row or was aggregated from
        block groups.

    Raises:
        ValueError: If the workbook does not contain the expected indicator columns, which would
            mean TCAC changed its schema and the replication in ``metrics/opportunity.py`` needs
            revisiting before any number from it is trusted.
    """
    archive = cache.fetch(SOURCES["tcac_opportunity_map"], refresh=refresh)
    extracted = cache.unzip(archive)
    workbook = next(extracted.glob("*.xlsx"))

    raw = pd.read_excel(workbook)

    missing = [c for c in ALL_INDICATORS if c not in raw.columns]
    missing += [
        f"Regional Median - {c}"
        for c in ALL_INDICATORS
        if f"Regional Median - {c}" not in raw.columns
    ]
    if missing:
        raise ValueError(
            "the CTCAC/HCD Opportunity Map workbook is missing expected columns: "
            f"{missing}. TCAC has changed its schema; revisit metrics/opportunity.py before "
            "trusting any score from this vintage."
        )

    sd_all = raw[raw["County"] == "San Diego"].copy()
    sd = sd_all[sd_all["Census Block Group"].isna()].copy()

    out = sd.rename(columns=COLUMN_RENAMES)
    for indicator in ALL_INDICATORS:
        out[f"regional_median_{_slug(indicator)}"] = sd[f"Regional Median - {indicator}"]
        out[_slug(indicator)] = sd[indicator]

    keep = (
        ["tract_geoid", "county", "tcac_region"]
        + [_slug(i) for i in ALL_INDICATORS]
        + [f"regional_median_{_slug(i)}" for i in ALL_INDICATORS]
        + [
            "environmental_burden_flag",
            "opportunity_score",
            "opportunity_category",
            "high_poverty_segregated_flag",
        ]
    )
    out = out[keep]
    out["tract_geoid"] = out["tract_geoid"].astype("int64").astype(str).str.zfill(11)
    out["geography"] = "tract"

    split = _aggregate_block_groups(sd_all, keep)
    out = pd.concat([out, split], ignore_index=True)
    out = out.sort_values("tract_geoid", ignore_index=True)

    if out["tract_geoid"].duplicated().any():
        raise ValueError("aggregating block groups produced duplicate tracts")

    out.to_parquet(INTERIM / "tcac_opportunity_map.parquet", index=False)
    return out


def _block_group_housing_units() -> pd.Series:
    """2020 Census housing units per block group, from the block table the crosswalk builds.

    A block group GEOID is the first 12 characters of a block GEOID by construction, so this
    needs no additional download and cannot disagree with the crosswalk.
    """
    from ingest.crosswalk import load_block_geography

    blocks = load_block_geography()
    return (
        blocks.assign(block_group=blocks["block_geoid"].str[:12])
        .groupby("block_group")["housing_units_2020"]
        .sum()
    )


def _aggregate_block_groups(sd_all: pd.DataFrame, keep: list[str]) -> pd.DataFrame:
    """Roll TCAC's block-group rows up to tracts, weighted by housing units.

    See :func:`load_opportunity_map` for the rule and why dropping these rows would be wrong.
    """
    from metrics.opportunity import category_from_score

    bg = sd_all[sd_all["Census Block Group"].notna()].copy()
    if bg.empty:
        return pd.DataFrame(columns=[*keep, "geography"])

    bg["tract_geoid"] = bg["Census Tract"].astype("int64").astype(str).str.zfill(11)
    bg["block_group"] = bg["Census Block Group"].astype("int64").astype(str).str.zfill(12)
    bg["units"] = bg["block_group"].map(_block_group_housing_units()).fillna(0.0)

    rows = []
    for tract, group in bg.groupby("tract_geoid", sort=True):
        weights = group["units"]
        weighted = weights.sum() > 0
        scores = group["Opportunity Score"]
        score = (
            float((scores * weights).sum() / weights.sum()) if weighted else float(scores.mean())
        )
        rounded = int(round(score))

        row: dict = {
            "tract_geoid": tract,
            "county": "San Diego",
            "tcac_region": group["Region"].iloc[0],
            "opportunity_score": rounded,
            "opportunity_category": category_from_score(rounded),
            "environmental_burden_flag": float(
                (group["Environmental Burden Flag"].fillna(0) * weights).sum() / weights.sum()
            )
            if weighted
            else float(group["Environmental Burden Flag"].fillna(0).mean()),
            # A tract counts as high-poverty and segregated if any of its block groups does.
            # This is a flag about the presence of a condition, not an average of one.
            "high_poverty_segregated_flag": float(
                group["High-Poverty & Segregated Flag"].fillna(0).max()
            ),
            "geography": "block_group" if weighted else "block_group_unweighted",
        }
        for indicator in ALL_INDICATORS:
            slug = _slug(indicator)
            values = group[indicator]
            row[slug] = (
                float((values * weights).sum() / weights.sum())
                if weighted and values.notna().all()
                else float(values.mean())
            )
            row[f"regional_median_{slug}"] = float(group[f"Regional Median - {indicator}"].iloc[0])
        rows.append(row)

    return pd.DataFrame(rows)[[*keep, "geography"]]


def _slug(indicator: str) -> str:
    """Turn a TCAC column heading into a stable snake_case name.

    The mapping is kept mechanical rather than hand-written so a new indicator in a future vintage
    gets a predictable name instead of silently missing one.
    """
    return (
        indicator.lower()
        .replace(">", "over_")
        .replace("%", "pct")
        .replace("+", "_plus")
        .replace(" ", "_")
        .replace("-", "_")
        .replace("__", "_")
        .strip("_")
    )


def coverage(*, refresh: bool = False) -> dict:
    """How much of the region the Opportunity Map actually covers.

    Coverage is near-total once block-group rows are aggregated rather than dropped. The handful
    of tracts TCAC genuinely does not map have **no** opportunity category, and a methodology
    that weights lower-income units by resource category has to decide explicitly what happens to
    them. Silently treating them as Low Resource would push units toward them; silently dropping
    them would push units away. Both are choices, and both must be made in the open.

    Returns:
        Keys ``tcac_tracts``, ``tract_level_rows``, ``block_group_aggregated``,
        ``block_group_rows_used``, ``region_tracts``, ``uncovered_tracts``, ``uncovered_geoids``.
    """
    from ingest.crosswalk import load_crosswalk

    archive = cache.fetch(SOURCES["tcac_opportunity_map"], refresh=refresh)
    raw = pd.read_excel(next(cache.unzip(archive).glob("*.xlsx")))
    sd_all = raw[raw["County"] == "San Diego"]

    mapped = load_opportunity_map(refresh=refresh)
    region = set(load_crosswalk()["tract_geoid"])
    covered = set(mapped["tract_geoid"])
    uncovered = sorted(region - covered)

    return {
        "tcac_tracts": len(covered),
        "tract_level_rows": int((mapped["geography"] == "tract").sum()),
        "block_group_aggregated": int((mapped["geography"] != "tract").sum()),
        "block_group_rows_used": int(sd_all["Census Block Group"].notna().sum()),
        "region_tracts": len(region),
        "uncovered_tracts": len(uncovered),
        "uncovered_geoids": uncovered,
    }
