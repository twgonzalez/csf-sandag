"""The bedroom lens: what a unit-counted allocation delivers in the thing families need.

RHNA's ledger counts units — a studio and a four-bedroom house are the same entry. The
fairness objective, meanwhile, exists to put *families* near good schools. On expensive
coastal land the units that pencil are small ones, so a unit-denominated coastal obligation
can satisfy the ledger while delivering little of what the objective is for. This report
measures the landscape (bedrooms per unit of the existing stock, by opportunity standing and
jurisdiction) and prices the gap (bedrooms delivered under two build-out mixes of the same
allocations). Predictions were committed before computing
(``docs/predictions_bedroom_lens.md``, commit 4123581) and are scored inline.

Conventions, stated once: ACS B25041; a studio counts as one sleeping room and "5 or more"
counts as exactly 5 (the pipeline's existing convention — it *understates* the difference
between family stock and small-unit stock, so the gap measured here is conservative). The
small-unit scenario assumes 1.0 bedroom per allocated unit, with 0.75 and 1.25 shown as
sensitivity; the local-mix scenario assumes new units arrive at each tract's existing
bedrooms-per-unit ratio. Neither is a forecast of what gets built — together they bracket
what the ledger cannot see.
"""

from __future__ import annotations

import pandas as pd

from allocate.model import allocate, allocation_feature_table
from allocate.params import load_methodology
from config import REPORTS, RHND_6TH_CYCLE_BY_CATEGORY
from ingest.crosswalk import load_crosswalk
from ingest.opportunity_map import load_opportunity_map
from metrics.housing import bedrooms, housing_units

#: The five high-resource coastal cities the predictions name, and the four whose combined
#: gap prediction 3 prices (Coronado is excluded there: its obligation is small and its
#: stock is the predicted outlier).
COASTAL_HIGH_RESOURCE = ("carlsbad", "encinitas", "solana_beach", "del_mar", "coronado")
GAP_CITIES = ("carlsbad", "encinitas", "solana_beach", "del_mar")

SMALL_UNIT_BEDROOMS = 1.0
SMALL_UNIT_SENSITIVITY = (0.75, 1.25)

RUNS = (
    "resource_only",
    "capacity_within_bins",
    "jobs_within_bins",
    "composition_jobs",
    "composition_jobs_capacity",
)


def _tract_table() -> pd.DataFrame:
    """Bedrooms per unit, opportunity standing, and dominant jurisdiction, per tract."""
    stock = housing_units()[["tract_geoid", "housing_units"]].merge(
        bedrooms()[["tract_geoid", "total_bedrooms"]], on="tract_geoid", how="inner"
    )
    stock = stock[stock["housing_units"] > 0].copy()
    stock["bedrooms_per_unit"] = stock["total_bedrooms"] / stock["housing_units"]

    opportunity = load_opportunity_map()[["tract_geoid", "opportunity_category"]]
    stock = stock.merge(opportunity, on="tract_geoid", how="left")

    crosswalk = load_crosswalk()
    dominant = (
        crosswalk.sort_values(["tract_geoid", "weight"], ascending=[True, False])
        .drop_duplicates("tract_geoid")
        .set_index("tract_geoid")["jurisdiction"]
    )
    stock["jurisdiction"] = stock["tract_geoid"].map(dominant)
    return stock


def _bpu(stock: pd.DataFrame, mask) -> float:
    sub = stock[mask]
    return float(sub["total_bedrooms"].sum() / sub["housing_units"].sum())


