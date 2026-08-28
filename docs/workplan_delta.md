# Work plan — the first delta table

**Milestone D1.** Produce `reports/delta_vs_sixth_cycle.md`: the resource-only allocation run
against the 6th-cycle RHND of 171,685, side by side with the adopted allocation, deltas by
jurisdiction and income category. This pulls the allocator forward from Phase 6 of
[plan.md](plan.md) — a deliberate re-sequencing, because the allocator and the resource-only
baseline need **only data already ingested and verified**, and every later phase then adds a
column to a harness that already exists instead of waiting for one.

---

## What this does and does not require

| Needed | Status |
|---|---|
| CTCAC/HCD Opportunity Map at tract level | **Done** — replicated exactly |
| Tract-to-jurisdiction crosswalk with unit-share splits | **Done** |
| 6th-cycle RHND and adopted allocation | **Done** — replication passing |
| 2020 housing units per tract | **Done** (in the crosswalk) |
| IPF / largest-remainder machinery | **Done**, tested |
| Statutory guardrails | **Done**, tested |

| Not needed for D1 | When it enters |
|---|---|
| **OpenStreetMap — anything** | Phase 4 only (evacuation) |
| Hazard / protected-land layers | Phase 2 adds capacity columns to the same table |
| QCEW, jobs corrections | Phase 5 adds the corrected-jobs column |
| Six income categories | Blocked on open question 1; D1 uses the four 6th-cycle categories so the comparison is like-for-like |

**On OSM specifically, since the question will recur.** The evacuation indicator is *not* a
per-city analysis. All 737 tracts are routed simultaneously on **one drivable network for San
Diego County**, downloaded once through `osmnx` and cached like every other raw input. That is
the point of the bottleneck-attribution design: shared bottlenecks only make sense on a shared
graph. The contrast with JOSH — which builds one network per city because its unit of analysis is
a city — is structural. One download, one graph build, one routing pass, one ledger. City
boundaries never touch the computation; they enter only at roll-up, like everywhere else in the
pipeline (Hard constraint 2).

---

## The resource-only baseline, specified

The baseline is the AFFH measuring stick, so its rule has to be boringly explicit. Four income
categories, matching the 6th cycle for like-for-like comparison.

**Lower-income (very low + low):** distributed across tracts in **High and Highest Resource**
categories, proportional to 2020 housing units, with a small uniform floor weight on all other
tracts (see below).

**Moderate and above-moderate:** distributed across **all** tracts proportional to 2020 housing
units. Neutral by design — the Opportunity Map is an instrument about where lower-income housing
goes; stretching it to the other categories would claim more than the research behind it does.

**Why housing units as the mass base.** Distribution within a resource bin needs a mass base —
otherwise a 200-unit Highest Resource tract and a 7,000-unit one receive the same. Housing units
is the only base that is public, tract-level, and not derived from zoning (prohibited) or job
counts (whose corrections are Phase 5). Direction matters for legality: more existing housing →
*more* allocation, which is the opposite of the prohibited stable-population reasoning. Recorded
as a named parameter (`mass_base`) so a candidate methodology can substitute another base and the
delta shows what that choice is worth.

**The nonzero floor.** Hard constraint 4 requires every jurisdiction nonzero in every category —
and a pure High/Highest rule gives El Cajon, Imperial Beach, Lemon Grove and National City
approximately zero lower-income units, because they have almost no High/Highest housing. The
floor is therefore structural, not cosmetic: a small uniform weight (`floor_weight`, default 1%
of total category weight, spread over all tracts by unit share) applied **to the seed**, per the
rule already documented in `allocate/reconcile.py` — zeros in a seed are structural and cannot be
fixed afterwards. The floor value is a named parameter and the report states it.

**Rounding at the output geography.** Tract allocations stay fractional; they are rolled up
through the crosswalk and largest-remainder rounding is applied **at the jurisdiction level**,
per category. Rounding at the tract level first and then splitting fractional tracts across
jurisdictions would re-break the integer totals the rounding just fixed.

---

## Steps

Each lands separately with its own tests. Order is dependency order.

**D1.1 — Parameter file schema and loader.** TOML schema: methodology metadata, geography
declaration (must be `tract`; `jurisdiction` is refused outside the replication harness), factor
table with source and description per factor, income-split rule, named parameters. Loader runs
`allocate.guardrails.enforce` before anything else and writes any refusal to the run log.
*Test:* a parameter file naming a prohibited factor is refused; the 6th-cycle file still loads
under its `replication_only` flag.

**D1.2 — The allocator.** `allocate/model.py`: one function — tract feature table + RHND by
category + parameters → tract allocation matrix. Applies the floor to the seed, distributes each
category's RHND over tract weights, asserts zero-sum before returning. Rolls up via
`roll_up_to_jurisdictions`, rounds at jurisdiction level.
*Test:* synthetic fixtures — zero-sum per category, floor produces nonzero everywhere,
determinism (two runs byte-identical), a seed with a zero row raises.

**D1.3 — The resource-only parameter file.** `params/resource_only.toml` encoding the rule above,
with every choice named: bin weights, mass base, floor, rounding geography.
*Test:* loads clean through the guardrails; declared geography is tract.

**D1.4 — The AFFH baseline number.** From the D1.3 run: the share of lower-income units landing
in High and Highest Resource tracts. This constant **is** the gate for every future methodology
(plan.md, Phase 1) — computed here because the gate needs the baseline before it can refuse
anything.
*Test:* recomputing the share from the published tract CSV matches the report's number.

**D1.5 — The delta report.** `report/delta.py` → `reports/delta_vs_sixth_cycle.md` plus CSVs:
adopted allocation, resource-only allocation, delta and delta-% by jurisdiction and category;
the AFFH share of each column; reconciliation lines proving every column sums to 171,685 and to
HCD's category totals.
*How a person checks it:* the adopted column must equal the portal/Plan Table 4.7 numbers already
cross-checked every run; each delta column must sum to zero by construction; any cell is
recomputable from the tract CSV and the crosswalk CSV.

**Effort.** Roughly a week and a half of focused work. No new downloads, so no source risk.

---

## What D1 answers immediately

The delta table settles, with numbers instead of assertion, the question raised in discussion:
*does a resource-weighted allocation force the coastal cities to take the region's housing?* The
stock arithmetic says no — San Diego city holds ~56% of the region's High/Highest housing and the
six 100%-high-resource cities hold about a fifth — but D1 turns that from an estimate into a
table, per jurisdiction, per income category, against the allocation everyone already knows.

## What D1 deliberately defers

- **Six income categories** — open question 1; like-for-like against the 6th cycle requires four.
- **Capacity columns** — Phase 2 layers drop into the same feature table; each new indicator adds
  a candidate parameter file and a column to the same report.
- **Jobs factor** — enters only when Phase 5 makes it defensible; D1's baseline deliberately
  contains no jobs term at all.
