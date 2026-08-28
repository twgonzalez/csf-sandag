"""The delta report — milestones D1.4 and D1.5.

The first candidate methodology run against the 6th-cycle RHND, side by side with the adopted
allocation. Every column sums to 171,685; the differences are pure redistribution.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from allocate.model import affh_share, allocate, allocation_feature_table, to_jurisdictions
from allocate.params import load_methodology
from config import INCOME_4, REPORTS, RHND_6TH_CYCLE_BY_CATEGORY, RHND_6TH_CYCLE_TOTAL
from ingest.sixth_cycle import adopted_allocation_wide, check_allocation_sources_agree
from report.tables import display_names, write_pair

LOWER_INCOME = ("very_low", "low")


def build(*, write: bool = True) -> dict:
    """Run the resource-only baseline and write ``reports/delta_vs_sixth_cycle.md``.

    Returns:
        Summary dict including the AFFH baseline share -- the gate constant.
    """
    check_allocation_sources_agree()
    adopted = adopted_allocation_wide()

    methodology = load_methodology("resource_only")
    features = allocation_feature_table()
    tracts = allocate(methodology, RHND_6TH_CYCLE_BY_CATEGORY, features=features)
    baseline = to_jurisdictions(tracts, RHND_6TH_CYCLE_BY_CATEGORY)
    gate = affh_share(tracts)

    totals = pd.DataFrame(
        {
            "Adopted 6th cycle": adopted["total"],
            "Resource-only": baseline["total"],
        }
    )
    totals["Delta"] = totals["Resource-only"] - totals["Adopted 6th cycle"]
    totals["Delta %"] = (totals["Delta"] / totals["Adopted 6th cycle"] * 100).round(1)
    totals = totals.sort_values("Delta", ascending=False)
    totals.index = display_names(totals.index)

    lower = pd.DataFrame(
        {
            "Adopted (VL+L)": adopted[list(LOWER_INCOME)].sum(axis=1),
            "Resource-only (VL+L)": baseline[list(LOWER_INCOME)].sum(axis=1),
        }
    )
    lower["Delta"] = lower["Resource-only (VL+L)"] - lower["Adopted (VL+L)"]
    lower = lower.sort_values("Delta", ascending=False)
    lower.index = display_names(lower.index)

    summary = {
        "affh_baseline_share": gate,
        "regional_total": int(baseline["total"].sum()),
        "columns_reconcile": int(baseline["total"].sum()) == RHND_6TH_CYCLE_TOTAL
        and int(adopted["total"].sum()) == RHND_6TH_CYCLE_TOTAL,
        "delta_sums_to_zero": int(totals["Delta"].sum()) == 0,
    }
    if not write:
        return summary

    csv_dir = REPORTS / "delta_vs_sixth_cycle"
    totals_md = write_pair(totals, csv_dir / "jurisdiction_totals.csv")
    lower_md = write_pair(lower, csv_dir / "lower_income.csv")
    baseline_out = baseline.copy()
    baseline_out.index.name = "jurisdiction"
    baseline_out.to_csv(csv_dir / "resource_only_by_category.csv")
    tracts.to_csv(csv_dir / "resource_only_tracts.csv", index=False)

    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    floor = methodology.parameters.get("floor_weight")

    body = f"""# Delta vs the adopted 6th cycle

*Generated {generated} · Milestone D1 · first candidate column*

## What this report is, and is not

The **resource-only baseline** run against the 6th-cycle RHND of {RHND_6TH_CYCLE_TOTAL:,} units,
beside the allocation SANDAG adopted in July 2020. Both columns sum to the same regional total;
every difference is pure redistribution.

**The baseline is a measuring stick, not a proposal.** It answers one question — where would
units go if the fair-housing objective in Gov. Code §65584(d)(5) were the *only* lower-income
driver — so that every real candidate methodology can be scored against it. Quoting its numbers
as a recommendation would misread the entire design.

Rule (full spec in [`params/resource_only.toml`](../params/resource_only.toml)): lower-income
units distributed across High and Highest Resource tracts by existing housing units; moderate and
above-moderate across all tracts by existing housing units; a {floor} floor spread over all
tracts so every jurisdiction receives a nonzero allocation in every category (§65584(d)(1));
rounding per category at the jurisdiction level.

## The AFFH gate constant

> **{gate:.4f}** — share of lower-income units the baseline places in High or Highest Resource
> tracts.

This is the number every candidate methodology must meet or beat before the pipeline will emit
it. It is not 1.0000 because the nonzero floor deliberately sends {floor:.0%} of each category
everywhere — the gap between {gate:.4f} and 1 is the statutory floor at work, priced.

The adopted 6th-cycle allocation has **no measurable value on this axis**: it allocated to
jurisdictions, never to tracts, so the share of its lower-income units in high-resource tracts
is unknowable from the adopted documents. A tract-scored methodology is auditable on the AFFH
objective in a way the adopted one structurally cannot be.

## Jurisdiction totals

{totals_md}

## Lower-income units (very low + low)

{lower_md}

## Reading the table honestly

Three things the numbers say, including one that cuts against this project's earlier framing:

1. **Resource weighting does not concentrate housing in the small coastal cities — but it does
   raise them substantially.** San Diego city falls by roughly a quarter (it holds ~56% of the
   region's high-resource housing, but the adopted methodology's transit component weighted it
   even harder). Carlsbad, Encinitas, Poway and Solana Beach all rise steeply in percentage
   terms because their stock is entirely high-resource. Small base, large percentage: Del Mar's
   +{int(totals.loc["Del Mar", "Delta"]):,} units is a {totals.loc["Del Mar", "Delta %"]:.0f}% increase on 163.
2. **The unincorporated county is the largest riser in absolute units** — it holds the region's
   largest housing stock and a meaningful high-resource share once TCAC's block-group tracts are
   aggregated correctly.
3. **The four jurisdictions with ~no high-resource housing receive lower-income units only
   through the floor** — El Cajon's {int(baseline.loc["el_cajon", "very_low"])} very-low units
   are the floor working as §65584(d)(1) requires, and a candidate methodology that wants to
   send them more must argue for it on some axis other than resource.

A capacity-weighted candidate will move these numbers again — that is the point of the harness.
Each later phase adds a column to this report against the same fixed adopted baseline.

## Reconciliation

| Check | Result |
|---|---|
| Adopted column sums to the RHND | {int(adopted["total"].sum()):,} = {RHND_6TH_CYCLE_TOTAL:,} |
| Resource-only column sums to the RHND | {int(baseline["total"].sum()):,} = {RHND_6TH_CYCLE_TOTAL:,} |
| Delta column sums to zero | {int(totals["Delta"].sum())} |
| Category totals match HCD determination | {", ".join(f"{c.replace('_', ' ')} {int(baseline[c].sum()):,}" for c in INCOME_4)} |
| Every jurisdiction nonzero in every category | yes (asserted in code) |
| Adopted column matches Plan Table 4.7 and the open-data portal | verified this run |

Tract-level allocation: [`delta_vs_sixth_cycle/resource_only_tracts.csv`](delta_vs_sixth_cycle/resource_only_tracts.csv)
— any jurisdiction number above is recomputable from it plus the crosswalk.
"""
    out_path = REPORTS / "delta_vs_sixth_cycle.md"
    out_path.write_text(body)
    summary["report_path"] = str(out_path)
    return summary
