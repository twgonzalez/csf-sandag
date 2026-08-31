"""The uniformed-military jobs layer: level from SDMAC, split from ACS, placement from the Census.

LODES cannot see a sailor. Its inputs are unemployment-insurance records and OPM's federal
*civilian* files, so roughly 110,000 active-duty jobs are simply absent from the raw count --
and they are the jobs whose misplacement caused the 6th cycle's one appeal correction. This
module adds them back in three steps, each from a different open source, so no single
assumption carries the result:

1. **The county level.** Active-duty employment by service, FY 2023, from the transcribed
   SDMAC Exhibit 6 (:func:`ingest.military.county_uniformed_total`). This is the only number
   that sets the SIZE of the layer.

2. **The jurisdiction split.** ACS table B08604 counts workers where they WORK, armed forces
   included; LODES counts everything except the military, the self-employed, and a small
   unincorporated-worker remainder. So per jurisdiction::

       residual = ACS workplace workers - LODES jobs

   is military plus self-employment. The self-employment part is removed with one county-wide
   rate, computed from the county's own books: county residual minus the SDMAC military total,
   as a share of county ACS workers, is the non-military non-covered rate. Each jurisdiction's
   military estimate is its residual minus that rate times its ACS workers, floored at zero,
   restricted to jurisdictions hosting a **workforce-bearing** installation (roster rows marked
   ``major`` -- a training beach or an outlying field is a place, not a workforce), and finally
   scaled so the 19 jurisdictions sum exactly to the SDMAC county total.

3. **The tract placement.** Within a jurisdiction, military jobs land on tracts in proportion
   to 2020 Census military-quarters population (barracks and ships at homeport) -- an official
   block-level map of where the installations are. A jurisdiction with military jobs but no
   quarters (an office command, an outlying field) falls back to its LODES job distribution,
   and the fallback is logged.

Why the split is not taken from the quarters directly: Census Day 2020 caught much of the
fleet away from homeport, so quarters understate ship-heavy installations' workforces badly
(Coronado's quarters count is a fifth of its measured workplace gap). Quarters are a reliable
map of WHERE installations are, not of HOW MANY people work there; the ACS residual measures
the how-many at the jurisdiction level where it is statistically solid.

Every intermediate number -- residuals, the rate, the scale factor, the fallbacks -- is
returned in a log the report prints in full.
"""

from __future__ import annotations

import pandas as pd

from config import REFERENCE
from ingest.crosswalk import load_block_geography
from ingest.lodes import load_workplace_jobs
from ingest.military import (
    california_active_duty,
    county_uniformed_total,
    load_military_gq,
    workplace_workers_by_jurisdiction,
)


def _lodes_jobs_by_jurisdiction() -> pd.DataFrame:
    """LODES workplace jobs summed straight from blocks to jurisdictions.

    Blocks nest cleanly in jurisdictions (the crosswalk's place assignment), so this rollup
    involves no tract-splitting judgement at all.
    """
    wac = load_workplace_jobs(by="block")[["block_geoid", "jobs_total"]]
    blocks = load_block_geography()[["block_geoid", "jurisdiction"]]
    merged = wac.merge(blocks, on="block_geoid", how="left")
    unmatched = int(merged["jurisdiction"].isna().sum())
    if unmatched:
        raise ValueError(f"{unmatched} LODES blocks missing from the crosswalk")
    return (
        merged.groupby("jurisdiction", as_index=False)["jobs_total"]
        .sum()
        .rename(columns={"jobs_total": "lodes_jobs"})
    )


