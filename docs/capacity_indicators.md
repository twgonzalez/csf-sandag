# Capacity indicator specification

The authoritative definition of every capacity indicator: its objective measure, its data source,
how it reaches a tract, and how it is scored. `metrics/capacity.py` implements this document. If
the two disagree, this document is wrong and should be corrected — the code is generated from
these definitions, not the other way round.

Nothing here may be built without a public source. Where a source does not exist, the indicator
says so and is excluded from scoring rather than estimated.

---

## 1. Design rules

**Marginal, not stock.** Every indicator asks *what does the next increment of housing cost
here*, not *how much is already here*. This is the difference between a permitted factor and
prohibited "built out" reasoning, and it is not a matter of phrasing:

| Framing | Example | Status |
|---|---|---|
| Proportional to existing stock | "100 units is 8% of Del Mar" | **Prohibited** — Gov. Code §65584.04(e)(2)(B), stable population |
| Marginal physical impact | "100 units adds 6 minutes to clearance time for 2,400 existing residents" | **Permitted** — §65584.04(e) names evacuation route capacity |

**Density is demand, never capacity.** Density alone as a constraint is the prohibited argument.
Density in a measured ratio against measured egress or treatment capacity is physics. The
distinction is enforced by construction: no indicator takes density as an input except as the
numerator of a ratio whose denominator is an independently measured capacity.

**Orientation.** Every scored indicator is oriented so **higher means more able to accommodate
housing**. Constraint measures are stored as their complement or reciprocal.
`metrics.capacity.check_orientation` refuses to score a table where this does not hold, because a
sign error would invert the map without making any single number look implausible.

**Two values per indicator.** Each publishes an interpretable continuous value (minutes, units,
share) *and* the scoring form. Reports show the interpretable one; the score uses the other.

---

## 2. Correspondence to the Opportunity Map

The Capacity Map is scored by the CTCAC/HCD Opportunity Map's own rule, verified exactly against
TCAC's published output in `metrics/opportunity.py`:

```
score = count(indicator >= regional median) + 1
```

Identical construction buys three things. The two maps cross-tabulate on one page. The scoring
cannot be attacked as ad hoc — it is the state's method on different inputs. And **nothing is
weighted**, so there are no coefficients to argue about in a board meeting.

