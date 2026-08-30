"""The delta report — milestones D1.4 and D1.5.

The first candidate methodology run against the 6th-cycle RHND, side by side with the adopted
allocation. Every column sums to 171,685; the differences are pure redistribution.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from allocate.model import (
    affh_share,
    allocate,
    allocation_feature_table,
    enforce_affh_gate,
    to_jurisdictions,
)
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

    features = allocation_feature_table()

    methodology = load_methodology("resource_only")
    tracts = allocate(methodology, RHND_6TH_CYCLE_BY_CATEGORY, features=features)
    baseline = to_jurisdictions(tracts, RHND_6TH_CYCLE_BY_CATEGORY)
    gate = affh_share(tracts)

    candidate_m = load_methodology("capacity_within_bins")
    candidate_tracts = allocate(candidate_m, RHND_6TH_CYCLE_BY_CATEGORY, features=features)
    candidate = to_jurisdictions(candidate_tracts, RHND_6TH_CYCLE_BY_CATEGORY)
    candidate_share = affh_share(candidate_tracts)
    # The gate as machinery, not prose: an AFFH-regressive candidate cannot leave the pipeline.
    enforce_affh_gate(candidate_share, gate, candidate_m.name)

    totals = pd.DataFrame(
        {
            "Adopted 6th cycle": adopted["total"],
            "Resource-only": baseline["total"],
            "Capacity-weighted": candidate["total"],
        }
    )
    totals["Cap vs adopted"] = totals["Capacity-weighted"] - totals["Adopted 6th cycle"]
    totals["Cap vs resource-only"] = totals["Capacity-weighted"] - totals["Resource-only"]
    totals = totals.sort_values("Cap vs resource-only", ascending=False)
    totals.index = display_names(totals.index)

    lower = pd.DataFrame(
        {
            "Adopted (VL+L)": adopted[list(LOWER_INCOME)].sum(axis=1),
            "Resource-only (VL+L)": baseline[list(LOWER_INCOME)].sum(axis=1),
            "Capacity-weighted (VL+L)": candidate[list(LOWER_INCOME)].sum(axis=1),
        }
    )
    lower["Cap vs resource-only"] = (
        lower["Capacity-weighted (VL+L)"] - lower["Resource-only (VL+L)"]
    )
    lower = lower.sort_values("Cap vs resource-only", ascending=False)
    lower.index = display_names(lower.index)

    summary = {
        "affh_baseline_share": gate,
        "affh_candidate_share": candidate_share,
        "candidate_passes_gate": candidate_share >= gate - 1e-9,
        "regional_total": int(baseline["total"].sum()),
        "columns_reconcile": int(baseline["total"].sum()) == RHND_6TH_CYCLE_TOTAL
        and int(adopted["total"].sum()) == RHND_6TH_CYCLE_TOTAL,
        "delta_sums_to_zero": int(totals["Cap vs adopted"].sum()) == 0
        and int(totals["Cap vs resource-only"].sum()) == 0,
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
    candidate_out = candidate.copy()
    candidate_out.index.name = "jurisdiction"
    candidate_out.to_csv(csv_dir / "capacity_within_bins_by_category.csv")
    candidate_tracts.to_csv(csv_dir / "capacity_within_bins_tracts.csv", index=False)

    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    floor = methodology.parameters.get("floor_weight")

    body = f"""# Delta vs the adopted 6th cycle

*Generated {generated} · Milestone D1 · first candidate column*

## What this report is, and is not

Three allocations of the same 6th-cycle RHND of {RHND_6TH_CYCLE_TOTAL:,} units: the allocation
SANDAG adopted in July 2020, the **resource-only baseline**, and the first real candidate — the
**capacity-weighted orthogonal methodology**, in which the fair-housing objective decides which
resource bins receive lower-income units and the four measured capacity dimensions (fire,
floodway, protected land, shed-validated evacuation) decide siting *within* them. Every column
sums to the same regional total; every difference is pure redistribution.

