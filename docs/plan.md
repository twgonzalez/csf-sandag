# Project plan — 7th-cycle methodology

**Goal.** An objective 7th-cycle RHNA methodology for the SANDAG region that leans on true physical
capacity constraints as far as the AFFH objective permits, computed entirely from public data, and
reproducible by anyone with a laptop.

**Working assumption, adopted 2026-08-31: HCD reviews everything.** Every file in this
repository — code, reports, journal pages, commit messages — is written on the assumption that
the Department of Housing and Community Development will read it during methodology review.
Nothing goes in the record that we would not defend to the reviewer.

**Status.** Milestone 0 (replicate the adopted 6th-cycle allocation) is complete and passing. See
[`reports/sixth_cycle_replication.md`](../reports/sixth_cycle_replication.md). This plan covers
what follows.

**Re-sequencing note (2026-08-28).** The tract-scored allocator and the resource-only baseline
are pulled forward from Phase 6 into a standalone milestone, **D1**, because they need only
Phase 1 data — see [workplan_delta.md](workplan_delta.md). The delta-vs-adopted harness gets
built once, early, and each later phase adds a column to it instead of waiting for Phase 6.

**Effort figures** below are working sessions of an AI agent driving this repository, with the
project owner reviewing outputs and making the decisions only a human can make. The evidence for
the calibration: milestone 0 (repo, ingest, crosswalk, allocator, exact replication, reports,
tests) took one session; Phase 1 (Opportunity Map ingested and replicated exactly, capacity
framework) took one session.

What genuinely does NOT compress, in descending order of schedule risk:

1. **Human decision gates** — the open questions, the chair's read at Gate A, the board's choice
   at Gate B, the informal HCD conversation. These are the schedule now.
2. **Data friction** — discovering that a source is stale, absent, or unpublished (the FHSZ
   service vintage; sewer service-area boundaries). Probing is fast; dead ends still cost real
   sessions, and the project convention — stop and ask rather than substitute a guess — inserts
   deliberate human checkpoints.
3. **Statutory clocks** — HCD's 60-day review and 45-day revision cycle under §65584.04(i) are
   fixed in law.
4. **Review discipline** — every report should be read by a person before it travels. That is a
   feature.

---

## The design constraint, stated once

Three capacity measures are named in Gov. Code §65584.04(e) and are therefore not merely
permitted but **required to be considered**:

1. Lack of sewer or water capacity **due to federal or state** laws, regulations, regulatory
   actions, or supply and distribution decisions
2. Availability of land suitable for urban development; protected lands under federal or state
   programs
3. Emergency evacuation route capacity, wildfire risk, sea level rise, and other climate impacts

§65584.04(f) requires the COG to explain in writing how each factor was incorporated. §65584(d)(5)
requires the plan to affirmatively further fair housing. §65584.04(i) gives HCD 60 days to find
whether the methodology furthers the objectives.

**The whole methodology follows from one rule:** capacity determines *where* units go, never *how
many* a jurisdiction receives. Applied as a reducer of a jurisdiction's total, capacity collides
with §65584(d)(5). Applied as a siting input within a fixed total, it satisfies (e) and (f)
without touching (d)(5). Every phase below is built to hold that line.

---

## What every phase must produce

Each phase ends in a markdown report and its backing CSVs. A phase is not done until a person who
has not read the code can check the result. Concretely, every report must carry:

- every number's source, vintage, and the URL it came from;
- a reconciliation to a figure the publishing agency states independently, wherever one exists;
- the SHA-256 of every input file actually used, from `data/raw/manifest.json`;
- a machine acceptance test that fails the build if the check breaks.

The "How a person checks it" column below is the point of this plan. If a phase cannot offer one,
the phase is not ready to start.

---

## Phase 1 — AFFH backbone

**Goal.** Establish the fair-housing measuring stick before anything is measured against it.

**Build.** Ingest the TCAC/HCD Opportunity Map (COG-geography version) at tract level: composite
score and resource category, including the High Segregation & Poverty category. Implement the
resource-only allocation as a permanent baseline. Implement the AFFH gate — the pipeline refuses
to emit any methodology whose share of lower-income units landing in High and Highest Resource
tracts falls below that baseline.

**Verifiable output.** `reports/affh_baseline.md`

**How a person checks it.** The report states how many of the region's 737 tracts fall in each of
the six TCAC categories. TCAC publishes its own San Diego County category counts; the two must
match exactly, and the report shows both side by side. The resource-only allocation must sum to
the RHND and give every jurisdiction a nonzero allocation in every category.

**Acceptance test.** Tract counts per category equal the published TCAC summary; baseline
allocation passes the zero-sum and nonzero-per-jurisdiction tests already in
`tests/test_integration.py`.

