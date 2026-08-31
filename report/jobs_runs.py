"""The employment-weighted candidate runs, and the adjudication of their committed predictions.

Three candidates join the resource-only baseline and the capacity run: jobs-weighted siting
within the fairness bins, the composition structure (fairness places affordable, jobs place
market-rate), and composition with capacity-weighted siting. Eight predictions were committed
before any of them ran (``docs/predictions_jobs_runs.md``, commit 18b1a8c); this report runs
the allocations, enforces the fairness gate, and scores every prediction -- misses printed
next to hits, per the standing rule.
"""

from __future__ import annotations

import pandas as pd

from allocate.model import (
    affh_share,
    allocate,
    allocation_feature_table,
    enforce_affh_gate,
    to_jurisdictions,
)
from allocate.params import load_methodology
from config import REPORTS, RHND_6TH_CYCLE_BY_CATEGORY
from ingest.sixth_cycle import adopted_allocation_wide

RUNS = (
    "resource_only",
    "capacity_within_bins",
    "jobs_within_bins",
    "composition_jobs",
    "composition_jobs_capacity",
)

_LOWER = ("very_low", "low")


def _run_all() -> tuple[dict[str, pd.DataFrame], dict[str, float]]:
    """Allocate every run against one shared feature table; enforce the gate on candidates."""
    features = allocation_feature_table()
    tracts, shares = {}, {}
    for name in RUNS:
        methodology = load_methodology(name)
        allocation = allocate(methodology, RHND_6TH_CYCLE_BY_CATEGORY, features=features)
        tracts[name] = allocation
        shares[name] = affh_share(allocation)
    baseline = shares["resource_only"]
    for name in RUNS[1:]:
        enforce_affh_gate(shares[name], baseline, name)
    return tracts, shares


def _predictions(juris: dict[str, pd.DataFrame], shares: dict[str, float]) -> list[dict]:
    """Score docs/predictions_jobs_runs.md, prediction by prediction."""

    def total(run: str, j: str) -> float:
        return float(juris[run].loc[j, "total"])

    def lower_share(run: str, j: str) -> float:
        row = juris[run].loc[j]
        return float((row["very_low"] + row["low"]) / row["total"])

    baseline = shares["resource_only"]
    out = []

    gate_equal = all(abs(shares[r] - baseline) < 1e-6 for r in RUNS[1:])
    out.append(
        {
            "n": 1,
            "claim": "all three candidates meet the gate at exactly the baseline share",
            "measured": " · ".join(f"{r}={shares[r]:.4f}" for r in RUNS),
            "hit": gate_equal,
        }
    )

    sd = total("composition_jobs", "san_diego")
    out.append(
        {
            "n": 2,
            "claim": "Metropolis composition total in 86,000-93,000",
            "measured": f"composition san_diego = {sd:,.0f}",
            "hit": 86_000 <= sd <= 93_000,
        }
    )

    poway_jobs = total("jobs_within_bins", "poway")
    poway_base = total("resource_only", "poway")
    poway_cap = total("capacity_within_bins", "poway")
    poway_full = total("composition_jobs_capacity", "poway")
    out.append(
        {
            "n": 3,
            "claim": (
                "Fire-Country rises above its benchmark under jobs_within_bins; "
                "composition+capacity lands between the capacity run and the benchmark"
            ),
            "measured": (
                f"benchmark {poway_base:,.0f} · jobs {poway_jobs:,.0f} · capacity "
                f"{poway_cap:,.0f} · comp+capacity {poway_full:,.0f}"
            ),
            "hit": poway_jobs > poway_base
            and min(poway_cap, poway_base) <= poway_full <= max(poway_cap, poway_base),
        }
    )

    sb = total("composition_jobs", "solana_beach")
    sb_base = total("resource_only", "solana_beach")
    out.append(
        {
            "n": 4,
            "claim": "composition moves the Coastal Enclave by no more than ±15% of benchmark",
            "measured": f"benchmark {sb_base:,.0f} · composition {sb:,.0f} "
            f"({(sb / sb_base - 1):+.1%})",
            "hit": abs(sb / sb_base - 1) <= 0.15,
        }
    )

    sb_ratio = lower_share("composition_jobs", "solana_beach") / lower_share(
        "resource_only", "solana_beach"
    )
    out.append(
        {
            "n": 5,
            "claim": "the Enclave's affordable share does NOT double under composition",
            "measured": f"affordable-share ratio composition/benchmark = {sb_ratio:.2f}x",
            "hit": sb_ratio < 1.5,
        }
    )

    uninc = total("composition_jobs", "unincorporated")
    out.append(
        {
            "n": 6,
            "claim": "Back Country composition total in 15,000-19,000",
            "measured": f"composition unincorporated = {uninc:,.0f}",
            "hit": 15_000 <= uninc <= 19_000,
        }
    )

    nc = total("composition_jobs", "national_city")
    nc_base = total("resource_only", "national_city")
    out.append(
        {
            "n": 7,
            "claim": "composition moves the Urban Core Suburb by no more than ±10%",
            "measured": f"benchmark {nc_base:,.0f} · composition {nc:,.0f} "
            f"({(nc / nc_base - 1):+.1%})",
            "hit": abs(nc / nc_base - 1) <= 0.10,
        }
    )

    cb = total("composition_jobs", "carlsbad")
    cb_base = total("resource_only", "carlsbad")
    cb_full = total("composition_jobs_capacity", "carlsbad")
    out.append(
        {
            "n": 8,
            "claim": (
                "Coastal-fire rises above benchmark under composition, pulled back by capacity"
            ),
            "measured": f"benchmark {cb_base:,.0f} · composition {cb:,.0f} · "
            f"comp+capacity {cb_full:,.0f}",
            "hit": cb > cb_base and cb_full < cb,
        }
    )
    return out


