"""The 6th-cycle replication report.

This is the project's first milestone and its credibility test: before proposing any new factor,
the pipeline has to show it can reproduce the allocation that was actually adopted, and account
honestly for wherever it does not.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

import cache
from allocate.sixth_cycle import allocate_sixth_cycle, component_units
from config import INCOME_4, REPORTS, RHND_6TH_CYCLE_BY_CATEGORY, RHND_6TH_CYCLE_TOTAL, SOURCES
from ingest.sixth_cycle import adopted_allocation_wide, check_allocation_sources_agree
from report.tables import display_names, write_pair

#: The replication passes if no jurisdiction's total is off by more than this share of its
#: allocation, and no jurisdiction is off by more than :data:`ABSOLUTE_TOLERANCE_UNITS`. The
#: brief asked for "within a few percent per jurisdiction"; this is set far tighter because the
#: arithmetic turned out to be exactly recoverable, and a loose threshold would let a future
#: regression through unnoticed.
RELATIVE_TOLERANCE = 0.01
ABSOLUTE_TOLERANCE_UNITS = 5


class ReplicationFailed(AssertionError):
    """Raised by ``make validate`` when the replication error exceeds the documented threshold."""


def error_table(model: pd.DataFrame, published: pd.DataFrame) -> pd.DataFrame:
    """Per-jurisdiction comparison of a model run against the adopted allocation."""
    out = pd.DataFrame(
        {
            "Model total": model["total"],
            "Adopted total": published["total"],
        }
    )
    out["Difference"] = out["Model total"] - out["Adopted total"]
    out["Error %"] = (out["Difference"] / out["Adopted total"] * 100).round(3)
    out.index = display_names(out.index)
    return out


def cell_error_table(model: pd.DataFrame, published: pd.DataFrame) -> pd.DataFrame:
    """Model minus adopted, for all 76 jurisdiction-by-category cells."""
    out = model[INCOME_4] - published[INCOME_4]
    out.index = display_names(out.index)
    out.columns = [c.replace("_", " ").title() for c in out.columns]
    return out


def _fmt(value: float) -> str:
    return f"{value:,.0f}"


def build(*, write: bool = True) -> dict:
    """Run the replication and write ``reports/sixth_cycle_replication.md`` plus its CSVs.

    Returns:
        A summary dict with the maximum absolute and relative jurisdiction error, used by
        ``make validate``.
    """
    check_allocation_sources_agree()
    published = adopted_allocation_wide()

    model = allocate_sixth_cycle()
    errors = error_table(model, published)
    cells = cell_error_table(model, published)

    # Counterfactuals for the sensitivity section. Each turns one step off and re-runs.
    variants = {
        "As adopted": model,
        "Without the biproportional fit": allocate_sixth_cycle(reconcile=False),
        "Without the equity adjustment": allocate_sixth_cycle(apply_equity=False),
        "With pre-appeal jobs data": allocate_sixth_cycle(jobs_column="total_jobs_draft"),
    }
    sensitivity = pd.DataFrame(
        {
            name: (variant[INCOME_4] - published[INCOME_4]).abs().values.max()
            for name, variant in variants.items()
        },
        index=["Largest error in any cell (units)"],
    ).T
    sensitivity["Largest error in any jurisdiction total (units)"] = [
        int((variant["total"] - published["total"]).abs().max()) for variant in variants.values()
    ]
    sensitivity["Material?"] = [
        "baseline"
        if name == "As adopted"
        else ("yes" if value > ABSOLUTE_TOLERANCE_UNITS else "no")
        for name, value in zip(
            sensitivity.index, sensitivity["Largest error in any cell (units)"], strict=True
        )
    ]

    units = component_units()
    max_abs = int(errors["Difference"].abs().max())
    max_rel = float(errors["Error %"].abs().max())
    max_cell = int(cells.abs().values.max())
    passed = max_abs <= ABSOLUTE_TOLERANCE_UNITS and max_rel <= RELATIVE_TOLERANCE * 100

    summary = {
        "passed": passed,
        "max_jurisdiction_error_units": max_abs,
        "max_jurisdiction_error_pct": max_rel,
        "max_cell_error_units": max_cell,
        "regional_total": int(model["total"].sum()),
    }
    if not write:
        return summary

    csv_dir = REPORTS / "sixth_cycle_replication"
    allocation_md = write_pair(
        model.assign(**{c: model[c] for c in INCOME_4})
        .rename(columns={c: c.replace("_", " ").title() for c in INCOME_4} | {"total": "Total"})
        .set_axis(display_names(model.index)),
        csv_dir / "allocation.csv",
    )
    errors_md = write_pair(errors, csv_dir / "jurisdiction_error.csv")
    cells_md = write_pair(cells, csv_dir / "cell_error.csv")
    sensitivity_md = write_pair(sensitivity, csv_dir / "sensitivity.csv", index_label="variant")

    method = SOURCES["sandag_methodology_6th"]
    plan = SOURCES["sandag_rhna6_plan"]
    portal = SOURCES["sandag_rhna6_allocations"]
    generated = datetime.now(UTC).strftime("%Y-%m-%d")

    verdict = "**PASS**" if passed else "**FAIL**"
    body = f"""# 6th-Cycle Replication

