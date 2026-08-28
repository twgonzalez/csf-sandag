# Status

What is built, what is stubbed, what is blocked. Updated 2026-08-27.

The brief said to build in layer order and to report the 6th-cycle replication before building
anything else. That is where this stands: **milestone 1 is complete and passing**, Layers 1 and 2
are partially built to the depth the replication and the first feature table needed, and Layers 3
and 4 exist in the form the replication required.

**What happens next is in [plan.md](plan.md)** — seven phases, each ending in a report a person
can check without reading code.

---

## Milestone 1 — 6th-cycle replication: PASS

The adopted allocation is reproduced to within **2 units in any of the 76 jurisdiction-by-income
cells**, and **1 unit in any jurisdiction total**, out of a regional determination of 171,685.
All remaining difference is rounding. See [`reports/sixth_cycle_replication.md`](../reports/sixth_cycle_replication.md).

### Two findings worth a board's attention

**1. The adopted methodology is missing a step, and the step is load-bearing.**

The equity adjustment produces four numbers per jurisdiction that do not sum to 100% — SANDAG's
own Table 5 shows Carlsbad's summing to 111.9%. Neither the methodology adopted 22 November 2019
nor the Plan adopted 10 July 2020 says what to do about that. The adopted allocation is
reproduced only by iterative proportional fitting to both margins. Reading the documents the
obvious way instead — normalising each jurisdiction's row on its own — misses cells by up to
**990 units**.

A jurisdiction preparing an appeal under Gov. Code §65584.05 had 45 days and could not have
recomputed its own allocation from the documents it was given. This step had to be recovered here
by working backwards from the published result.

**2. The one correction the appeals process produced was a multi-site employer error — the exact
defect Layer 2 is designed to catch automatically.**

The only difference between the draft and adopted allocations is a jobs correction affecting
three jurisdictions. Silver Strand Training Complex (Coronado) and Naval Outlying Landing Field
(Imperial Beach) had been treated as remote stations of Naval Base San Diego 32nd Street; NAS
North Island's jobs were reassigned 80.5/19.5 between Coronado and San Diego by land area. That
moved 135 units.

It surfaced in February 2020, through a conversation with Naval Facilities Engineering Command,
four months after the draft allocation was issued, and only because Coronado could afford to
appeal. `metrics/adjustments/multi_site.py` is specified to detect this class of error from open
data before an allocation is issued. It is not yet built (see below).

---

## Layer status

### Layer 1 — Ingest

| Source | Status | Notes |
|---|---|---|
| SANDAG 6th-cycle adopted allocation | **built** | Socrata `t9sh-dzf3`, cross-checked against Plan Table 4.7 every run |
| SANDAG 6th-cycle methodology inputs | **built** | Transcribed from cited PDFs; both PDFs checksum-verified per run |
| Tract-to-jurisdiction crosswalk | **built** | 737 tracts, 190 crossing a boundary, split by 2020 block housing units |
| LEHD LODES (WAC, RAC, OD) | **built** | LODES8 vintage 2023, block level, wage bands and 20 NAICS sectors |
| ACS 5-year | **built** | 10 tables, tract level, estimates and margins of error; API or bulk |
| TIGER boundaries | **built** | Blocks (2020), places, tracts, counties |
| Census Data API (optional) | **built** | Equivalence to the bulk path asserted by tests |
| QCEW / EDD | **not built** | Needed for reconciliation and seasonality curves |
| HCD Annual Progress Reports | **deliberately not built** | See "Refused inputs" below |
| DOF E-5 | **not built** | |
| TCAC/HCD Opportunity Map | **built** | Replicated exactly; see reports/opportunity_map.md |
| OpenStreetMap network | **not built** | |
| Caltrans / SANDAG traffic counts | **not built** | |
| Hazard layers | **partial** | FHSZ (2024/2025 vintages), NFHL floodway, CPAD 2026a built; CoSMoS awaits the scenario decision; CCED not yet |

### Layer 2 — Tract metrics

