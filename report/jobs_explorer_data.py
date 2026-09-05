"""Data emitter for the city jobs explorer — the drill-down page's committed blob.

The explorer follows the communication-stack rule for interactive pages: **the page computes
nothing**. This module extracts everything the page shows from the pipeline's outputs, writes
it as one JSON blob, and injects the blob between markers in ``tools/jobs-explorer.html`` so
the published page is a single self-contained file. Regenerating and re-committing the blob is
how the page updates; the page itself only formats.

The contract — one object with:

``meta``
    ``generated`` (date), ``lodes_vintage``, ``regional`` totals (2019 draft, 2019 adopted,
    open corrected), and the global caveat string shown under every city.

``cities`` (keyed by jurisdiction key, 19 entries)
    ``name``
        Display name.
    ``open`` — the corrected count and its provenance
        ``civilian`` (census-visible jobs, LODES rollup), ``military`` (the uniformed layer),
        ``hq_delta`` (headquarters correction, signed), ``corrected`` (their sum).
    ``blend2019``
        ``draft`` and ``adopted``, from SANDAG's published tables.
    ``shares``
        ``adopted_2019`` and ``open`` — each city's fraction of its column's regional total.
    ``derivation`` — the military layer's work, shown so a reader can follow it
        ``acs_workers`` (ACS workers-by-workplace), ``lodes`` (census-visible jobs),
        ``residual`` (their difference).
    ``sectors``
        The city's census-visible jobs by NAICS sector group, descending, as
        ``[label, count]`` pairs (all twenty; the page shows the top eight).
    ``wages``
        Census-visible jobs in the three published earnings bands, low to high.
    ``tracts``
        Every census tract whose dominant jurisdiction is this city, descending by corrected
        jobs: ``[tract_geoid, corrected, military, hq_delta]``.
    ``caveats``
        City-specific caveat strings, rendered as banners. Written here, in one place, so the
        numbers never travel without their qualifications: the straddling-base convention for
        National City, fleet growth plus the whole-place convention for Coronado, the military
        split uncertainty for San Diego and the unincorporated county, the no-workforce
        satellite sites for Imperial Beach.

Sources feeding the blob: ``data/processed/jobs_corrections_log.json`` and
``jobs_corrected_tract.parquet`` (the corrected count and its logs), LODES block files rolled
up through the crosswalk (sectors and wage bands), and
``data/reference/sixth_cycle_jobs.csv`` (the 2019 tables).
"""

from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from config import LODES_VINTAGE, PROCESSED, REFERENCE, ROOT
from ingest.crosswalk import load_block_geography
from ingest.lodes import EARNINGS_BANDS, SECTORS, load_workplace_jobs

EXPLORER_HTML = ROOT / "tools" / "jobs-explorer.html"
EXPLORER_JSON = ROOT / "tools" / "jobs_explorer_data.json"

_MARK_START = "/*__EXPLORER_DATA_START__*/"
_MARK_END = "/*__EXPLORER_DATA_END__*/"

GLOBAL_CAVEAT = (
    "Open counts are second-quarter 2023 snapshots (census workplace data with military and "
    "headquarters corrections), not yet reconciled to state sector totals. The 2019 column is "
    "SANDAG's published table, roughly 2018-vintage, from a proprietary blend. Levels differ "
    "by vintage and definition — the meaningful comparison is each city's share."
)

CITY_CAVEATS: dict[str, list[str]] = {
    "national_city": [
        "Naval Base San Diego straddles the San Diego–National City line. The 2019 blend "
        "credited National City with roughly 14,000 of its jobs by the Navy's site "
        "conventions; both open sources place those jobs in San Diego and agree with each "
        "other within ~300 (census 23,336; ACS 23,034). Which city a straddling base's jobs "
        "belong to is a definitional choice the 7th cycle should make explicitly."
    ],
    "coronado": [
        "Higher than the 2019 figure for two documented reasons: about 15% more Navy "
        "active-duty in the county between the fiscal-2019 and fiscal-2023 counts, and a "
        "convention difference — this count assigns all of North Island to Coronado, where "
        "the adopted plan split the base 80.5/19.5 with San Diego by land area."
    ],
    "san_diego": [
        "The military layer's split between San Diego and the unincorporated county is the "
        "least certain corrected number; the county total does not depend on it."
    ],
    "unincorporated": [
        "The military layer's split between San Diego and the unincorporated county is the "
        "least certain corrected number; the county total does not depend on it."
    ],
    "imperial_beach": [
        "The Outlying Landing Field carries no workforce in this count — the adopted 2020 "
        "Plan documents 'at most 99 active duty jobs' there. The draft 2019 error that "
        "inflated Imperial Beach cannot recur from these sources."
    ],
}


