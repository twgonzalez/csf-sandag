"""The evacuation capacity report — Phase 4's verifiable output."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from config import INTERIM, REPORTS
from ingest.network import lane_basis_coverage, load_network
from metrics.evacuation import load_evacuation
from report.tables import write_pair


def build(*, write: bool = True) -> dict:
    """Write ``reports/evacuation_capacity.md``, the bottleneck ledger, and the tract CSV."""
    evac = load_evacuation()
    ledger = pd.read_parquet(INTERIM / "bottleneck_ledger.parquet")
    coverage = lane_basis_coverage(load_network())

    connected = evac[evac["connected"]]
    inhabited = connected[connected["households"] >= 100]

    summary = {
        "tracts": int(len(evac)),
        "connected": int(evac["connected"].sum()),
        "median_clearance_hours": float(inhabited["clearance_hours"].median()),
        "median_units_per_hour": float(inhabited["evacuation_units_per_hour"].median()),
        "lanes_tag_share": float(coverage.get("lanes_tag", 0.0)),
        "class_default_share": float(coverage.get("class_default", 0.0)),
    }
    if not write:
        return summary

    csv_dir = REPORTS / "evacuation"
    csv_dir.mkdir(parents=True, exist_ok=True)
    evac.to_csv(csv_dir / "evacuation_by_tract.csv", index=False)
    ledger.head(500).to_csv(csv_dir / "bottleneck_ledger_top500.csv", index=False)

    worst = (
        inhabited.nsmallest(12, "evacuation_units_per_hour")[
            [
                "tract_geoid",
                "households",
                "vehicles_per_household",
                "bottleneck_name",
                "bottleneck_highway",
                "clearance_hours",
                "evacuation_units_per_hour",
                "delta_clearance_min_per_100_units",
            ]
        ]
        .set_index("tract_geoid")
        .round(2)
    )
    worst_md = write_pair(worst, csv_dir / "most_constrained_tracts.csv", index_label="tract_geoid")

    top = (
        ledger.head(15)[
            [
                "name",
                "highway",
                "lanes_out",
                "lane_basis",
                "capacity_vph",
                "load_vehicles",
                "vc_ratio",
                "n_tracts",
            ]
        ]
        .rename(columns={"vc_ratio": "clearance_hours"})
        .set_index("name")
        .round(2)
    )
    ledger_md = write_pair(top, csv_dir / "top_bottlenecks.csv", index_label="bottleneck")

    quantiles = (
        inhabited[
            ["clearance_hours", "evacuation_units_per_hour", "delta_clearance_min_per_100_units"]
        ]
        .quantile([0.1, 0.25, 0.5, 0.75, 0.9])
        .round(2)
    )
    quantiles.index = [f"p{int(q * 100)}" for q in quantiles.index]
    quantiles_md = write_pair(quantiles, csv_dir / "distribution.csv", index_label="quantile")

    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    body = f"""# Evacuation capacity

*Generated {generated} · Plan Phase 4 · v1: uncalibrated, simultaneous departure*

## What was computed

Every tract's measured vehicle demand (households × vehicles per household, ACS B25044) routed
simultaneously along free-flow shortest paths to the freeway exit set on one county OpenStreetMap
network ({summary["connected"]} of {summary["tracts"]} tracts connected — all of them, after
snapping origins to exit-reachable nodes). Each link's load accumulated; each tract's binding
shared bottleneck identified; the full ledger — every loaded link with capacity, load, and
contributing tracts — in [`bottleneck_ledger_top500.csv`](evacuation/bottleneck_ledger_top500.csv).

**The scored measure is the pro-rata discharge rate**, per the v1 amendment in
[`docs/capacity_indicators.md`](../docs/capacity_indicators.md) §3.1:

```
evacuation_units_per_hour = households ÷ clearance hours at the binding shared bottleneck
```

A tract that takes 9 hours to clear discharges one-ninth of its homes per hour. The originally
specified headroom form degenerates under simultaneous departure (median clearance is
{summary["median_clearance_hours"]:.1f} h, so hourly capacity minus total load is negative nearly
everywhere); the discharge rate keeps the shared-bottleneck attribution and is robust to the
departure-curve assumption. Δ-clearance per 100 added units is published per tract, as specified.

## Distribution (inhabited tracts, ≥100 households)

{quantiles_md}

## Honesty accounting — read before using any number

1. **Uncalibrated.** The separable calibration against Caltrans/SANDAG count stations has not
   yet run. Link capacities are FHWA HPMS Appendix N class defaults; **rankings between tracts
   are the meaningful output, not absolute clearance times.**
2. **Simultaneous departure.** Everyone leaves at once — the most conservative loading.
   NUREG/CR-7002 stages departures over hours, so absolute clearance figures here are upper
   bounds.
3. **All-or-nothing routing.** Each tract's whole demand takes its single shortest path; a grid's
   parallel-street redundancy is invisible, so dense urban tracts read *worse* than reality.
   This inflation runs **against** high-opportunity urban cores — the direction that matters for
   the AFFH caution on this indicator — and is the first thing a v2 capacitated assignment
   should fix.
4. **Lane-tag coverage:** {coverage.get("lanes_tag", 0):.1%} of edges carry a real OSM `lanes`
   tag; {coverage.get("class_default", 0):.1%} rest on class defaults. Defaults dominate
   residential streets; arterials and freeways — where bottlenecks live — are the best-tagged.
5. **Exit set v1** is freeway mainline only; county-boundary exits are not yet included, which
   overstates constraint in the far-east unincorporated communities.
6. **Five tracts snap directly to the freeway mainline** — military installations (Camp
   Pendleton, MCAS Miramar among them) whose restricted internal road networks are absent from
   the public drive graph. Their egress is treated as one three-lane mainline, stated per tract
   in the CSV (`bottleneck_name = "at freeway mainline"`, with `origin_snap_km` recording every
   snap distance). Defensible for bases fronting I-5/I-15; flagged rather than hidden.

## The most constrained inhabited tracts

{worst_md}

## The region's most stressed links

`clearance_hours` here is the link's total assigned load over its hourly capacity.

{ledger_md}

Every number is recomputable from
[`evacuation_by_tract.csv`](evacuation/evacuation_by_tract.csv) and the ledger.
"""
    (REPORTS / "evacuation_capacity.md").write_text(body)
    summary["report_path"] = str(REPORTS / "evacuation_capacity.md")
    return summary
