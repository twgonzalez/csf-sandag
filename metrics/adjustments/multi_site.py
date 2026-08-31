"""The multi-site employer correction: detect headquarters job-pileups, move them to the sites.

**The defect.** LODES geocodes a job to the employer's reporting unit. A multi-site employer
that reports centrally piles every employee onto its headquarters block: a school district's
four thousand teachers appear at the district office, and the schools where they work appear
empty. This is the same defect class as the 6th cycle's one appeal correction (Navy jobs
reported at the wrong installation), and the plan's acceptance test for this machinery is that
it catches that class of error from open data before a draft issues.

**The v1 scope.** Corrections are applied only where a public roster says where the sites
actually are. School districts have exactly that roster (the California School Directory, see
:mod:`ingest.schools`), so v1 detects and redistributes district-office pileups in the
``educational_services`` sector. Everything else gets the **screen**: sector concentrations
that look like headquarters reporting are flagged in the report with the evidence, and no jobs
are moved without a roster. Detection is the product; redistribution happens only where it can
be defended row by row.

**The v1 rule**, per district with at least :data:`MIN_SITES` active schools:

- Let ``E`` be the sector's jobs in the office tract and ``S`` the sector's jobs across the
  district's school tracts. A central office should hold about :data:`OFFICE_SHARE` of a
  district's employment; anything above that is the *excess*.
- The excess is moved only when it is material (>= :data:`MIN_EXCESS`) **and** the office
  tract shows a spike signature -- at least :data:`SPIKE_MULTIPLE` times the sector jobs of
  the district's busiest school tract. A merely large office near a college fails the spike
  test rather than triggering a bogus move.
- The move is capped at :data:`PER_SITE_CAP` jobs per school site, so a college sharing the
  office tract cannot be drained into elementary schools even if every test misfires.
- Moved jobs land on the district's school tracts in proportion to site count -- the size
  proxy the roster supports. Enrollment would be better; when an open enrollment file is
  added, the proxy changes in one place and the log will say so.

Every district's numbers -- moved or not, and why -- are in the returned log, verbatim.
"""

from __future__ import annotations

import pandas as pd

from ingest.schools import load_school_roster
from metrics.jobs import workplace_jobs

#: A district needs at least this many active schools before central reporting is detectable.
MIN_SITES = 5

#: Share of a district's employment a central office may plausibly hold. Districts publish
#: staff rosters showing office staff are well under a tenth of employees; the rule is
#: deliberately generous so only clear pileups trigger.
OFFICE_SHARE = 0.10

#: Smallest excess worth moving. Below this the correction is noise against ACS-sized margins.
MIN_EXCESS = 500

#: Spike signature: the office tract must out-count the district's busiest school tract by
#: this multiple before any move happens.
SPIKE_MULTIPLE = 3.0

#: Hard ceiling on moved jobs per school site. No public school employs anything like this
#: many people, so the cap only ever binds when something else in the tract (a university,
#: a tutoring chain) is inflating the office tract's sector count.
PER_SITE_CAP = 80

_SECTOR = "educational_services"


def school_district_correction(*, refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Detect and redistribute school-district headquarters pileups.

    Returns:
        ``(deltas, log)``. ``deltas`` has columns ``tract_geoid`` and ``jobs_delta`` (the
        sector-level change; negative at office tracts, positive at school tracts, summing to
        zero). ``log`` holds one record per examined district plus the roster counts.
    """
    schools, offices, roster_log = load_school_roster(refresh=refresh)
    jobs = workplace_jobs().set_index("tract_geoid")[_SECTOR]

    site_counts = schools.groupby("district").size()
    eligible = site_counts[site_counts >= MIN_SITES].index

    deltas: dict[str, float] = {}
    records = []
    for district in sorted(eligible):
        office = offices[offices["district"] == district]
        record = {"district": district, "sites": int(site_counts[district])}
        if len(office) != 1:
            record["action"] = "skipped: no single district office in the directory"
            records.append(record)
            continue
        office_tract = office["tract_geoid"].iloc[0]
        district_school_tracts = (
            schools.loc[schools["district"] == district]
            .groupby("tract_geoid")
            .size()
            .rename("sites_in_tract")
        )
        school_tracts = district_school_tracts.drop(office_tract, errors="ignore")
        if school_tracts.empty:
            record["action"] = "skipped: every school shares the office tract"
            records.append(record)
            continue

        e = float(jobs.get(office_tract, 0.0))
        s = float(jobs.reindex(school_tracts.index).fillna(0.0).sum())
        busiest_school_tract = float(jobs.reindex(school_tracts.index).fillna(0.0).max())
        expected_office = OFFICE_SHARE * (e + s)
        excess = e - expected_office

        record.update(
            office_tract=office_tract,
            office_tract_sector_jobs=int(e),
            school_tracts_sector_jobs=int(s),
            busiest_school_tract_jobs=int(busiest_school_tract),
            excess_over_expected=int(excess),
        )
        if excess < MIN_EXCESS:
            record["action"] = "no move: excess below threshold"
        elif e < SPIKE_MULTIPLE * max(busiest_school_tract, 1.0):
            record["action"] = "flagged, not moved: no spike signature over the busiest school"
        else:
            moved = min(excess, PER_SITE_CAP * int(site_counts[district]))
            share = school_tracts / school_tracts.sum()
            deltas[office_tract] = deltas.get(office_tract, 0.0) - moved
            for tract, weight in share.items():
                deltas[tract] = deltas.get(tract, 0.0) + moved * float(weight)
            record["action"] = f"moved {int(moved)} jobs to {len(school_tracts)} school tracts"
            record["moved"] = int(moved)
            record["cap_bound"] = bool(moved < excess)
        records.append(record)

    out = (
        pd.DataFrame(
            {"tract_geoid": list(deltas), "jobs_delta": list(deltas.values())}
        ).sort_values("tract_geoid", ignore_index=True)
        if deltas
        else pd.DataFrame(columns=["tract_geoid", "jobs_delta"])
    )
    if len(out) and abs(out["jobs_delta"].sum()) > 1e-6:
        raise ValueError("multi-site deltas must sum to zero; a move leaked jobs")
    log = {
        "sector": _SECTOR,
        "thresholds": {
            "min_sites": MIN_SITES,
            "office_share": OFFICE_SHARE,
            "min_excess": MIN_EXCESS,
            "spike_multiple": SPIKE_MULTIPLE,
            "per_site_cap": PER_SITE_CAP,
        },
        "roster": roster_log,
        "districts": records,
    }
    return out, log


def concentration_screen(top_n: int = 12) -> pd.DataFrame:
    """Sector concentrations that look like headquarters reporting, for the report.

    Rule:
        For every sector, the tracts holding the largest share of the county's sector jobs.
        A tract holding a fifth of a sector is either a genuine cluster (a university, a
        hospital campus, a naval base's civilians) or a reporting address. The screen cannot
        tell which -- that is what rosters are for -- so it flags, and moves nothing.
    """
    wac = workplace_jobs()
    sectors = [
        c
        for c in wac.columns
        if c not in ("tract_geoid", "jobs_total") and not c.startswith("jobs_earning")
    ]
    rows = []
    for sector in sectors:
        total = float(wac[sector].sum())
        if total < 5_000:
            continue
        top = wac.nlargest(1, sector).iloc[0]
        share = float(top[sector]) / total
        if share >= 0.10:
            rows.append(
                {
                    "sector": sector,
                    "tract_geoid": top["tract_geoid"],
                    "tract_jobs": int(top[sector]),
                    "county_share": round(share, 3),
                }
            )
    return (
        pd.DataFrame(rows)
        .sort_values("county_share", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