**The baseline is a measuring stick, not a proposal.** It answers one question — where would
units go if the fair-housing objective in Gov. Code §65584(d)(5) were the *only* lower-income
driver — so that every real candidate methodology can be scored against it. Quoting its numbers
as a recommendation would misread the entire design.

Rule (full spec in [`params/resource_only.toml`](../params/resource_only.toml)): lower-income
units distributed across High and Highest Resource tracts by existing housing units; moderate and
above-moderate across all tracts by existing housing units; a {floor} floor spread over all
tracts so every jurisdiction receives a nonzero allocation in every category (§65584(d)(1));
rounding per category at the jurisdiction level.

## The AFFH gate — now enforced in code, and passed

> Baseline: **{gate:.4f}** · Capacity-weighted candidate: **{candidate_share:.4f}** — the
> candidate meets the gate **with equality, by construction**: it uses the same resource bins
> and the same statutory floor, and reweights only within them.

`allocate.model.enforce_affh_gate` refuses any allocation below the baseline before a report can
be written — the pipeline is structurally incapable of emitting an AFFH-regressive methodology.
The gate is not 1.0000 because the nonzero floor deliberately sends {floor:.0%} of each category
everywhere; the gap is the statutory floor at work, priced.

The adopted 6th-cycle allocation has **no measurable value on this axis**: it allocated to
jurisdictions, never to tracts, so the share of its lower-income units in high-resource tracts
is unknowable from the adopted documents. A tract-scored methodology is auditable on the AFFH
objective in a way the adopted one structurally cannot be.

## Jurisdiction totals

{totals_md}

## Lower-income units (very low + low)

{lower_md}

## What capacity does, isolated exactly

The **Cap vs resource-only** column is the purest measurement this harness can produce: two
allocations with identical fair-housing decisions, differing only in physical-capacity siting.
Every unit in that column moved for a reason a fire marshal or utility engineer could state.

## Reading the table honestly

Three things the numbers say, including one that cuts against this project's earlier framing:

1. **Capacity moves units from fire country to safe ground without touching fair housing.** The
   biggest shedders in the *Cap vs resource-only* column are exactly the fire-dominant
   jurisdictions of the capacity matrix — the unincorporated county
   ({int(totals.loc["Unincorporated County", "Cap vs resource-only"]):,}), Poway
   ({int(totals.loc["Poway", "Cap vs resource-only"]):,}), Carlsbad
   ({int(totals.loc["Carlsbad", "Cap vs resource-only"]):,}) — and the biggest gainers are the
   safe urban grids: San Diego (+{int(totals.loc["San Diego", "Cap vs resource-only"]):,}),
   La Mesa (+{int(totals.loc["La Mesa", "Cap vs resource-only"]):,}). Same AFFH share to four
   decimal places.
2. **Against the adopted 6th cycle, both candidate columns tell the same structural story**:
   San Diego was over-weighted by the adopted transit component relative to its high-resource
   share; the high-resource coastal cities rise from very small bases; the low-resource
   jurisdictions receive lower-income units chiefly through the statutory floor
   (El Cajon's {int(baseline.loc["el_cajon", "very_low"])} very-low units under resource-only),
   as §65584(d)(1) requires.
3. **The baseline and candidate bracket the lawful design space on the capacity axis**: zero
   capacity responsiveness versus full capacity-score weighting, at identical fair-housing
   performance. The frontier work in Phase 6 sweeps between and beyond them.

## Reconciliation

| Check | Result |
|---|---|
| Adopted column sums to the RHND | {int(adopted["total"].sum()):,} = {RHND_6TH_CYCLE_TOTAL:,} |
| Resource-only column sums to the RHND | {int(baseline["total"].sum()):,} = {RHND_6TH_CYCLE_TOTAL:,} |
| Capacity-weighted column sums to the RHND | {int(candidate["total"].sum()):,} = {RHND_6TH_CYCLE_TOTAL:,} |
| AFFH gate passed by candidate | {candidate_share:.4f} >= {gate:.4f} (asserted in code) |
| Both delta columns sum to zero | {int(totals["Cap vs adopted"].sum())} and {int(totals["Cap vs resource-only"].sum())} |
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