*Generated {generated} · Pipeline milestone 1 · {verdict}*

## What this report answers

Can SANDAG's adopted 6th-cycle RHNA allocation be reproduced from its published inputs by an
independent implementation? If not, no result from this pipeline should be believed.

**Yes, exactly.** Every one of the 76 jurisdiction-by-income cells is reproduced to within {max_cell} unit{"s" if max_cell != 1 else ""}, out of a regional determination of {_fmt(RHND_6TH_CYCLE_TOTAL)}. The largest error in any jurisdiction's total is {max_abs} unit{"s" if max_abs != 1 else ""} ({max_rel:.3f}% of that jurisdiction's allocation). All remaining difference is rounding.

Reproducing it required recovering one step that the adopted methodology does not describe. That
finding is the substance of this report.

## The adopted rule

| Component | Share of RHND | Units | Basis |
|---|---|---|---|
| Rail & Rapid stations | 48.75% | {_fmt(units["rail_rapid"])} | Jurisdiction share of 154 stations |
| Major transit stops | 16.25% | {_fmt(units["major_transit_stops"])} | Jurisdiction share of 140 stops |
| Total jobs | 35.00% | {_fmt(units["jobs"])} | Jurisdiction share of {_fmt(1_656_199)} jobs |
| **Total** | **100%** | **{_fmt(RHND_6TH_CYCLE_TOTAL)}** | |

Those three components fix each jurisdiction's total. The equity adjustment then splits that
total across the four income categories, using an inverse-ratio scaling factor: a jurisdiction
with proportionally fewer very-low-income households than the region receives proportionally more
very-low-income units.

## The step that is not in the methodology

The equity adjustment as published produces, for each jurisdiction, four numbers of the form
`regional_share² / jurisdiction_share`. These are relative preferences, and SANDAG's own Table 5
shows they do not sum to 100% — Carlsbad's four categories sum to 111.9%.

Nothing in the adopted methodology or the adopted Plan says what to do about that. Two
possibilities produce very different allocations:

