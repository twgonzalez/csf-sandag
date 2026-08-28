"""The jurisdiction capacity matrix — every capacity dimension, tract-computed, city-rolled.

Answers two questions a board member will ask the moment they see the capacity map: *how does my
city rank*, and *what is actually constraining it*. The second matters more than the first: a
city constrained by protected parkland and a city constrained by fire hazard should not be
discussed in the same breath, and a single composite score would merge them.

Everything is computed at tract level and rolled up through the unit-share crosswalk (Hard
constraint 2); the exposure figures are shares of each city's *housing*, not its area.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from config import REPORTS
from ingest.crosswalk import load_crosswalk
from ingest.hazards import load_hazard_shares
from metrics.capacity import capacity_feature_table, score_capacity
from report.tables import display_names, write_pair

CAPACITY_ORDER = ["Highest Capacity", "High Capacity", "Moderate Capacity", "Low Capacity"]


def _tract_pieces() -> pd.DataFrame:
    """One row per (tract, jurisdiction) piece with its housing units and tract capacity values."""
    shares = load_hazard_shares()[
        ["tract_geoid", "share_in_vhfhsz", "share_in_floodway", "share_protected"]
    ]
    scored = score_capacity(capacity_feature_table())[
        ["tract_geoid", "capacity_score", "capacity_category"]
    ]
    pieces = load_crosswalk()[["tract_geoid", "jurisdiction", "housing_units_2020"]]
    return pieces.merge(shares, on="tract_geoid").merge(scored, on="tract_geoid")


def build(*, write: bool = True) -> dict:
    """Build the matrix and write ``reports/capacity_by_jurisdiction.md`` plus CSVs."""
    pieces = _tract_pieces()

    def weighted(group: pd.DataFrame, column: str) -> float:
        units = group["housing_units_2020"].sum()
        return float((group[column] * group["housing_units_2020"]).sum() / units) if units else 0.0

    rows = []
    for jurisdiction, group in pieces.groupby("jurisdiction"):
        units = int(group["housing_units_2020"].sum())
        row = {
            "jurisdiction": jurisdiction,
            "Housing units": units,
            "% housing in VHFHSZ": weighted(group, "share_in_vhfhsz") * 100,
            "% housing in floodway": weighted(group, "share_in_floodway") * 100,
            "% land protected (unit-wtd)": weighted(group, "share_protected") * 100,
            "Mean capacity score": weighted(group, "capacity_score"),
            "Tracts": int(group.loc[group["housing_units_2020"] > 0, "tract_geoid"].nunique()),
        }
        for category in CAPACITY_ORDER:
            in_bin = group[group["capacity_category"] == category]
            row[f"% units {category.split()[0]}"] = (
                in_bin["housing_units_2020"].sum() / units * 100 if units else 0.0
            )
        rows.append(row)

    matrix = pd.DataFrame(rows).set_index("jurisdiction")
    matrix = matrix.sort_values("Mean capacity score", ascending=False)
    matrix.insert(0, "Rank", range(1, len(matrix) + 1))

    # What drives each city's constraint: the dimension with the largest exposure.
    dims = {
        "% housing in VHFHSZ": "fire",
        "% housing in floodway": "floodway",
        "% land protected (unit-wtd)": "protected land",
    }
    exposure = matrix[list(dims)]
    matrix["Dominant constraint"] = [
        "none material" if exposure.loc[j].max() < 1.0 else dims[exposure.loc[j].idxmax()]
        for j in matrix.index
    ]

    summary = {
        "most_capacity": str(matrix.index[0]),
        "least_capacity": str(matrix.index[-1]),
        "fire_dominant": int((matrix["Dominant constraint"] == "fire").sum()),
        "protected_dominant": int((matrix["Dominant constraint"] == "protected land").sum()),
    }
    if not write:
        return summary

    display = matrix.copy()
    display.index = display_names(display.index)

    csv_dir = REPORTS / "capacity_by_jurisdiction"
    dim_cols = ["Rank", "Housing units", *dims, "Dominant constraint", "Mean capacity score"]
    dist_cols = ["Rank", *(f"% units {c.split()[0]}" for c in CAPACITY_ORDER), "Tracts"]
    dims_md = write_pair(display[dim_cols].round(1), csv_dir / "dimensions.csv")
    dist_md = write_pair(display[dist_cols].round(1), csv_dir / "distribution.csv")
    pieces.to_csv(csv_dir / "tract_pieces.csv", index=False)

    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    body = f"""# Capacity by jurisdiction

*Generated {generated} · tract-computed, rolled up by housing-unit share · 3 of 7 indicators*

## How to read this

Ranked by housing-weighted mean capacity score (higher = less physically constrained). All
figures are shares of each city's **housing**, not its area, computed at tract level and rolled
up through the unit-share crosswalk — a city is never scored directly.

**Read the Dominant constraint column before the Rank column.** A city constrained by protected
parkland and one constrained by fire hazard are different conversations: parkland is a
land-supply fact with no safety content; fire is the safety axis. A composite rank merges them,
which is exactly why the dimensions are published side by side.

Partial-evidence caveat, as everywhere: fire, floodway, and protected land only. Evacuation, sea
level rise, sewer and water are not yet measured, and evacuation in particular could reorder
this table — Coronado ranks well on land and hazard axes precisely because its binding
constraint (one bridge, one road) is not yet in the data.

## The dimensions matrix

{dims_md}

## Capacity distribution within each city

Share of each city's housing units by capacity category of the tract they sit in, plus the
number of inhabited tracts contributing:

{dist_md}

Recompute anything from [`tract_pieces.csv`](capacity_by_jurisdiction/tract_pieces.csv) — one
row per (tract, jurisdiction) piece with units and every indicator.
"""
    out_path = REPORTS / "capacity_by_jurisdiction.md"
    out_path.write_text(body)
    summary["report_path"] = str(out_path)
    return summary
