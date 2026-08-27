"""Jobs metrics from LODES, and the wage bands used to relate jobs to housing costs.

This is the open-data replacement for the "Total Jobs" column that carried 35% of the 6th-cycle
allocation from a proprietary blend.

The counts here are **unadjusted Q2 job counts**. Three corrections stand between them and a
number fit to allocate housing on, and each is a separate, toggleable function in
``metrics/adjustments/``: multi-site employer redistribution, QCEW reconciliation to county
sector totals, and seasonal annualisation to full-time equivalents. Using
:func:`workplace_jobs` directly in a methodology means accepting all three defects.
"""

from __future__ import annotations

import pandas as pd

from ingest.lodes import EARNINGS_BANDS, SECTORS, load_residence_jobs, load_workplace_jobs

#: The monthly earnings thresholds LODES uses to cut CE01/CE02/CE03, in nominal dollars.
#: Fixed since the series began and never indexed, so they slip against area median income every
#: year. Source: LODES Technical Document 8.2, table of WAC variables.
LODES_EARNINGS_THRESHOLDS_MONTHLY = {"ce01_ce02": 1_250, "ce02_ce03": 3_333}

#: The share of income a household can spend on housing before it is cost-burdened. HUD's
#: threshold, and the one HCD applies in the RHNA determination.
AFFORDABILITY_RATIO = 0.30


def workplace_jobs() -> pd.DataFrame:
    """Jobs per tract counted at the workplace, by wage band and sector.

    Rule:
        LODES Workplace Area Characteristics, all jobs (segment S000, job type JT00). Wage bands
        are the published CE01/CE02/CE03 columns; sectors are CNS01-CNS20.

    Source:
        LEHD LODES8, vintage pinned in ``config.LODES_VINTAGE``. Reference period is the second
        quarter of that year.

    Returns:
        Columns ``tract_geoid``, ``jobs_total``, the three wage-band columns, and twenty sector
        columns.
    """
    return load_workplace_jobs(by="tract")


def resident_workers() -> pd.DataFrame:
    """Employed residents per tract, by wage band, counted at the worker's home.

    Rule:
        LODES Residence Area Characteristics, all jobs. A tract's resident workers are the people
        who sleep there and hold a job somewhere; its workplace jobs are the jobs located there
        whoever fills them. The gap between the two is what jobs-housing balance measures.

    Returns:
        Columns ``tract_geoid``, ``resident_workers_total``, and one column per wage band.
    """
    rac = load_residence_jobs(by="tract")
    return rac.rename(
        columns={"jobs_total": "resident_workers_total"}
        | {v: f"resident_{v}" for v in EARNINGS_BANDS.values()}
    )[
        [
            "tract_geoid",
            "resident_workers_total",
            *(f"resident_{v}" for v in EARNINGS_BANDS.values()),
        ]
    ]


def affordable_monthly_housing_cost(monthly_earnings: float) -> float:
    """Monthly housing cost affordable to a single earner at a given wage.

    Rule:
        30% of monthly earnings, per :data:`AFFORDABILITY_RATIO`.

    Warning:
        This assumes **one earner per household**. Real households often have two, which makes
        this a conservative estimate of what a household holding one such job can afford, and an
        accurate estimate of what a single-earner household can. The jobs-housing *fit* metric
        inherits the assumption; :func:`metrics.jobs_housing.jobs_housing_fit` states it again at
        the point of use, and it is the single largest judgement call in that metric.
    """
    return monthly_earnings * AFFORDABILITY_RATIO


#: Monthly housing cost affordable to a worker at the top of each LODES wage band, under the
#: single-earner assumption. CE01's ceiling of $1,250/month supports $375/month in rent; CE02's
#: ceiling of $3,333 supports $1,000. These are the cut points
#: :func:`metrics.jobs_housing.affordable_units_by_wage_band` uses against the rent distribution.
WAGE_BAND_AFFORDABLE_RENT = {
    "jobs_earning_1250_or_less": affordable_monthly_housing_cost(
        LODES_EARNINGS_THRESHOLDS_MONTHLY["ce01_ce02"]
    ),
    "jobs_earning_1251_to_3333": affordable_monthly_housing_cost(
        LODES_EARNINGS_THRESHOLDS_MONTHLY["ce02_ce03"]
    ),
}


def jobs_by_wage_band() -> pd.DataFrame:
    """Workplace jobs collapsed to the three wage bands, with a lower-wage roll-up.

    Rule:
        ``lower_wage_jobs`` is CE01 + CE02, i.e. every job paying $3,333 a month or less. That is
        the group whose housing options the jobs-housing fit metric is about.

    Returns:
        Columns ``tract_geoid``, ``jobs_total``, the three band columns, and ``lower_wage_jobs``.
    """
    wac = workplace_jobs()
    bands = list(EARNINGS_BANDS.values())
    out = wac[["tract_geoid", "jobs_total", *bands]].copy()
    out["lower_wage_jobs"] = out["jobs_earning_1250_or_less"] + out["jobs_earning_1251_to_3333"]
    return out


def jobs_by_sector() -> pd.DataFrame:
    """Workplace jobs by NAICS sector group, for QCEW reconciliation and seasonality curves."""
    wac = workplace_jobs()
    return wac[["tract_geoid", *SECTORS.values()]].copy()