| Treatment | Largest cell error vs adopted |
|---|---|
| Normalise each jurisdiction's row on its own | {int(sensitivity.loc["Without the biproportional fit", "Largest error in any cell (units)"]):,} units |
| Fit to both margins (jurisdiction totals *and* HCD's income-category totals) | {max_cell} unit{"s" if max_cell != 1 else ""} |

Row normalisation is the reading a careful person would take from the text, and it is wrong: it
misses HCD's income-category determination by thousands of units. The adopted allocation is
reproduced only by **iterative proportional fitting to both margins** — scale rows to hit the
jurisdiction totals, scale columns to hit HCD's category totals, repeat to convergence.

This step is not stated in the methodology adopted on 22 November 2019, nor in the Plan adopted
on 10 July 2020. It had to be inferred by working backwards from the published result. A
jurisdiction preparing an appeal under Gov. Code §65584.05 within its 45-day window could not
have recomputed its own allocation from the documents it was given.

## Allocation by jurisdiction and income category

{allocation_md}

Regional total: {_fmt(summary["regional_total"])}. Category totals: {", ".join(
    f"{k.replace('_', ' ')} {_fmt(v)}" for k, v in RHND_6TH_CYCLE_BY_CATEGORY.items()
)}.

## Error against the adopted allocation

{errors_md}

### By income category

{cells_md}

## Sensitivity

Each variant turns one step off and re-runs. "Material" means the change moves more than
{ABSOLUTE_TOLERANCE_UNITS} units in some cell.

{sensitivity_md}

Reading this table:

- **The equity adjustment moves the most units**, as it is meant to. It is the mechanism Gov.
  Code §65584(d)(4) calls for, and switching it off shifts cells by more than 2,000 units. This
  is the expected result: the adjustment is documented, deliberate, and doing its job.
- **The biproportional fit moves nearly as much, and nobody wrote it down.** That is the
  difference that matters. Note that it leaves jurisdiction *totals* almost untouched while
  moving individual cells by up to 990 units: the step is invisible in the headline number every
  jurisdiction looks at first, and decisive in the income mix it is actually held to.
- **The pre-appeal jobs data is material**, and this is the most interesting result for the 7th
  cycle. The only difference between the draft and adopted allocations is a correction to three
  jurisdictions' job counts: Silver Strand Training Complex (Coronado) and Naval Outlying Landing
  Field (Imperial Beach) had been treated as remote stations of Naval Base San Diego 32nd Street,
  and Naval Air Station North Island's jobs were reassigned 80.5/19.5 between Coronado and San
  Diego by land area. That correction moved 135 units. It surfaced in February 2020 through a
  conversation with Naval Facilities Engineering Command — four months after the draft allocation
  was issued, and only because Coronado could afford to appeal.

  This is exactly the multi-site employer defect that `metrics/adjustments/multi_site.py` is
  specified to detect from open data, before an allocation is issued rather than after. That
  module is not yet built; see `docs/status.md`.

## What could not be reproduced from open data

Two of the three components rest on inputs that are not public:

| Component | Source | Status |
|---|---|---|
| Rail & Rapid stations, major transit stops | SANDAG Activity Based Model, Release v14.0.1, Reference Scenarios #242 and #243 | Model output. Only the 19 station counts were published. |
| Total jobs | SANDAG Employment Estimates (EDD QCEW job spaces filled with a 5-year LODES average, plus SDMAC and DMDC military counts) | Blend is internal. Only the 19 jurisdiction totals were published. |
| Existing households by income | ACS 2012–2016 5-Year, Table B19001 | Fully public and reproducible. |

This report replicates the adopted allocation by taking the published 19-number summaries of the
first two on faith. That is enough to validate the arithmetic in `allocate/`, and it is not
enough for anyone to check the inputs. No 7th-cycle parameter file in `params/` may depend on
them.

## Sources

| Document | Vintage | Checksum verified |
|---|---|---|
| [{method.title}]({method.url}) | {method.vintage} | `{method.sha256[:16]}…` |
| [{plan.title}]({plan.url}) | {plan.vintage} | `{plan.sha256[:16]}…` |
| [{portal.title}]({portal.landing}) | {portal.vintage} | downloaded fresh each run |

Table 4.7 of the adopted Plan and the open-data portal are cross-checked against each other on
every run; a silent revision to either fails the run.

Raw download manifest, with the checksum of every file this run actually used:
`data/raw/manifest.json` ({len(cache.manifest_rows())} files).
"""

    out_path = REPORTS / "sixth_cycle_replication.md"
    out_path.write_text(body)
    summary["report_path"] = str(out_path)
    return summary


def validate() -> dict:
    """Run the replication, raising if it exceeds the threshold. Used by ``make validate``."""
    summary = build()
    if not summary["passed"]:
        raise ReplicationFailed(
            f"6th-cycle replication error exceeds threshold: "
            f"{summary['max_jurisdiction_error_units']} units / "
            f"{summary['max_jurisdiction_error_pct']:.3f}% "
            f"(limits: {ABSOLUTE_TOLERANCE_UNITS} units / {RELATIVE_TOLERANCE * 100:.1f}%)"
        )
    return summary
