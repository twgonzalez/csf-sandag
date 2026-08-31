# Fair housing in the 6th-cycle methodology: what SANDAG did, and did not, do

A reference for the question that will come up in any staff discussion: *"Didn't we apply fair
housing in 2019?"* The answer is yes — and the precise form it took is the whole story. Every
quote below is from the adopted documents, which are checksummed in this repository
(`config.SOURCES`), with page references.

## Short answer

**SANDAG did apply the fair-housing objective in 2019, explicitly and in writing.** Its equity
adjustment steered each jurisdiction's *income mix* toward regional balance, and the adopted
methodology reviewed the TCAC Opportunity Map — by name — as evidence that the approach served
fair housing. HCD accepted it without amendment.

**What the 2019 methodology did not do** is use fair-housing geography to determine *how many
homes each jurisdiction receives*. Jurisdiction totals came entirely from transit stations (65%)
and jobs (35%). The opportunity map appears in the methodology as an exhibit supporting the
income-mix adjustment — never as an allocation input.

The one-line version: **fair housing shaped the percentages; stations and jobs shaped the
totals.** Our comparison runs show what changes when fair housing shapes the totals too — which
is the direction state practice moved after 2019.

## The documented record

### 1. The methodology claimed AFFH, and meant it

*6th Cycle RHNA Methodology* (adopted 2019-11-22), p. 11, addressing statutory Objective 5:

> "During development of the methodology, SANDAG reviewed the California Tax Credit Allocation
> Committee (TCAC) 2019 Opportunity Map for the San Diego region… The Equity Adjustment within
> the methodology addresses the disparities in access to resource-rich areas by providing
> housing opportunities for people in all income levels to reside in any given community."

And the empirical claim SANDAG offered as proof (p. 11–12):

> "The six jurisdictions that will receive the highest percentage of low- and very low-income
> housing units under the methodology also do not contain areas of high segregation and poverty
> or low resource census tracts, and compared to other jurisdictions in the region have the
> highest percentage of area in high or highest resource census tracts (76–100% of the
> jurisdiction)."

Note the operative word: **percentage**. The claim is about each city's affordability *mix*, not
its total. The adopted numbers bear it out: Solana Beach's allocation was 36% very-low-income
and Carlsbad's 34%, against 12% for National City and 15% for El Cajon — while those same
coastal cities received among the smallest *totals* in the region, because totals were set by
stations and jobs. A full-page reproduction of the TCAC map appears on p. 12 of the
methodology; it is the map's only role in the document.

### 2. The equity adjustment was the AFFH mechanism

Methodology p. 2, item 4: "To promote equity and fair housing, as well as to meaningfully
address patterns of segregation, the methodology will allocate more housing units within each
income category to jurisdictions with a percentage of households in that same category that is
lower than the regional percentage." The Board's RHNA Subcommittee direction (p. 9) is
explicit: "Include an equity adjustment to ensure the allocation furthered fair housing."

### 3. HCD accepted it — under the standard of that moment

Methodology p. 2: "HCD reviewed the draft methodology and submitted a letter to SANDAG on
November 1, 2019. HCD found that the methodology furthers the five statutory objectives in
Government Code section 65584(d), and did not provide any proposed amendments." The HCD letter
is reproduced in the methodology's appendix.

The timing context: the AFFH objective entered §65584(d) on January 1, 2019 (AB 1771, 2018).
SANDAG's draft went to HCD in September 2019; the letter came in November 2019. HCD's
implementing AFFH guidance was published in **April 2021** — seventeen months later. SANDAG was
reviewed under the newest, least-developed reading of the objective, and met it.

### 4. What changed afterward

In the Bay Area's 2020–21 methodology process, HCD pushed toward opportunity-based *allocation
factors*, and ABAG's adopted methodology uses high-opportunity-area weighting to help set
jurisdiction shares directly. The practice moved from "opportunity map as supporting evidence
for an income-mix adjustment" to "opportunity geography as an input that shapes where homes
go." The 2027 review will apply the matured standard.

### 5. A related choice worth knowing

The methodology's response-to-comments (p. 36) records that SANDAG **calculated jurisdiction
jobs-housing ratios and considered using them**, and that the RHNA Subcommittee and Technical
Working Group chose a methodology without them. The consideration of factors was real; the
adopted factor set was deliberately minimal ("keep the methodology simple and easy to explain,"
p. 8).

## Summary, in spoken form

"The 2019 team did apply fair housing — through the income mix, with the opportunity map cited
as supporting evidence, and the state signed off. What's changed since is that the state now
expects opportunity geography to help decide the totals themselves, not just the percentages.
Our comparison runs measure exactly that difference — which is why they look so different from
2020, and why that difference is a statement about the evolved standard, not about the 2019
work."

## The opportunity map, defined

The **CTCAC/HCD Opportunity Map** is the State of California's official neighborhood-level
index of economic, educational, and environmental conditions, published jointly by the
Treasurer's Tax Credit Allocation Committee and the Department of Housing and Community
Development, updated annually. It classifies every census tract as Highest / High / Moderate /
Low Resource, with a separate High Segregation & Poverty designation. It is the state's own
instrument — this project replicated its published scores exactly (638 of 638 complete tracts)
before relying on it.

Official page, methodology, and downloads: <https://www.treasurer.ca.gov/ctcac/opportunity>

## Sources

| Document | Where cited above | Verification |
|---|---|---|
| SANDAG, *6th Cycle RHNA Methodology* (2019-11-22) | pp. 2, 8–9, 11–12, 36, appendix | SHA-256 pinned in `config.SOURCES`; checked every run |
| SANDAG, *Final 6th Cycle RHNA Plan* (2020-07-10) | adopted allocation (income-mix shares) | same |
| CTCAC/HCD Opportunity Map, 2026 edition | replication in `metrics/opportunity.py` | exact, `reports/opportunity_map.md` |
