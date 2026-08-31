"""Jobs metrics from LODES, and the wage bands used to relate jobs to housing costs.

This is the open-data replacement for the "Total Jobs" column that carried 35% of the 6th-cycle
allocation from a proprietary blend.

The counts here are **unadjusted Q2 job counts**. Three corrections stand between them and a
number fit to allocate housing on, and each is a separate, toggleable function in
``metrics/adjustments/`` -- multi-site employer redistribution, QCEW reconciliation to county
sector totals, and seasonal annualisation to full-time equivalents. **None of the three is built
yet** (see ``docs/status.md``), so using :func:`workplace_jobs` in a methodology today means
accepting all three defects.
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


def corrected_workplace_jobs(*, refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Jobs per tract with the two built corrections applied: multi-site and military.

    Rule:
        Start from the raw LODES tract counts. Apply the school-district headquarters
        redistribution (zero-sum moves within districts,
        :func:`metrics.adjustments.multi_site.school_district_correction`). Add the
        uniformed-military layer (:func:`metrics.adjustments.military.military_jobs`), which
        LODES cannot see at all. The QCEW reconciliation and seasonal annualisation specified
        by Phase 5 are **not yet applied**; until they are, these counts remain Q2 snapshots.

    Returns:
        ``(tracts, log)``. One row per tract with ``jobs_total_uncorrected``,
        ``jobs_multisite_delta``, ``jobs_military``, and ``jobs_total_corrected`` = the sum of
        the three. ``log`` carries both corrections' full derivation logs.
    """
    from ingest.crosswalk import load_block_geography
    from metrics.adjustments.military import military_jobs
    from metrics.adjustments.multi_site import school_district_correction

    base = workplace_jobs()[["tract_geoid", "jobs_total"]].rename(
        columns={"jobs_total": "jobs_total_uncorrected"}
    )
    multisite, multisite_log = school_district_correction(refresh=refresh)
    military, military_log = military_jobs(refresh=refresh)

    out = (
        base.merge(
            multisite.rename(columns={"jobs_delta": "jobs_multisite_delta"}),
            on="tract_geoid",
            how="outer",
        )
        .merge(
            military.rename(columns={"military_jobs": "jobs_military"}),
            on="tract_geoid",
            how="outer",
        )
        .fillna(0.0)
        .sort_values("tract_geoid", ignore_index=True)
    )
    out["jobs_total_corrected"] = (
        out["jobs_total_uncorrected"] + out["jobs_multisite_delta"] + out["jobs_military"]
    )
    if (out["jobs_total_corrected"] < -1e-6).any():
        raise ValueError("a correction drove a tract's job count negative")

    # Jurisdiction view for the report: raw LODES straight from blocks (no tract-splitting
    # judgement), military from its own jurisdiction-level derivation, multi-site deltas
    # assigned to each tract's dominant jurisdiction by housing units (moves are within a
    # school district, which only rarely crosses a city line; the approximation is logged).
    blocks = load_block_geography()
    dominant = (
        blocks.groupby(["tract_geoid", "jurisdiction"])["housing_units_2020"]
        .sum()
        .reset_index()
        .sort_values("housing_units_2020")
        .drop_duplicates("tract_geoid", keep="last")[["tract_geoid", "jurisdiction"]]
    )
    delta_by_juris = (
        multisite.merge(dominant, on="tract_geoid", how="left")
        .groupby("jurisdiction")["jobs_delta"]
        .sum()
        .to_dict()
    )
    military_by_juris = {
        r["jurisdiction"]: r["military_jobs"] for r in military_log["by_jurisdiction"]
    }
    lodes_by_juris = {r["jurisdiction"]: r["lodes_jobs"] for r in military_log["by_jurisdiction"]}
    jurisdiction = pd.DataFrame(
        {
            "jurisdiction": sorted(lodes_by_juris),
            "lodes_jobs": [lodes_by_juris[j] for j in sorted(lodes_by_juris)],
            "multisite_delta": [round(delta_by_juris.get(j, 0.0)) for j in sorted(lodes_by_juris)],
            "military_jobs": [round(military_by_juris.get(j, 0.0)) for j in sorted(lodes_by_juris)],
        }
    )
    jurisdiction["jobs_corrected"] = (
        jurisdiction["lodes_jobs"] + jurisdiction["multisite_delta"] + jurisdiction["military_jobs"]
    )

    log = {
        "multi_site": multisite_log,
        "military": military_log,
        "by_jurisdiction": jurisdiction.to_dict(orient="records"),
    }
    return out, log