| Metric | Status |
|---|---|
| Jobs by wage band and sector | **built**, unadjusted Q2 counts |
| Jobs-housing balance | **built** |
| Jobs-housing fit | **built**, with two documented limitations (below) |
| Housing by bedroom count | **built** |
| Cost burden, overcrowding, tenure | **built** |
| Workforce housing gap | **built** in units; **not built** in bedrooms |
| Opportunity bin | **built**, replicated exactly |
| Transit access (GTFS) | **not built** |
| Street network capacity | **not built** |
| Hazard constraint index | **partial** — 3 of 7 capacity indicators scored; see reports/capacity_map.md |
| Evacuation capacity (NUREG/CR-7002 method, in-repo) | **not built** — Phase 4 |
| Multi-site correction | **not built** |
| QCEW reconciliation | **not built** |
| Seasonality / FTE annualisation | **not built** |

### Layer 3 — Allocation

| Component | Status |
|---|---|
| Biproportional reconciliation | **built**, tested |
| Largest-remainder integer rounding | **built**, tested |
| Inverse-ratio equity adjustment | **built** |
| Statutory guardrails (§65584.04(e)(2)(B)) | **built**, 25 tests |
| 6th-cycle replication harness | **built**, passing |
| General tract-scored allocator | **not built** |
| Six-category income split (7th cycle) | **not built** |
| Candidate 7th-cycle methodologies | **not built** |

### Layer 4 — Reports

| Report | Status |
|---|---|
| 6th-cycle replication | **built** |
| Sensitivity (per adjustment) | **built** for the three steps that currently exist |
| Jurisdiction allocations reconciled to RHND | **built** |
| Delta vs 6th cycle / vs named run | **not built** |
| Opportunity-bin AFFH test | **not built** — blocked on the TCAC/HCD Opportunity Map ingest |
| Methodology appendix from docstrings | **not built** |

---

## Decisions taken, with reasons

**pandas, not polars.** The brief said pick one. `geopandas` is mandated and is built on pandas;
choosing polars would mean two dataframe models in one pipeline and a conversion at every spatial
boundary. Pinned at 2.2.3.

**Census bulk files by default, API as an optional accelerator.** The Census Data API now
redirects keyless requests to a "Missing Key" page. A free key is not proprietary data and would
not breach Hard constraint 6, but requiring one is a manual step, and it would mean an HCD
reviewer auditing under §65584.04(i), or a city building an appeal inside its 45-day window under
§65584.05, must first obtain credentials. That is a smaller barrier than a controlled device in a
SANDAG office, but it is the same kind of barrier, and it is the one this project argues against.

So both paths exist. `CENSUS_API_KEY` set (environment or gitignored `.env`) uses the API;
absent, the keyless bulk files. The difference is bandwidth only:

| Path | Fresh download |
|---|---|
| API key set | **37 MB** |
| Keyless (default) | **874 MB** |

The 837 MB difference is the 365 MB statewide TIGER block shapefile plus 472 MB of national ACS
table files, of which the pipeline uses San Diego County. The key is a **speed-up, never a
correctness dependency**: `tests/test_census_api.py` runs both paths over real data and fails if
a single cell disagrees. It currently asserts equality of three ACS tables across all 737 tracts,
of block housing counts across all 28,633 blocks, of the finished crosswalk weights, and of the
final 76-cell allocation. All pass with zero difference.

`ingest/census_api.py` redacts the key from every URL, error message and manifest entry, since
the Census API takes it as a query parameter. `.env` is gitignored and a test asserts that rule
is present.

**The 365 MB block shapefile, on the keyless path.** `tl_2020_06_tabblock20.zip` is the only
keyless source carrying 2020 Census housing units per block, which is what the crosswalk splits
on. County-level block files are not published for this layer. With a key, `H1_001N` from the
2020 redistricting file replaces it in one county-scoped request; the two agree on every block.

**LODES S000 only.** The `SE01`/`SE02`/`SE03` segment files are not fetched: the S000 file
already carries the three earnings bands as columns and the twenty sector groups as columns, so
one 6 MB download gives both cuts. Fetching the segment files too would triple the download and
create a second path to the same numbers.

**Reference tables are committed, not parsed.** Tables 4.1, 4.2, 4.4 and 4.7 come from PDFs. PDF
text extraction is not stable enough to satisfy Hard constraint 7, so the tables are transcribed
into `data/reference/` and the source PDFs are checksum-verified on every run. A reissue of
either PDF fails the run rather than silently changing the baseline.

