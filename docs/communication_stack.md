# The communication stack — design brief

How the analysis reaches SANDAG board members and staff. Three artifacts, one system. This brief
is the spec; artifacts get built against it.

## Shared principles

1. **Layered by audience behavior, not by topic.** Board members skim and listen; staff read and
   probe; analysts recompute. Each layer serves one behavior and points down a level.
2. **One idea per view.** A frame, page, or screen makes exactly one point, carried by a visual
   where possible. Density lives in the reference layer (the staff paper and the repo).
3. **Plain, memo-register language** (per the standing rule). No invented vocabulary; the
   "opportunity map" gets defined once with the state link.
4. **No artifact computes anything.** Every number is precomputed by the pipeline and traceable
   to a committed report. The explorer *displays* a precomputed sweep; it never runs a model in
   the browser. Single source of truth, same as the dashboard rule.
5. **Anonymized archetypes throughout** — the same six, same rounded figures, so the artifacts
   corroborate each other.
6. **Same visual identity** as the journal (palette, Archivo/Public Sans/Plex Mono), so the
   stack reads as one body of work.
7. **"Questions worth asking us" is a first-class element** in every layer. The goal is better
   questions, not finished arguments; we seed them explicitly.

## Layer 1 — the one-pager (leave-behind)

- **Job:** the only artifact most board members will absorb. 60-second read. Must survive
  black-and-white photocopying.
- **Content budget (hard):** 3-sentence background · **three** findings, 2–3 sentences each ·
  one micro-visual (three archetypes' movement, 2020 → range) · four decisions with dates · four
  "questions worth asking us" · one pointer line to the deeper layers.
- **The three findings that survive compression:**
  1. The last plan's math could not be checked; we rebuilt it so it can be — and the only error
     ever found needed a formal appeal that an open system would catch automatically.
  2. Fair housing moved from the percentages to the totals: 2019 applied it to each city's
     income mix (the state approved); the state now expects it to shape how many. Coastal
     high-opportunity cities rise under any lawful formula.
  3. Safety data works as placement, proven against real fires (Wildcat Canyon) — it moves
     ~7,300 homes to safer ground at an identical fair-housing score, and it cannot lawfully
     lower a city's total (measured, not asserted).
- **Format:** single self-contained HTML, strict print stylesheet targeting one US-Letter page.

## Layer 2 — the walkthrough (presented, ~10 minutes)

- **Job:** what [name withheld] presents. Question-titled frames; one visual and one sentence of answer
  per frame; presenter notes under each.
- **Frame list (draft):**
  1. Why we did this (the 45-day appeal problem)
  2. "Didn't we already do fair housing in 2019?" (percentages → totals, credit the 2019 team)
  3. "Why do coastal numbers go up?" (the movement picture)
  4. "Can fire risk lower a city's number?" (the 3.3× overlap, one map-style graphic)
  5. "Then what is safety data for?" (placement; the 7,300-home shift at identical fair housing)
  6. "How do we know the evacuation model is any good?" (Wildcat Canyon)
  7. "What did it get wrong?" (the coastal-funnel miss — credibility through candor)
  8. "What about smaller totals with more affordable?" (the option and its catch)
  9. "What has to be decided, and when?" (the four decisions on the statutory clock)
  10. "Questions worth asking us" (closing frame)
- **Format:** self-contained HTML slides (arrow keys / swipe), printable as a handout list.

## Layer 3 — the explorer (the differentiator)

- **Job:** let an executive move a dial and *watch* the consequences; teach the
  placement-not-reduction design through play; generate questions. Thirty seconds of
  interaction should convey what pages of prose cannot.
- **Interaction model, v1 — deliberately one dial:** "How much weight does safety get?"
  (0% = fair-housing benchmark, 100% = full capacity weighting). One dial teaches one lesson;
  more controls dilute it. As the dial moves:
  - the six archetype bars animate between allocations;
  - a **"homes in severe fire zones" counter falls** — the dial visibly buys something;
  - the **fair-housing gauge does not move** (pinned at 99.5%). The gate as interface: the
    user's attempt to find a setting that trades fairness away fails visibly. That refusal is
    the design's central message, delivered as an interaction instead of a paragraph.
- **Data contract:** a small pipeline job sweeps the safety weight at 11 positions and emits one
  JSON blob (per position: archetype totals, affordable subtotals, fire-zone exposure,
  fair-housing share). The blob is committed, checksummed, embedded in the page. The page
  interpolates for display only.
- **v2 candidates (explicitly out of scope for v1):** a 7th-cycle-total slider (everything
  scales); the composition option as a toggle; a private, real-city mode for staff.
- **Format:** single self-contained HTML; publishable as a private artifact and committed to the
  journal like everything else.

## Build order and status

| Layer | Status | Estimate |
|---|---|---|
| Design brief (this document) | done | — |
| One-pager | done — journal 2026-08-31 | — |
| Walkthrough | done — journal 2026-08-31 | — |
| Explorer v1 (sweep job + page) | next | one session |
| Staff paper | done — becomes the reference layer | — |
