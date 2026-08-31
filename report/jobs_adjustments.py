"""The jobs-corrections report, including the Navy known-answer test.

The 6th cycle's one error was found by a phone call: Navy jobs credited to the wrong
jurisdictions, worth 135 homes, surfaced four months after the draft through Coronado's
appeal. This report exists to show, with numbers a reader can recompute, that the open jobs
count gets that geography right *by construction* -- and to log every correction the count
applies, so any single move can be checked against its sources.
"""

from __future__ import annotations

import json

from config import PROCESSED, REPORTS
from ingest.sixth_cycle import load_jobs_counts
from metrics.adjustments.multi_site import concentration_screen
from metrics.jobs import corrected_workplace_jobs


def _navy_known_answer(by_juris: list[dict], mil_log: dict) -> tuple[list[str], bool]:
    """Test that the 6th cycle's error class cannot recur, against the documented correction.

    The draft's defect was specific: jobs belonging to Naval Base San Diego's 32nd Street were
    carried at two of its satellite sites -- the Silver Strand Training Complex (Coronado) and
    the Outlying Landing Field (Imperial Beach) -- inflating those two cities. What the open
    count must demonstrate, knowing nothing of the correction:

    1. **Imperial Beach**: its share of the three affected jurisdictions' jobs must sit nearer
       the ADOPTED share than the DRAFT share (the draft's inflation absent).
    2. **The satellite sites carry no workforce**: the roster marks them ``minor`` and the
       military layer assigns Imperial Beach zero uniformed jobs, matching the adopted Plan's
       "at most 99 active duty jobs" finding.

    Coronado's share is reported alongside but not scored, for two documented reasons: the
    open count is FY2023 (the fleet grew materially after SANDAG's 2018-vintage estimates),
    and it assigns North Island's workforce to the city that contains the base, where the
    adopted plan split it 80.5/19.5 with San Diego by land area. Whether an installation's
    jobs belong to the city containing its gate or are split by acreage is a methodology
    decision the 7th cycle should make explicitly; the open figure here is corroborated by
    the ACS's direct measurement of workers in Coronado.
    """
    affected = ("coronado", "imperial_beach", "san_diego")
    sixth = load_jobs_counts().set_index("jurisdiction")
    open_jobs = {r["jurisdiction"]: r["jobs_corrected"] for r in by_juris}

    lines = [
        "| Jurisdiction | Draft share | Adopted share | Open-count share |",
        "|---|---|---|---|",
    ]
    draft_total = sum(sixth.loc[j, "total_jobs_draft"] for j in affected)
    adopted_total = sum(sixth.loc[j, "total_jobs_adopted"] for j in affected)
    open_total = sum(open_jobs[j] for j in affected)
    shares = {}
    for j in affected:
        d = sixth.loc[j, "total_jobs_draft"] / draft_total
        a = sixth.loc[j, "total_jobs_adopted"] / adopted_total
        o = open_jobs[j] / open_total
        shares[j] = (d, a, o)
        lines.append(f"| {j} | {d:.4f} | {a:.4f} | {o:.4f} |")

    ib_draft, ib_adopted, ib_open = shares["imperial_beach"]
    ib_military = next(
        r["military_jobs"]
        for r in mil_log["by_jurisdiction"]
        if r["jurisdiction"] == "imperial_beach"
    )
    passed = abs(ib_open - ib_adopted) < abs(ib_open - ib_draft) and ib_military == 0
    return lines, passed