def write() -> dict:
    """Run the five allocations, write ``reports/jobs_runs.md``, return the CLI summary."""
    tracts, shares = _run_all()
    juris = {
        name: to_jurisdictions(allocation, RHND_6TH_CYCLE_BY_CATEGORY)
        for name, allocation in tracts.items()
    }
    adopted = adopted_allocation_wide()["total"]
    scored = _predictions(juris, shares)
    hits = sum(1 for p in scored if p["hit"])

    lines: list[str] = []
    add = lines.append
    add("# Employment-weighted candidate runs")
    add("")
    add("Five runs of the same 171,685 homes: the fairness baseline, the capacity run, and")
    add("three employment-weighted candidates built on the corrected open jobs count")
    add("(reports/jobs_adjustments.md). Predictions were committed before computing")
    add("(docs/predictions_jobs_runs.md, commit 18b1a8c) and are scored below.")
    add("")
    add("## Fairness gate")
    add("")
    add("| Run | Lower-income share in High/Highest Resource |")
    add("|---|---|")
    for name in RUNS:
        add(f"| {name} | {shares[name]:.4f} |")
    add("")
    add("Every candidate meets the gate; the allocator refuses anything below it.")
    add("")
    add("## Totals by jurisdiction")
    add("")
    add(
        "| Jurisdiction | 2020 adopted | Fairness baseline | Capacity "
        "| Jobs in bins | Composition | Comp + capacity |"
    )
    add("|---|---|---|---|---|---|---|")
    order = juris["resource_only"].sort_values("total", ascending=False).index
    for j in order:
        cells = " | ".join(f"{int(juris[r].loc[j, 'total']):,}" for r in RUNS)
        add(f"| {j} | {int(adopted[j]):,} | {cells} |")
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
    add("## Affordable share under the composition structure")
    add("")
    add("The composition option's premise is a smaller headline with a larger affordable")
    add("share. Measured, for the jurisdictions the predictions name:")
    add("")
    add(
        "| Jurisdiction | Baseline affordable share | Composition affordable share "
        "| Total, baseline → composition |"
    )
    add("|---|---|---|---|")
    for j in ("solana_beach", "del_mar", "coronado", "carlsbad", "encinitas", "san_diego"):
        b = juris["resource_only"].loc[j]
        c = juris["composition_jobs"].loc[j]
        b_share = (b["very_low"] + b["low"]) / b["total"]
        c_share = (c["very_low"] + c["low"]) / c["total"]
        add(
            f"| {j} | {b_share:.1%} | {c_share:.1%} | "
            f"{int(b['total']):,} → {int(c['total']):,} |"
        )
    add("")
    add("All figures divide the 6th-cycle total of 171,685 so they can be compared with the")
    add("adopted plan; the state's 7th-cycle total rescales everything.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "jobs_runs.md").write_text("\n".join(lines) + "\n")
    return {
        "report_path": "reports/jobs_runs.md",
        "predictions_hit": hits,
        "predictions_total": len(scored),
        "gate_shares": {k: round(v, 4) for k, v in shares.items()},
    }