| | Opportunity Map | Capacity Map |
|---|---|---|
| Indicators | 8 (economic, education) | see §3 |
| Comparison | at or above regional median | at or above regional median |
| Region | San Diego County (TCAC's own region definition) | San Diego County, same tract population |
| Median basis | unweighted across tracts | unweighted across tracts, to match |
| Penalty term | environmental burden flag, subtracted | none |
| Score range | 1–9 | 1 – (n+1) |
| Bands | Highest / High / Moderate / Low Resource | Highest / High / Moderate / Low Capacity |

**Scoring population.** Only indicators available for **every** tract in the region are scored.
An indicator with partial coverage is reported and excluded, because a tract scored on four
indicators and one scored on six are not comparable, and a fraction-of-available scheme hides
that behind a number that looks like it means something. Which indicators were excluded, and why,
appears at the top of every Capacity Map report.

**The cross-tab.** 4 opportunity categories × 4 capacity categories = 16 cells, each reporting
tract count and 2020 housing units. This is the Phase 3 deliverable, and the whole point of
matching construction is that a reader can check any cell from two published CSVs.

---

## 3. The indicators

### 3.1 Evacuation — `evacuation_units_accommodatable`

**Domain:** Evacuation. **Statutory hook:** §65584.04(e), "emergency evacuation route capacity."

**Concept.** Find the geographic bottlenecks a tract's evacuating traffic depends on, attribute
each bottleneck's load among the tracts that share it, and measure how many dwelling units the
tract can add before the first bottleneck it depends on saturates. A JOSH-style contribution
threshold — "no project may consume more than X% of a bottleneck's remaining headroom" — is a
level set of this same surface, so the indicator supports both a scored factor and, later, a hard
siting bound in the allocator.

**Objective measure.**

```
units_addable(t) = min over bottlenecks b on tract t's evacuation routes of:

    headroom_share(t, b) × (capacity_b − assigned_load_b)
    ─────────────────────────────────────────────────────
    vehicles_per_unit(t) × share_of_t_flow_through_b
```

Higher is more capacity. Expressed in dwelling units, like the sewer and water measures, so the
three infrastructure-family indicators read in the same currency.

**Why bottleneck attribution and not per-tract max flow.** Max flow computed independently per
tract double-counts shared links: every tract on the Coronado peninsula sees the bridge's full
capacity in its own max-flow, so summing tract capacities counts the bridge once per tract. The
measure looks fine tract by tract and overstates aggregate capacity exactly where evacuation
constraint actually lives — where many tracts share one outlet. Attribution measures the shared
link once and divides its load among the tracts that depend on it.

**The four steps, all deterministic.**

1. **Route.** Assign every tract's evacuation demand — households × vehicles per household from
   ACS B25044 — to the road network along free-flow shortest paths to the regional exit set,
   all tracts simultaneously, all-or-nothing.
2. **Find bottlenecks.** Every link now has an assigned load and a capacity (lanes × per-lane
   capacity from the FHWA parameters). A tract's *binding* bottleneck is the link with the worst
   load-to-capacity ratio along its assigned routes. This is where the bridge appears: it
   carries the summed load of every peninsula tract against one capacity.
3. **Attribute.** Tract *t*'s contribution to bottleneck *b* is the share of *b*'s assigned load
   that is *t*'s vehicles. This falls directly out of step 1 — no additional model.
4. **Headroom.** Apply the formula above.

**Why all-or-nothing shortest paths and not a congestion equilibrium.** The simple assignment is
deterministic and — more important — checkable by a person: a fire marshal can look at "tract X's
traffic goes down Jamacha Road to SR-94" on a map and say whether it is right. An equilibrium
model's output can only be checked by another equilibrium model, which is the kind of modelling
opacity this project exists to avoid. The cost is that assignment ignores congestion rerouting;
stated in every report that uses the indicator.

**Two named parameters**, set in the methodology parameter file and stated in every report:

| Parameter | Default | Notes |
|---|---|---|
| `exit_set` | Freeway mainline plus county boundary | What counts as "evacuated" |
| `headroom_share` | Pro-rata to existing contribution | How a shared bottleneck's remaining room divides among the tracts that depend on it |

`headroom_share` is the one genuine judgement call in the indicator, so it is surfaced rather
than buried. Three defensible rules: pro-rata to existing contribution (status-quo-weighted,
stable), equal per dependent tract (favours dispersal), and solo — each tract sees the full
remaining headroom, which is only honest as an upper bound. **The scored value uses pro-rata; the
solo upper bound is published beside it.** For most of the region the two will be close; on the
peninsula they diverge sharply, and that divergence is itself the finding.

**Inputs.**

| Input | Source | Notes |
|---|---|---|
| Road network | OpenStreetMap via `osmnx`, San Diego County | Pinned by extract date |
| Lane count | OSM `lanes`, then `lanes:forward`/`lanes:backward` | Fallback hierarchy below |
| Street width | OSM `width` ÷ 3.3 m where `lanes` absent | Second choice |
| Direction | OSM `oneway` | Outbound direction only |
| Functional class | OSM `highway` | Last-resort lane default |
| Per-lane capacity | FHWA HPMS Field Manual, Appendix N | 1,900 pc/h/ln base saturation flow |
| Evacuation adjustments | NRC NUREG/CR-7002 Rev. 1 | Method and adjustment factors |
| Vehicles per household | **ACS Table B25044**, Tenure by Vehicles Available | Measured per tract, never assumed |
| Tract boundaries | TIGER/Line 2020 tracts | Already ingested |

**Vehicles per household is measured, and that matters.** A dense lower-income tract may average
0.9 vehicles per household where an affluent exurban tract averages 2.4 — nearly three times the
evacuation demand per home. Assuming a regional average would erase that and bias the measure
against dense urban tracts, precisely the direction that would cause an AFFH problem.

**Lane-count fallback hierarchy**, with every report stating what share of scored links used
each tier — OSM tagging is good on arterials and thin on residential streets, so this is not a
footnote:

1. `lanes` tag present → use it
2. `width` present → `round(width ÷ 3.3 m)`, minimum 1
3. Class default by `highway`: motorway 3, trunk 2, primary 2, secondary 2, tertiary 1,
   residential 1, unclassified 1

**The auditable output is a bottleneck ledger.** Every identified bottleneck link, its capacity,
its assigned load, and the contributing tracts with their shares — one row per
(bottleneck, tract) pair, published as CSV. A traffic engineer can audit it link by link, and a
resident can find their own street's role in it.

**Calibration.** Modeled link volumes compared against published Caltrans and SANDAG traffic
counts, station by station, residuals printed. Tracts with no nearby station are labelled
uncalibrated rather than silently carrying a default.

**Known simplifications, stated in every report.**

* Static all-hazard network. No scenario-specific route closures — a fire-scenario variant is a
  useful *diagnostic* but scenario choice is a modelling degree of freedom the scored indicator
  deliberately refuses, the same discipline as the pinned CoSMoS scenario.
* All-or-nothing assignment ignores congestion rerouting (see above).
* Saturation of a bottleneck is measured against its free-flow capacity; region-wide simultaneous
  evacuation would congest shared corridors beyond what any static measure captures.

**What this buys.** Coronado reads correctly: every tract's binding bottleneck is the bridge or
the Silver Strand, its headroom is a divided share of the room remaining there, and
`units_addable` is small for a stated physical reason anyone can trace on a map. Santee reads
correctly: demand spreads across routes to SR-52, SR-67 and SR-125, no single binding cut, large
headroom. And the indicator is **actionable**, which stock measures never are: a jurisdiction
that adds egress capacity moves its own number.

**AFFH caution.** If dense urban tracts route through saturated urban interchanges they could
score poorly merely for being dense — the failure mode survives the reformulation and must be
measured in Phase 3 before this indicator carries weight. The prior is that it favours grids
over foothills, but that is a prior, not a result.

---

### 3.2 Sewer — `sewer_units_accommodatable`

**Domain:** Infrastructure. **Statutory hook:** §65584.04(e), "lack of capacity for sewer or
water service due to federal or state laws, regulations or regulatory actions, or supply and
distribution decisions."

Note the clause is narrow: **state or federal** action. A locally chosen limit does not count.

**Objective measure.**

```
sewer_units_accommodatable = (permitted_capacity_mgd − current_average_flow_mgd) × 1e6
                             ÷ per_unit_wastewater_gpd
```

Remaining permitted treatment capacity, expressed in dwelling units. Marginal, continuous, and
federally sourced.

**Inputs.**

| Input | Source | Notes |
|---|---|---|
| Permitted flow | EPA ECHO, NPDES permit limits | Per treatment works |
| Actual average flow | EPA ECHO, Discharge Monitoring Reports | Rolling average, period stated |
| Per-unit wastewater generation | Sewer district design standards or UWMP | **Must cite; no rule of thumb** |
| Service area → tract | SanGIS sewer service districts, if published | See gap below |

**Two weaker proxies, and what they are for.**

*SWRCB / Regional Board enforcement orders* — Cease and Desist and Time Schedule Orders imposing
connection restrictions, via CIWQS. These are the literal statutory case but they are rare and
binary. Used as a hard override where present, not as the continuous measure.

*Sanitary sewer overflow reporting* — CIWQS publishes SSOs by collection agency. Chronic overflow
is **evidence of strain, not a state-imposed restriction**. Corroboration only. It must never be
the factor, because using it as one would convert an operational record into a constraint the
statute does not recognise.

**Known gap — flag before building on this.** Plant capacity is public; **sewer service area
boundaries are the question.** If SanGIS does not publish them, this degrades to agency level and
loses tract resolution, at which point it should be reported and excluded from scoring rather
than smeared across tracts.

---

### 3.3 Water — `water_units_accommodatable`

**Domain:** Infrastructure. **Statutory hook:** same clause as sewer.

**Objective measure.**

```
water_units_accommodatable = supply_headroom_acre_feet_per_year ÷ per_unit_demand_af_per_year
```

**Inputs.**

| Input | Source | Statutory fit |
|---|---|---|
| Supply reliability, normal/dry/multi-dry year | Urban Water Management Plans via DWR WUEdata | Strong — required state filing |
| State Water Project Table A allocations | DWR | **Exact** — a state supply decision |
| Colorado River shortage declarations | US Bureau of Reclamation | **Exact** — a federal supply decision |
| SB 610/221 Water Supply Assessments | Local, filed under state law | Project-specific; corroboration |
| Per-unit demand | UWMP demand factors | **Must cite** |

**Expect this indicator to do very little, and plan for that.** The County Water Authority has
spent two decades diversifying supply — desalination, IID transfers, canal lining — specifically
so it can report sufficiency. If every supplier reports adequate supply, the indicator is
near-uniform across tracts and redistributes nothing.

That is a legitimate finding, not a failure, and it should be reported as one. **The methodology's
structure must not assume this indicator lands.**

---

### 3.4 Protected land — `share_land_unprotected`

**Domain:** Land. **Statutory hook:** §65584.04(e), lands protected under federal or state
programs; availability of land suitable for urban development.

**Objective measure.** Complement of the share of tract land under a permanent conservation
instrument:

```
share_land_unprotected = 1 − (protected_area ÷ tract_land_area)
```

Protection means a federal, state, or private conservation instrument — a permanent easement or
public open-space dedication. **A local open-space zoning designation is not protection** for
this purpose; that would be prohibited zoning reasoning.

**Inputs:** California Protected Areas Database (CPAD) and California Conservation Easement
Database (CCED), GreenInfo Network. Tract land area from TIGER `ALAND`.

---

### 3.5 Floodway — `share_outside_floodway`

**Domain:** Land. **Statutory hook:** §65584.04(e), land suitable for urban development.

**Objective measure.**

```
share_outside_floodway = 1 − (residential_land_in_floodway ÷ residential_land_area)
```

**The regulatory floodway, not the 100-year floodplain.** The distinction is deliberate and
material: the floodplain is buildable with mitigation and is where a great deal of California
housing already sits, while the floodway is where construction is prohibited. Using the
floodplain would exclude far more land than the statute contemplates and would read as
constraint-shopping.

**Input:** FEMA National Flood Hazard Layer, zone designation `FLOODWAY`.

---

### 3.6 Wildfire — `share_outside_vhfhsz`

**Domain:** Hazard. **Statutory hook:** §65584.04(e), wildfire risk.

**Objective measure.**

```
share_outside_vhfhsz = 1 − (residential_land_in_VHFHSZ ÷ residential_land_area)
```

**Hazard is the one family where stock and marginal converge**, and it is worth saying why. For
the other indicators, existing conditions and marginal impact differ. Here, because units are
allocated *to tracts*, a tract that is 80% Very High Fire Hazard Severity Zone gives an added
unit roughly an 80% chance of landing in it. The share *is* the marginal exposure.

**Input:** CAL FIRE Office of the State Fire Marshal, Fire Hazard Severity Zones — State
Responsibility Area **effective 1 April 2024** and Local Responsibility Area **as recommended
24 March 2025**.

**Do not use the statewide GIS Fire_Severity_Zones service.** It still serves 2007 SRA and 2011
LRA zones. Anything built on it would be silently eighteen years stale. Confirmed 2026-08-27.

**Mitigation is an open question.** A unit built to current WUI standards — Chapter 7A materials,
defensible space — is not the risk the surrounding older stock is. Whether the safety axis
reports raw exposure, mitigation-adjusted exposure, or both is unresolved; the recommendation is
both, raw as the headline. See `docs/status.md`.

---

### 3.7 Sea level rise — `share_outside_slr_inundation`

**Domain:** Hazard. **Statutory hook:** §65584.04(e), sea level rise.

**Objective measure.**

```
share_outside_slr_inundation = 1 − (residential_land_in_inundation ÷ residential_land_area)
```

**Input:** USGS Coastal Storm Modeling System (CoSMoS).

**The scenario is a parameter, not a constant.** CoSMoS publishes multiple sea level rise and
storm scenarios. Which one is pinned is a policy choice that changes the result, so it lives in
the methodology parameter file and every report states which scenario produced its numbers.

---

### 3.8 Power — `circuit_headroom` · **diagnostic only, not scored**

**Domain:** none. **Statutory hook:** none.

§65584.04(e) names sewer and water. **It does not name electrical capacity.** There is a
catch-all for "other factors furthering stated objectives," but a methodology that moves a
jurisdiction's units on electrical grounds invites the question "under which subdivision?" and
there is no clean answer.

**Recommendation: carry it as a diagnostic, never as an allocation factor.** Report it, map it,
let it inform siting conversations and infrastructure programming. Do not weight it. If the chair
wants it weighted, that is a question for the informal HCD conversation before anything is
public.

**Inputs, which do exist:** CPUC requires investor-owned utilities to publish Integration
Capacity Analysis maps by circuit, and SDG&E files annual Grid Needs Assessment and Distribution
Deferral Opportunity reports identifying load-constrained circuits. Both are public. Caveat: ICA
is built for distributed energy interconnection rather than load growth, so it is an awkward fit
technically as well as legally.

---

## 4. Summary

| Indicator | Domain | Scored | Marginal | Source | Status |
|---|---|:--:|:--:|---|---|
| `evacuation_units_accommodatable` | Evacuation | yes | yes | OSM + ACS B25044 + NUREG/CR-7002 + FHWA | Phase 4 |
| `sewer_units_accommodatable` | Infrastructure | yes | yes | EPA ECHO + CIWQS | Phase 2, service areas at risk |
| `water_units_accommodatable` | Infrastructure | yes | yes | DWR UWMP + SWP/Reclamation | Phase 2, expect near-null |
| `share_land_unprotected` | Land | yes | n/a | CPAD / CCED | Phase 2 |
| `share_outside_floodway` | Land | yes | n/a | FEMA NFHL | Phase 2 |
| `share_outside_vhfhsz` | Hazard | yes | converges | CAL FIRE OSFM 2024/2025 | Phase 2 |
| `share_outside_slr_inundation` | Hazard | yes | converges | USGS CoSMoS | Phase 2, scenario is a parameter |
| `circuit_headroom` | — | **no** | yes | CPUC ICA / SDG&E GNA | Diagnostic only |

## 5. Open decisions

1. **Wildfire mitigation.** Raw exposure, mitigation-adjusted, or both? Recommendation: both, raw
   as headline. Shapes §3.6.
2. **CoSMoS scenario.** Which sea level rise and storm scenario is pinned for the cycle? Shapes
   §3.7.
3. **Per-unit demand factors.** Wastewater gpd/unit and water af/yr/unit must be sourced from
   UWMPs and district design standards rather than rules of thumb. Blocks §3.2 and §3.3.
4. **Power.** Diagnostic, as recommended here, or weighted? Requires an HCD conversation first.
5. **Sewer service areas.** If SanGIS does not publish district boundaries, does the indicator
   drop out of scoring or fall back to agency level? Recommendation: drop out and say so.
6. **Evacuation exit set.** Freeway mainline plus county boundary is the default; a stricter
   definition (named shelter destinations) changes the routing. Shapes §3.1.
7. **Headroom sharing rule.** Pro-rata scored with the solo bound published alongside is the
   recommendation; equal-per-tract is the defensible alternative. Shapes §3.1 and, later, the
   siting bound in the allocator.