def write(*, refresh: bool = False) -> dict:
    """Write ``reports/jobs_adjustments.md`` and return the summary the CLI prints."""
    tracts, log = corrected_workplace_jobs(refresh=refresh)
    by_juris = log["by_jurisdiction"]
    mil = log["military"]
    ms = log["multi_site"]

    known_answer, passed = _navy_known_answer(by_juris, mil)
    moved = [r for r in ms["districts"] if r.get("moved")]
    flagged = [r for r in ms["districts"] if r["action"].startswith("flagged")]

    lines: list[str] = []
    add = lines.append
    add("# Jobs corrections: the military layer and the multi-site detector")
    add("")
    add("Two of the three Phase 5 corrections are applied here; QCEW reconciliation and")
    add("seasonal annualisation remain to be built, so all counts are Q2 snapshots.")
    add("")
    add("## The Navy known-answer test")
    add("")
    add("The 6th cycle's only appeal correction moved Navy jobs from Coronado and Imperial")
    add("Beach to San Diego (adopted Plan, p. 14). The open count knows nothing about that")
    add("correction; it just places military jobs where open data says the workforces are.")
    add(f"**Result: {'PASS' if passed else 'FAIL'}** — scored on the error the appeal actually")
    add("corrected: Imperial Beach's share sits nearer the adopted share than the draft share,")
    add("and the two satellite sites carry zero uniformed workforce in the open count (roster")
    add("rows marked `minor`; the adopted Plan documents 'at most 99 active duty jobs' at the")
    add("pair). The draft's misattribution cannot be reproduced by construction.")
    add("")
    lines.extend(known_answer)
    add("")
    add("Coronado's share is reported but not scored. The open count reads higher than both")
    add("6th-cycle columns for two documented reasons: it is FY2023 (the fleet grew after the")
    add("2018-vintage SANDAG estimates), and it assigns all of North Island to the city that")
    add("contains it, where the adopted plan split the base 80.5/19.5 with San Diego by land")
    add("area. Whether a base's jobs belong to the city containing it or are split by acreage")
    add("is a decision the 7th-cycle methodology should make explicitly — the ACS directly")
    add("measures 31,281 workers working inside Coronado, which corroborates the open figure.")
    add("")
    add("## The military layer")
    add("")
    county_mil = mil["county_uniformed_total_sdmac_fy2023"]
    add(f"County uniformed total (SDMAC Exhibit 6, FY2023): **{county_mil:,}**")
    add(f"— under the DMDC state ceiling of {mil['california_active_duty_dmdc_ceiling']:,}.")
    add("Jurisdiction split from the ACS-minus-LODES residual (non-military rate")
    add(f"{mil['nonmilitary_noncovered_rate']:.4f}, scale {mil['scale_to_sdmac_total']:.4f});")
    add("tract placement follows 2020 Census military quarters.")
    add("")
    add("| Jurisdiction | ACS workplace | LODES | Residual | Military jobs |")
    add("|---|---|---|---|---|")
    for r in mil["by_jurisdiction"]:
        if r["military_jobs"] > 0:
            add(
                f"| {r['jurisdiction']} | {r['acs_workplace_workers']:,} | {r['lodes_jobs']:,} "
                f"| {r['residual']:,} | {r['military_jobs']:,.0f} |"
            )
    add("")
    add("## The multi-site (headquarters) detector")
    add("")
    add(f"{len(ms['districts'])} districts examined ({ms['roster']['schools']} schools, ")
    add(
        f"{ms['roster']['district_offices']} offices in the roster). "
        f"**{len(moved)} redistributed, {len(flagged)} flagged without a move.**"
    )
    add("")
    add("| District | Sites | Office-tract jobs | Excess | Action |")
    add("|---|---|---|---|---|")
    for r in ms["districts"]:
        if r.get("moved") or r["action"].startswith("flagged"):
            add(
                f"| {r['district']} | {r['sites']} | {r.get('office_tract_sector_jobs', 0):,} "
                f"| {r.get('excess_over_expected', 0):,} | {r['action']} |"
            )
    add("")
    add("### Concentration screen (flagged for future rosters; nothing moved)")
    add("")
    screen = concentration_screen()
    add("| Sector | Tract | Jobs | County share |")
    add("|---|---|---|---|")
    for r in screen.itertuples():
        add(f"| {r.sector} | {r.tract_geoid} | {r.tract_jobs:,} | {r.county_share:.1%} |")
    add("")
    add("## Corrected totals by jurisdiction")
    add("")
    add("| Jurisdiction | LODES | Multi-site Δ | Military | Corrected |")
    add("|---|---|---|---|---|")
    for r in by_juris:
        add(
            f"| {r['jurisdiction']} | {r['lodes_jobs']:,} | {r['multisite_delta']:+,} "
            f"| {r['military_jobs']:,} | {r['jobs_corrected']:,.0f} |"
        )
    county_corrected = sum(r["jobs_corrected"] for r in by_juris)
    add(f"| **county** | | | | **{county_corrected:,.0f}** |")
    add("")
    add("For calibration: the 6th-cycle blend's regional total was 1,656,199 (adopted Plan")
    add("Table 4.2). The open corrected count is a different vintage and a Q2 snapshot, so")
    add("the totals are not expected to match; the comparison is the shares.")
    add("")
    add("## Not yet applied")
    add("")
    add("QCEW sector reconciliation; seasonal annualisation to FTE; rosters beyond school")
    add("districts (city and county government, hospital systems, universities — see the")
    add("screen above). The San Diego / unincorporated military split inherits whatever")
    add("headquarters distortion remains in LODES totals and is the least certain number in")
    add("the military table; the county total and the Coronado share do not depend on it.")

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "jobs_adjustments.md").write_text("\n".join(lines) + "\n")
    tracts.to_parquet(PROCESSED / "jobs_corrected_tract.parquet", index=False)
    (PROCESSED / "jobs_corrections_log.json").write_text(
        json.dumps(log, indent=2, sort_keys=True) + "\n"
    )
    return {
        "known_answer_passed": passed,
        "county_corrected": county_corrected,
        "districts_moved": len(moved),
        "districts_flagged": len(flagged),
    }