**Depends on.** Nothing. **Effort.** 1 session. **Status: complete** — score replicated
exactly, 638/638; see `reports/opportunity_map.md`.

---

## Phase 2 — Constraint inventory

**Goal.** Get every capacity, safety and health layer onto tracts, with honest coverage notes.

**Build.** Ingest and reduce to tract shares:

| Layer | Source | Axis |
|---|---|---|
| Fire Hazard Severity Zones (LRA + SRA) | CAL FIRE | capacity, safety |
| National Flood Hazard Layer — floodway and 100-year | FEMA | capacity, safety |
| Sea level rise inundation scenarios | USGS CoSMoS | capacity, safety |
| Protected and conserved lands | CPAD / CCED | capacity |
| Pollution burden and population characteristics | CalEnviroScreen (CalEPA/OEHHA) | health |
| Sewer and water capacity limits from state or federal action | SWRCB / RWQCB orders | capacity |

Shares are of **residential** land, not raw area, using the block-level housing weights the
crosswalk already computes.

**Verifiable output.** `reports/constraint_inventory.md`

**How a person checks it.** CAL FIRE publishes FHSZ acreage by county and CPAD publishes protected
acreage by county; the report reconciles our totals to theirs and shows the difference. Where a
layer's coverage is partial, the report names the gap rather than interpolating.

**Known weak point, flagged now.** The sewer and water measure is the thinnest of the three
statutory capacity factors. The statute counts only limits arising from *state or federal* action,
and there is no clean open dataset of those — it is likely hand-assembled from Regional Water
Quality Control Board orders. **Do not let the methodology's weight structure assume this measure
lands.** If it does not, say so in the appendix under §65584.04(f) and carry the other two.

**Depends on.** Nothing. **Effort.** 2–4 sessions — the estimate is dominated by source
discovery friction, not code; the FHSZ vintage trap has already cost part of one.

---

## Phase 3 — The three-axis correlation study ← decision point

**Goal.** Answer, with evidence, the question that determines the entire methodology: **in San
Diego, does physical capacity run with or against opportunity?**

**Build.** Cross-tabulate every capacity, safety and health measure against TCAC resource category
at tract level, weighted by housing units. Report each axis separately.

**The hypothesis being tested.** That wildfire and evacuation constraint concentrate in affluent
foothill and exurban tracts, and sea level rise on expensive coast — so that a capacity-as-reducer
methodology would move units *out of* high-resource areas and *into* the lower-resource, more
segregated urban core. If that holds, capacity-as-reducer is an AFFH failure and the orthogonal
design is the only lawful option, with evidence to show a mayor who asks why.

**Safety and health are reported separately and must not be combined.** Health burden is expected
to run the *opposite* way from wildfire — concentrated in low-resource tracts. If so,
AFFH-compliant siting improves health outcomes while worsening wildfire exposure. That is a more
credible and more useful finding than either alone, and merging them into one index would destroy
it.

**Verifiable output.** `reports/capacity_opportunity_correlation.md`

**How a person checks it.** Every cell is a cross-tab of two published CSVs from Phases 1 and 2. A
reader can recompute any cell in a spreadsheet from the two files. No modelling, no weighting
choices, no parameters — this phase deliberately contains no judgement calls, so that its results
cannot be argued with on methodology grounds.

**Gate A.** This report goes to the chair before any design commitment. It determines whether the
orthogonal design is a preference or a requirement.

**Depends on.** Phases 1 and 2. **Effort.** Under one session once inputs exist — the study
is two published CSVs cross-tabulated, by design.

---

## Phase 4 — Street network and evacuation capacity

**Goal.** Compute evacuation capacity per tract, first-party, from open data and published federal
methods.

**Build.** Road network for San Diego County from OpenStreetMap via `osmnx`, retaining functional
class, lane count where tagged, and intersection geometry. From it:

- an HCM-family link and intersection capacity index per tract;
- a per-tract evacuation capacity and clearance-time estimate, following the methodology in
  NUREG/CR-7002 Rev. 1;
- an explicit, separable calibration step against published Caltrans and SANDAG traffic counts.

**On sources, and Hard constraint 6.** The Highway Capacity Manual itself is a licensed TRB
publication and is **not** used. The parameters and equations the index needs are reproduced in
free federal publications, and each parameter must cite the public source it came from:

- **FHWA, HPMS Field Manual, Appendix N** — capacity parameters including the 1,900 pc/h/ln base
  saturation flow rate. <https://www.fhwa.dot.gov/ohim/hpmsmanl/pdf/appn.pdf>
- **NRC, NUREG/CR-7002 Rev. 1**, *Criteria for Development of Evacuation Time Estimate Studies* —
  the federal evacuation-time methodology.
  <https://www.nrc.gov/docs/ML2101/ML21013A504.pdf>