def military_jobs(*, refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Uniformed military jobs by tract, with the full derivation log.

    Returns:
        ``(tracts, log)``. ``tracts`` has columns ``tract_geoid`` and ``military_jobs``
        (floats; they sum exactly to the SDMAC county total). ``log`` records every
        intermediate quantity the derivation used, in the order the docstring describes.
    """
    county_total = county_uniformed_total()
    ceiling = california_active_duty(refresh=refresh)
    if not 0 < county_total < ceiling:
        raise ValueError(
            f"county uniformed total {county_total:,} fails the DMDC state ceiling {ceiling:,}"
        )

    roster = pd.read_csv(REFERENCE / "military_installations.csv")
    roster_jurisdictions = sorted(set(roster.loc[roster["workforce"] == "major", "jurisdiction"]))

    acs = workplace_workers_by_jurisdiction(refresh=refresh)
    lodes = _lodes_jobs_by_jurisdiction()
    table = acs.merge(lodes, on="jurisdiction", how="outer")
    if table.isna().any().any():
        raise ValueError("jurisdiction mismatch between ACS workplace table and LODES rollup")

    table["residual"] = table["acs_workplace_workers"] - table["lodes_jobs"]

    county_acs = float(table["acs_workplace_workers"].sum())
    county_residual = float(table["residual"].sum())
    nonmilitary_rate = max(0.0, (county_residual - county_total) / county_acs)

    table["military_raw"] = (
        table["residual"] - nonmilitary_rate * table["acs_workplace_workers"]
    ).clip(lower=0.0)
    table.loc[~table["jurisdiction"].isin(roster_jurisdictions), "military_raw"] = 0.0

    raw_sum = float(table["military_raw"].sum())
    if raw_sum <= 0:
        raise ValueError("military residuals are all zero; sources disagree fundamentally")
    scale = county_total / raw_sum
    table["military_jobs"] = table["military_raw"] * scale

    # ---- tract placement: military quarters within each jurisdiction, LODES as fallback.
    gq = load_military_gq(refresh=refresh, by="block")
    blocks = load_block_geography()[["block_geoid", "tract_geoid", "jurisdiction"]]
    gq = gq.merge(blocks, on="block_geoid", how="left")
    gq_tract = gq.groupby(["jurisdiction", "tract_geoid"], as_index=False)["military_gq"].sum()

    wac_tract = load_workplace_jobs(by="block")[["block_geoid", "jobs_total"]].merge(
        blocks, on="block_geoid", how="left"
    )
    wac_tract = wac_tract.groupby(["jurisdiction", "tract_geoid"], as_index=False)[
        "jobs_total"
    ].sum()

    placed, fallbacks = [], []
    for row in table.itertuples():
        if row.military_jobs <= 0:
            continue
        weights = gq_tract[gq_tract["jurisdiction"] == row.jurisdiction]
        weight_col = "military_gq"
        if weights.empty:
            weights = wac_tract[wac_tract["jurisdiction"] == row.jurisdiction]
            weight_col = "jobs_total"
            fallbacks.append(row.jurisdiction)
        share = weights[weight_col] / weights[weight_col].sum()
        placed.append(
            pd.DataFrame(
                {
                    "tract_geoid": weights["tract_geoid"].to_numpy(),
                    "military_jobs": (row.military_jobs * share).to_numpy(),
                }
            )
        )
    tracts = (
        pd.concat(placed, ignore_index=True)
        .groupby("tract_geoid", as_index=False)["military_jobs"]
        .sum()
        .sort_values("tract_geoid", ignore_index=True)
    )

    log = {
        "county_uniformed_total_sdmac_fy2023": county_total,
        "california_active_duty_dmdc_ceiling": ceiling,
        "county_acs_workplace_workers": int(county_acs),
        "county_lodes_jobs": int(table["lodes_jobs"].sum()),
        "county_residual_acs_minus_lodes": int(county_residual),
        "nonmilitary_noncovered_rate": round(nonmilitary_rate, 5),
        "scale_to_sdmac_total": round(scale, 5),
        "roster_jurisdictions": roster_jurisdictions,
        "placement_fallback_jurisdictions": fallbacks,
        "by_jurisdiction": table[
            ["jurisdiction", "acs_workplace_workers", "lodes_jobs", "residual", "military_jobs"]
        ]
        .sort_values("military_jobs", ascending=False)
        .to_dict(orient="records"),
    }
    return tracts, log