---

## Refused inputs

**HCD Annual Progress Report permit data.** Listed in the brief's Layer 1 sources. It is
deliberately not ingested, and the `rhna_progress` column that arrives in the same SANDAG
open-data response as the adopted allocation is dropped at the point of ingest.

Gov. Code §65584.04(e)(2)(B)(ii) prohibits basing any jurisdiction's share on prior
underproduction, and Hard constraint 5 restates it. Permit counts have legitimate uses that are
not allocation — tracking progress against an adopted allocation, for one — but the safest way to
guarantee they never reach a factor is for them never to reach the feature table. If APR data is
needed later for a non-allocation purpose, it should land in a separate namespace that Layer 3
cannot import.

`allocate/guardrails.py` will refuse any parameter file naming it, and the refusal is written to
the run log with the statutory citation.

---

## Known limitations in what *is* built

**Jobs-housing fit rests on two approximations, both material.**

1. *Single earner.* A unit is called affordable to a wage band if its rent is at most 30% of one
   worker's earnings at the top of that band. Real households often have two earners, so the
   affordable stock is understated. The measure is accurate for single-earner households and
   conservative for the rest.
2. *Contract rent, not gross rent.* ACS B25056 excludes tenant-paid utilities. HUD's 30%
   threshold applies to gross rent (B25063). Using contract rent overstates the affordable stock.

These pull in opposite directions and do not cancel. The county-level result — 583,408 lower-wage
jobs against 38,991 rental units under $1,000 a month, a ratio near 15 to 1 — is stark enough
that neither correction changes the conclusion, but a jurisdiction-level factor built on this
metric would need both fixed first.

**The fit metric is sparse.** 235 of 737 tracts have no rental units under $1,000 a month, so
their fit ratio is undefined rather than zero. That is a real feature of the region, not a data
gap, but any methodology weighting this metric must decide explicitly what an undefined fit means
before it can be used.

**LODES jobs are unadjusted.** They are Q2 snapshots, geocoded to the employer's reporting unit,
and not reconciled to QCEW. The three corrections that would fix this are specified and not yet
built. Until they are, `jobs_total` should not carry weight in any candidate methodology.

---

## Open questions for the project owner

These need a decision before the work they block can proceed. None of them blocks anything
currently built. The full sequencing is in [plan.md](plan.md).

1. **AMI-based affordability.** The fit metric currently uses LODES wage bands, which are fixed
   in nominal dollars and drift against area median income every year. Keying it to HCD's
   published State Income Limits instead would answer the statutory question directly. HCD
   publishes these annually as an Excel file; which vintage should be pinned, and should the
   pipeline track the annual reissue or hold one vintage for the whole cycle?

2. **The six income categories.** Hard constraint 3 requires acutely low, extremely low, very
   low, low, moderate and above moderate, with the first two within 3% of proportionality to very
   low. HCD has not issued a 7th-cycle determination for the SANDAG region, and the acutely low
   category has no settled definition in the statute. What should the pipeline use as the control
   column totals until a determination is issued — a placeholder RHND, or the 6th-cycle
   determination resplit into six?

3. **Mitigation assumption for wildfire exposure.** *(Replaces the earlier question about a JOSH
   interface. Evacuation capacity is now computed in this repository from NUREG/CR-7002 Rev. 1
   rather than taken from an external score — see [plan.md](plan.md), Phase 4.)* A unit built to
   current WUI standards is not the risk the surrounding older stock is. Should the safety axis
   report raw exposure, mitigation-adjusted exposure, or both?

4. **The transit component has no open replacement yet.** 65% of the 6th-cycle allocation ran on
   SANDAG ABM output. A GTFS-based accessibility metric is the obvious open substitute, but the
   6th-cycle rule counted *stations*, not accessibility. Should the 7th-cycle transit factor
   replicate the station-count rule from open GTFS data (reproducible, but keeps a crude measure),
   or replace it with a jobs-reachable-in-45-minutes accessibility surface (better measure,
   not comparable to the 6th cycle)?