- **Caltrans Highway Design Manual** — state facility standards.

Citing the free federal reproductions rather than the licensed manual is the same discipline
applied everywhere else in this repository, and it means an HCD reviewer can open every source.

**Not used: JOSH.** Evacuation capacity is computed in this repository from the federal method
above. No dependency on the sibling project. The algorithms are of the same family because both
derive from the same public literature, but every parameter here traces to a citable public
document, which is the property that matters for §65584.04(f).

**Verifiable output.** `reports/network_capacity.md` and `reports/evacuation_capacity.md`

**How a person checks it.** The calibration report lists every public traffic count station in the
county with the modeled volume beside the observed count, and the residual. A traffic engineer can
audit it station by station. Uncalibrated tracts are labelled uncalibrated rather than quietly
carrying a default.

**Depends on.** Phase 2 for hazard overlay. **Effort.** 2–3 sessions. The county OSM graph
builds in minutes and the routing is cheap; the real work is station-by-station calibration
against published counts and the honesty accounting for OSM lane-tag coverage.

---

## Phase 5 — Jobs adjustments

**Goal.** Make the jobs factor defensible enough to carry weight.

**Build.** The three adjustments specified but not yet written, each toggleable and each logged:
multi-site employer redistribution, QCEW reconciliation to county sector totals, and seasonal
annualisation to full-time equivalents (with a documented treatment of H-2A agricultural labour).

**Verifiable output.** `reports/jobs_adjustments.md`

**How a person checks it — and this is the good one.** The 6th-cycle appeals process found exactly
one error: Silver Strand Training Complex and Naval Outlying Landing Field had been treated as
remote stations of Naval Base San Diego 32nd Street, and NAS North Island's jobs needed splitting
80.5/19.5 with San Diego. It took a phone call to Naval Facilities Engineering Command, surfaced
four months after the draft allocation issued, and moved 135 units.

**The acceptance test is whether the multi-site detector finds that same error independently, from
open data, with no knowledge of the answer.** It is a known-answer test against real history. If
it passes, the case for computing this in the open is made in one sentence to any board member.
If it fails, we learn the detector is not yet good enough — before it matters.

Every redistribution is logged with the site roster used and the size proxy applied, so a reader
can check any one of them.

**Depends on.** Nothing. Runs parallel to Phase 4. **Effort.** 2–3 sessions, dominated by
assembling public site rosters (HCAI, CDE, campus and county facility lists) for the
multi-site detector.

---

## Phase 6 — The allocator, six income categories, and the frontier

**Goal.** Turn the parameter files into mechanism, and give the board a documented choice rather
than an argument.

**Build.**

- The general tract-scored allocator: `allocate/model.py`, taking the tract feature table, the
  RHND, and a parameter file, returning tract allocations that sum exactly to the RHND. This is
  what makes Hard constraint 2 true for something that could actually be adopted.
- Six income categories — acutely low, extremely low, very low, low, moderate, above moderate —
  with acutely low and extremely low held within 3% of proportionality to very low per
  §65584(d)(1). **Blocked on a decision: see Open questions below.**
- The frontier. Sweep the AFFH gate from unconstrained to maximum; at each level solve for the
  allocation minimising hazard exposure. Each point is a committed parameter file.

**Verifiable output.** `reports/frontier.md` and — the headline deliverable —
`reports/delta_vs_sixth_cycle.md`: every candidate methodology run against the 6th-cycle RHND of
171,685, side by side with the adopted allocation, deltas by jurisdiction and income category.
Three columns a board member reads first: what SANDAG adopted, what the resource-only baseline
produces, what the capacity-plus-opportunity candidate (with the corrected jobs factor from
Phase 5) produces. Same regional total in every column — the differences are pure redistribution.

Running candidates against the *6th-cycle* determination is deliberate: it is the only RHND that
exists until HCD issues the 7th-cycle number, and it turns every methodology argument into a
concrete statement — "under this rule, Santee receives X more and Solana Beach Y fewer" — that
can be checked against the adopted plan everyone already knows.

**How a person checks it.** Every point on the curve is a parameter file in `params/`. Rerunning
any one reproduces its point on the curve exactly, byte for byte. The slope at the chosen point is
the exchange rate between AFFH performance and hazard exposure, in units, at the margin — which is
the chair's question, answered as a rate rather than a verdict. Where the frontier is flat there
is no trade-off at all, and the report says so plainly. The delta table reconciles: each column
sums to 171,685, and the adopted column matches the replication already verified in milestone 0.

**Gate B.** The board picks a point on the frontier. Every point is lawful; the choice is
political, and it should be made in the open with the numbers visible.