def write() -> dict:
    """Compute the bedroom lens, write ``reports/bedroom_lens.md``, score the predictions."""
    stock = _tract_table()
    high = stock["opportunity_category"].isin(["High Resource", "Highest Resource"])

    county_bpu = _bpu(stock, stock["housing_units"] > 0)
    high_bpu = _bpu(stock, high)
    city_bpu = {j: _bpu(stock, stock["jurisdiction"] == j) for j in COASTAL_HIGH_RESOURCE}

    # ---- allocations -> bedrooms delivered under the two mixes, per jurisdiction.
    features = allocation_feature_table()
    per_tract_bpu = stock.set_index("tract_geoid")["bedrooms_per_unit"]
    crosswalk = load_crosswalk()
    dominant = (
        crosswalk.sort_values(["tract_geoid", "weight"], ascending=[True, False])
        .drop_duplicates("tract_geoid")
        .set_index("tract_geoid")["jurisdiction"]
    )

    delivered: dict[str, pd.DataFrame] = {}
    for name in RUNS:
        allocation = allocate(
            load_methodology(name), RHND_6TH_CYCLE_BY_CATEGORY, features=features, write=False
        )
        frame = allocation[["tract_geoid", "total"]].copy()
        frame["jurisdiction"] = frame["tract_geoid"].map(dominant)
        frame["bpu_local"] = (
            frame["tract_geoid"].map(per_tract_bpu).fillna(county_bpu).clip(lower=0.5)
        )
        frame["bedrooms_local_mix"] = frame["total"] * frame["bpu_local"]
        frame["bedrooms_small_unit"] = frame["total"] * SMALL_UNIT_BEDROOMS
        delivered[name] = frame.groupby("jurisdiction")[
            ["total", "bedrooms_local_mix", "bedrooms_small_unit"]
        ].sum()

    base = delivered["resource_only"]
    gap_units = float(base.loc[list(GAP_CITIES), "total"].sum())
    gap_local = float(base.loc[list(GAP_CITIES), "bedrooms_local_mix"].sum())
    gap_small = float(base.loc[list(GAP_CITIES), "bedrooms_small_unit"].sum())
    gap = gap_local - gap_small

    # ---- predictions, scored.
    scored = [
        {
            "n": 1,
            "claim": "High/Highest tracts average >=15% more bedrooms per unit than the county",
            "measured": f"county {county_bpu:.2f} · High/Highest {high_bpu:.2f} "
            f"({high_bpu / county_bpu - 1:+.1%})",
            "hit": high_bpu >= 1.15 * county_bpu,
        },
        {
            "n": 2,
            "claim": "all five high-resource coastal cities beat the county average",
            "measured": " · ".join(f"{j} {city_bpu[j]:.2f}" for j in COASTAL_HIGH_RESOURCE),
            "hit": all(city_bpu[j] > county_bpu for j in COASTAL_HIGH_RESOURCE),
        },
        {
            "n": 3,
            "claim": "four-city studio loophole >= 20,000 bedrooms; "
            "small-unit <= half of local mix",
            "measured": f"local mix {gap_local:,.0f} bedrooms · small-unit {gap_small:,.0f} · "
            f"gap {gap:,.0f}",
            "hit": gap >= 20_000 and gap_small <= 0.5 * gap_local,
        },
        {
            "n": 4,
            "claim": "Coronado has the lowest bedrooms per unit of the five",
            "measured": min(city_bpu, key=city_bpu.get)
            + f" is lowest at {min(city_bpu.values()):.2f}",
            "hit": min(city_bpu, key=city_bpu.get) == "coronado",
        },
    ]
    hits = sum(1 for p in scored if p["hit"])

    # ---- report.
    lines: list[str] = []
    add = lines.append
    add("# The bedroom lens")
    add("")
    add("RHNA counts units; families need bedrooms. This report measures what the ledger")
    add("cannot see. Conventions: ACS B25041, studio = one sleeping room, 5+ = 5 (both")
    add("conservative for the gap measured here). Predictions committed at 4123581.")
    add("")
    add("## The existing landscape")
    add("")
    add(f"County bedrooms per unit: **{county_bpu:.2f}**. High/Highest Resource tracts:")
    add(f"**{high_bpu:.2f}** ({high_bpu / county_bpu - 1:+.1%} vs county).")
    add("")
    add("| Jurisdiction | Bedrooms per unit, existing stock |")
    add("|---|---|")
    for j in COASTAL_HIGH_RESOURCE:
        add(f"| {j} | {city_bpu[j]:.2f} |")
    add(f"| county | {county_bpu:.2f} |")
    add("")
    add("## Bedrooms delivered by the same allocation, under two build mixes")
    add("")
    add("Fairness-baseline obligations for the four coastal-archetype cities, converted to")
    add("bedrooms two ways: built at each tract's existing local mix, or built at the")
    add(f"small-unit mix that pencils on expensive land ({SMALL_UNIT_BEDROOMS:.2f} BR/unit;")
    lo, hi = SMALL_UNIT_SENSITIVITY
    add(f"sensitivity {lo:.2f}-{hi:.2f} shown).")
    add("")
    add("| Jurisdiction | Units | Bedrooms at local mix | Bedrooms at small-unit mix | Gap |")
    add("|---|---|---|---|---|")
    for j in GAP_CITIES:
        row = base.loc[j]
        add(
            f"| {j} | {row['total']:,.0f} | {row['bedrooms_local_mix']:,.0f} "
            f"| {row['bedrooms_small_unit']:,.0f} "
            f"| {row['bedrooms_local_mix'] - row['bedrooms_small_unit']:,.0f} |"
        )
    add(
        f"| **four cities** | {gap_units:,.0f} | {gap_local:,.0f} | {gap_small:,.0f} "
        f"| **{gap:,.0f}** |"
    )
    add("")
    add(
        f"Sensitivity: at {lo:.2f} BR/unit the four-city small-unit total is "
        f"{gap_units * lo:,.0f} bedrooms; at {hi:.2f}, {gap_units * hi:,.0f}. The gap to the "
        f"local mix stays between {gap_local - gap_units * hi:,.0f} and "
        f"{gap_local - gap_units * lo:,.0f} bedrooms."
    )
    add("")
    add("The same conversion across all five formula runs, four-city totals:")
    add("")
    add("| Run | Units | Bedrooms at local mix | At small-unit mix |")
    add("|---|---|---|---|")
    for name in RUNS:
        d = delivered[name]
        add(
            f"| {name} | {d.loc[list(GAP_CITIES), 'total'].sum():,.0f} "
            f"| {d.loc[list(GAP_CITIES), 'bedrooms_local_mix'].sum():,.0f} "
            f"| {d.loc[list(GAP_CITIES), 'bedrooms_small_unit'].sum():,.0f} |"
        )
    add("")
    add("## Predictions, scored")
    add("")
    add(f"**{hits} of {len(scored)} hit.**")
    add("")
    add("| # | Prediction | Measured | Verdict |")
    add("|---|---|---|---|")
    for p in scored:
        add(f"| {p['n']} | {p['claim']} | {p['measured']} | {'HIT' if p['hit'] else 'MISS'} |")
    add("")
    add("## What this does and does not say")
    add("")
    add("Neither mix is a forecast. The point is that the state's ledger cannot distinguish")
    add("them: both satisfy the same RHNA obligation. Nor do cities fully control the mix:")
    add("zoning is written in units per acre, not bedrooms, the rezonings the state's numbers")
    add("force default to densities that favor small units, and a bedroom mandate on")
    add("market-rate projects can be waived under density-bonus law, bypassed by streamlining")
    add("statutes, or reviewed away as a constraint. What survives is narrower: bedroom")
    add("proportionality on the subsidized share (standard inclusionary practice), incentives")
    add("for family-sized homes, family-need allocation factors such as overcrowding, and a")
    add("published bedroom ledger — which nothing can waive.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "bedroom_lens.md").write_text("\n".join(lines) + "\n")
    return {
        "report_path": "reports/bedroom_lens.md",
        "predictions_hit": hits,
        "predictions_total": len(scored),
        "county_bpu": round(county_bpu, 2),
        "four_city_gap_bedrooms": round(gap),
    }
