# SANDAG 7th-Cycle RHNA — Open-Data Allocation Pipeline

A fully reproducible pipeline that allocates a fixed regional housing need (the HCD Regional
Housing Needs Determination, "RHND") across the 19 jurisdictions of the SANDAG region using
**only publicly available data**.

Every input is downloaded by script from a cited public URL. Every adjustment is a named function
whose docstring states the rule and its source. Every run produces a report that reconciles to the
regional total. If you disagree with an allocation, change one parameter in a methodology file,
rerun, and see exactly what moves.

## Why this exists

SANDAG's 6th-cycle RHNA methodology relies on two inputs that cannot be independently verified:

| Component | 6th-cycle source | Public? |
|---|---|---|
| Transit (65% of units) | SANDAG Activity Based Model, Release v14.0.1, Reference Scenarios #242/#243 | No — model output; only the resulting station counts were published |
| Jobs (35% of units) | SANDAG Employment Estimates (QCEW + LODES + SDMAC/DMDC blend) | No — the blend is internal; only jurisdiction totals were published |
| Equity adjustment | ACS 2012–2016 5-Year, Table B19001 | Yes |

A methodology that cannot be recomputed cannot be meaningfully appealed under Gov. Code
§65584.05, and cannot be audited by HCD under §65584.04(i). This repository demonstrates that a
compliant allocation can be built entirely from open sources, and provides a testbed for
evaluating candidate 7th-cycle methodologies.

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) and an internet connection. Nothing else.

```bash
uv sync --extra dev      # creates .venv, installs pinned versions
make validate            # 6th-cycle replication; fails if error exceeds threshold
make all                 # full pipeline from empty cache to reports
```

### Optional: a Census API key

Everything above works with no credentials. A [free Census Data API
key](https://api.census.gov/data/key_signup.html) cuts the first-run download from **874 MB to
37 MB** by fetching ACS tables and 2020 block housing counts county-scoped instead of pulling
national and statewide bulk files:

```bash
cp .env.example .env     # then paste your key into it; .env is gitignored
```

The key is a speed-up, never a correctness dependency. `tests/test_census_api.py` runs both paths
over real data and fails if a single cell disagrees — so a reviewer without a key gets byte-identical
results, just more slowly. That property is the point: an HCD audit under §65584.04(i) or a
jurisdiction's appeal under §65584.05 must not require credentials.

## Hard constraints

These are enforced in code and asserted in tests. They are not style preferences.

1. **Zero-sum.** The regional total is an input. Every run sums exactly to the RHND by income
   category. Capacity and constraint factors redistribute units; they never reduce the total.
2. **Tract is the computation geography; jurisdiction is the output geography.** All scoring
   happens at the 2020-vintage census tract. Jurisdictions are never scored directly.
3. **Six income categories** for the 7th cycle: acutely low, extremely low, very low, low,
   moderate, above moderate. Acutely low and extremely low are held within 3% of proportionality
   to very low, per §65584(d)(1).
4. **Every jurisdiction receives a nonzero allocation in every income category.** §65584(d)(1).
5. **Prohibited factors are refused.** Local ordinances, growth caps, zoning limits, "stable
   population," and prior underproduction are never inputs. §65584.04(e)(2)(B). A parameter file
   that names one is rejected at load time and the refusal is written to the run log.
6. **No proprietary or licensed data, ever.** Where a needed input is license-only, the gap is
   documented and the best public proxy is used in its place.
7. **Deterministic.** Data vintages and library versions are pinned; the same inputs and
   parameters produce byte-identical outputs.

## Layout

```
config.py         Pinned vintages, URLs, region constants. One place to change a data vintage.
cache.py          Download-once-with-checksum. Raw bytes are never modified after fetch.
ingest/           One module per public source -> tidy parquet. No allocation logic.
metrics/          Pure functions from ingest outputs -> one tract-level feature table.
allocate/         One allocation function. Parameter files are the methodology.
report/           Markdown + CSV reports. Every number carries a source.
params/           Methodology parameter files. Nothing about a method is hard-coded.
data/reference/   Tables transcribed from cited public PDFs, with checksum verification.
tests/            Unit tests per adjustment + integration tests for the hard constraints.
scratch/          Exploration. Gitignored. Never in main.
```

## Status

See [docs/status.md](docs/status.md) for what is built, what is stubbed, and what is blocked.

## Sources

Every source URL, vintage, and access date is recorded in [config.py](config.py) and reproduced in
the generated methodology appendix (`reports/methodology_appendix.md`).