**Depends on.** Phases 1–5, and open question 1 (six-category control totals) — a human
decision. **Effort.** 1–2 sessions; the allocator itself is pulled forward into milestone D1.

---

## Phase 7 — The HCD package

**Goal.** The document HCD reads under §65584.04(i), generated rather than written.

**Build.** The methodology appendix, generated from the docstrings: every factor, its source URL,
vintage, and rule, in the format §65584.04(f) requires — plus the written explanation of how each
§65584.04(e) factor was incorporated, and how the methodology furthers each §65584(d) objective.

**Verifiable output.** `reports/methodology_appendix.md`

**How a person checks it.** Every factor traces to a source URL, a vintage, and a SHA-256 in
`data/raw/manifest.json`. A reviewer can download any input and confirm the checksum matches the
one the report was generated against.

**Depends on.** Phase 6. **Effort.** 1 session — the appendix is generated from docstrings
that already carry their citations.

---

## Sequence

Calendar dates dropped in favour of what actually gates each step. The technical critical path
is **weeks of working sessions, not months**; the binding constraints are the human loops listed
above.

| | Phase | Agent effort | What actually gates it |
|---|---|---|---|
| 1 | AFFH backbone | **done** | — |
| 2 | Constraint inventory | 2–4 sessions | Source discovery; sewer service-area existence |
| 3 | **Correlation study** | <1 session | Phase 2 landing |
| — | **Gate A** | — | **Board leadership review** |
| 5 | Jobs adjustments | 2–3 sessions | Site-roster assembly; runs parallel to 4 |
| 4 | Network and evacuation | 2–3 sessions | OSM tag coverage; calibration counts |
| 6 | Allocator, six categories, frontier | 1–2 sessions | **Open question 1 — a human decision** |
| — | **Gate B** | — | **The board's calendar** |
| 7 | HCD package | 1 session | Phase 6 |

The late-2027 date for a draft methodology reaching HCD does not move — it is set by the
adoption process and the §65584.04(i) clocks, not by build speed. What changes is the shape of
the slack: **Gate A material can be in board leadership's hands in weeks**, which buys a year of
lead time — time for the informal HCD conversation, the counsel check, and board
socialisation — instead of the analysis arriving just in time to be argued about.

**Critical path is unchanged in kind: Phase 3.** It is now nearly free to compute, so the true
critical path is the two phases feeding it plus the chair's availability to act on it.

## Recommended alongside the technical work

**Talk to HCD informally ahead of formal submission.** Hearing "we would have concerns with that"
in a staff call costs nothing. Hearing it in the §65584.04(i) findings letter costs a revision
cycle. The concept to test with them is the orthogonal design: capacity as a siting input inside a
fixed total, never as a reducer of the total.

**Have counsel check one citation.** `allocate/guardrails.py` cites §65584.04(e)(2)(B) for the
three prohibited justifications, taken from SANDAG's own restatement in its adopted 6th-cycle
methodology. The section has been amended repeatedly and that subdivision letter may have moved.
The substance is right; the pincite will appear in the generated appendix that HCD reads.

**Expect the framing fight.** A chart showing hazard exposure rising with AFFH performance will be
quoted without its context. The defences are built into the plan above: report both directions of
the trade-off, keep safety and health on separate axes, publish the mitigation-adjusted result
alongside the raw one, and never emit a single scalar "cost of AFFH". The honest and strongest
position is that this reconciles competing factors the statute itself imposes, with the arithmetic
open — which is what §65584.04(f) asks for and what has not been done rigorously before.

---

## Open questions that block work

1. **Six-category control totals.** HCD has not issued a 7th-cycle determination. Until it does,
   what should the pipeline use — a placeholder RHND, or the 6th-cycle determination resplit into
   six categories? Blocks Phase 6.
2. **Mitigation assumption for wildfire exposure.** A unit built to current WUI standards is not
   the risk the surrounding 1970s stock is. Does the safety axis report raw exposure,
   mitigation-adjusted exposure, or both? Recommend both, with raw as the headline and adjusted
   beside it. Shapes Phases 3 and 4.
3. **AMI-based affordability.** The jobs-housing fit metric currently uses LODES wage bands, fixed
   in nominal dollars and drifting against area median income yearly. Keying it to HCD's published
   State Income Limits would answer the statutory question directly. Which vintage gets pinned, and
   does the pipeline track the annual reissue or hold one vintage for the cycle?
4. **Transit factor.** 65% of the 6th-cycle allocation ran on proprietary model output counting
   *stations*. Should the 7th-cycle transit factor replicate the station count from open GTFS
   (reproducible, but keeps a crude measure), or replace it with a jobs-reachable-in-45-minutes
   accessibility surface (better measure, not comparable to the 6th cycle)?
