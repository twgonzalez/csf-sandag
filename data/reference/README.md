# Reference tables

Tables transcribed from cited public PDFs, committed to the repository because the PDF is not
machine-readable and PDF text extraction is not stable enough to satisfy Hard constraint 7
(byte-identical outputs).

Each file records its source document, table number, and page. `ingest/sandag_methodology_6th.py`
verifies the source PDF's SHA-256 against the value pinned in `config.SOURCES` on every run, so a
reader can confirm these numbers came from the document they think they came from, and any
reissue of that PDF fails the run loudly.

| File | Source |
|---|---|
| `sixth_cycle_transit.csv` | SANDAG, *6th Cycle RHNA Methodology* (Final, 2019-11-22), Table 1: Transit Data, p. 4 |
| `sixth_cycle_jobs.csv` | SANDAG, *6th Cycle RHNA Methodology* (Final, 2019-11-22), Table 2: Jobs Data, p. 5 |
| `sixth_cycle_households.csv` | SANDAG, *6th Cycle RHNA Methodology* (Final, 2019-11-22), Table 4: Households per Income Category, p. 7 |
| `jurisdictions.csv` | Canonical jurisdiction keys, names, and Census place GEOIDs |

## A note on what is and is not open here

Tables 1 and 2 are *published outputs of proprietary models* — the SANDAG Activity Based Model and
the SANDAG Employment Estimates. The jurisdiction-level totals are public; the models that
produced them are not. Transcribing the published totals lets this pipeline replicate the adopted
6th-cycle allocation exactly, which is the validation milestone. It does **not** make those inputs
reproducible, and no 7th-cycle methodology in `params/` may depend on them. That is the whole
point of the exercise: see `docs/status.md`, "Non-reproducible 6th-cycle inputs".
