# Predictions: the employment-weighted candidate runs

Committed **before** the allocations are computed, per the standing rule (no prediction after
the fact; misses published). Basis: the corrected open jobs count (commit 3b669dd) and each
jurisdiction's jobs share versus housing share — inputs only, no allocation has been run.

The three candidates, all at the 6th-cycle total with the fairness gate enforced:

- **jobs_within_bins** — lower-income homes to High/Highest Resource tracts in proportion to
  corrected jobs; moderate and above-moderate to all tracts in proportion to corrected jobs.
- **composition_jobs** — the composition option priced: lower-income placement identical to
  the resource-only baseline; moderate and above-moderate follow corrected jobs.
- **composition_jobs_capacity** — as composition_jobs, with both masses scaled by the
  capacity score (safety picks among equal-standing tracts).

Input anchors (jobs share ÷ housing share): Coronado 2.79, Poway 1.53, Carlsbad 1.27,
San Diego 1.22, Del Mar 1.06, Solana Beach 1.05, National City 0.99, unincorporated 0.77,
Oceanside 0.53, Imperial Beach 0.24.

## The predictions

1. **Gate.** All three candidates meet the fairness gate at exactly the baseline 0.9946.
   The bins and the 1% floor are unchanged, and the gate share depends only on those.
2. **The Metropolis rises under every jobs-weighted run** (ratio 1.22), recovering part of
   the premium the 2020 transit count gave it: composition total predicted 86,000–93,000,
   between its fairness benchmark (~83,000) and its 2020 figure (~108,000), nearer the
   benchmark.
3. **Fire-Country Suburb rises under jobs weighting** (ratio 1.53; its business park sits in
   High/Highest tracts): jobs_within_bins lands ABOVE its fairness benchmark (~3,400).
   Jobs weighting therefore pushes against the safety correction there; under
   composition_jobs_capacity it lands between the capacity run (~1,900) and the benchmark.
4. **The composition option does NOT meaningfully shrink the Coastal Enclave's headline**
   (ratio 1.05): composition total within ±15% of its fairness benchmark (~1,300). If this
   holds, the idea that the composition structure lowers high-resource coastal headlines is
   true only for job-LIGHT cities — and the region's small high-resource coastal cities are
   not job-light. This would materially weaken the composition option's political appeal.
5. **Corollary to 4:** the staff paper's "roughly double the affordable obligation" framing
   for a coastal archetype under composition will NOT reproduce for the Enclave in this
   implementation (its total does not fall, so its affordable share cannot double).
6. **The Back Country falls under all three** (ratio 0.77), furthest under the composition
   pair: composition total predicted 15,000–19,000 against a ~21,100 benchmark.
7. **Urban Core Suburb is roughly unchanged by composition** (ratio 0.99): within ±10% of
   its benchmark (~1,500).
8. **Coastal City, Fire at its Back rises under composition** (ratio 1.27): above its
   ~9,700 benchmark before capacity weighting, pulled back toward it with capacity.

Misses get published next to hits, as always.