def build() -> dict:
    """Assemble the blob, write the JSON, and inject it into the explorer page."""
    log = json.loads((PROCESSED / "jobs_corrections_log.json").read_text())
    by_juris = {r["jurisdiction"]: r for r in log["by_jurisdiction"]}
    mil = {r["jurisdiction"]: r for r in log["military"]["by_jurisdiction"]}

    sixth = pd.read_csv(REFERENCE / "sixth_cycle_jobs.csv").set_index("jurisdiction")
    names = pd.read_csv(REFERENCE / "jurisdictions.csv").set_index("jurisdiction")["name"]

    blocks = load_block_geography()[["block_geoid", "tract_geoid", "jurisdiction"]]
    wac = load_workplace_jobs(by="block").merge(blocks, on="block_geoid", how="left")
    sector_cols = list(SECTORS.values())
    band_cols = list(EARNINGS_BANDS.values())
    by_city = wac.groupby("jurisdiction")[sector_cols + band_cols].sum()

    tracts = pd.read_parquet(PROCESSED / "jobs_corrected_tract.parquet")
    dominant = (
        load_block_geography()
        .groupby(["tract_geoid", "jurisdiction"])["housing_units_2020"]
        .sum()
        .reset_index()
        .sort_values("housing_units_2020")
        .drop_duplicates("tract_geoid", keep="last")
        .set_index("tract_geoid")["jurisdiction"]
    )
    tracts["jurisdiction"] = tracts["tract_geoid"].map(dominant)

    adopted_total = int(sixth["total_jobs_adopted"].sum())
    open_total = sum(r["jobs_corrected"] for r in log["by_jurisdiction"])

    cities: dict[str, dict] = {}
    for key in sorted(by_juris):
        j = by_juris[key]
        m = mil[key]
        sect = by_city.loc[key, sector_cols].sort_values(ascending=False)
        city_tracts = tracts[tracts["jurisdiction"] == key].sort_values(
            "jobs_total_corrected", ascending=False
        )
        cities[key] = {
            "name": str(names[key]),
            "open": {
                "civilian": int(j["lodes_jobs"]),
                "military": round(float(j["military_jobs"])),
                "hq_delta": int(j["multisite_delta"]),
                "corrected": round(float(j["jobs_corrected"])),
            },
            "blend2019": {
                "draft": int(sixth.loc[key, "total_jobs_draft"]),
                "adopted": int(sixth.loc[key, "total_jobs_adopted"]),
            },
            "shares": {
                "adopted_2019": round(
                    float(sixth.loc[key, "total_jobs_adopted"]) / adopted_total, 5
                ),
                "open": round(float(j["jobs_corrected"]) / open_total, 5),
            },
            "derivation": {
                "acs_workers": int(m["acs_workplace_workers"]),
                "lodes": int(m["lodes_jobs"]),
                "residual": int(m["residual"]),
            },
            "sectors": [[label.replace("_", " "), int(count)] for label, count in sect.items()],
            "wages": [int(by_city.loc[key, c]) for c in band_cols],
            "tracts": [
                [
                    row.tract_geoid,
                    round(float(row.jobs_total_corrected)),
                    round(float(row.jobs_military)),
                    round(float(row.jobs_multisite_delta)),
                ]
                for row in city_tracts.itertuples()
            ],
            "caveats": CITY_CAVEATS.get(key, []),
        }

    data = {
        "meta": {
            "generated": dt.date.today().isoformat(),
            "lodes_vintage": LODES_VINTAGE,
            "regional": {
                "draft_2019": int(sixth["total_jobs_draft"].sum()),
                "adopted_2019": adopted_total,
                "open_corrected": round(open_total),
            },
            "global_caveat": GLOBAL_CAVEAT,
        },
        "cities": cities,
    }

    EXPLORER_JSON.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, separators=(",", ":"))
    EXPLORER_JSON.write_text(blob + "\n")

    if EXPLORER_HTML.exists():
        page = EXPLORER_HTML.read_text()
        start = page.index(_MARK_START) + len(_MARK_START)
        end = page.index(_MARK_END)
        EXPLORER_HTML.write_text(page[:start] + blob + page[end:])

    return {
        "cities": len(cities),
        "json_kb": round(len(blob) / 1024),
        "injected": EXPLORER_HTML.exists(),
    }
