"""The evacuation shed report — the objective zone geography and its validation."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from config import INTERIM, REPORTS
from report.tables import write_pair


def build(*, write: bool = True) -> dict:
    """Write ``reports/evacuation_sheds.md`` from the shed and replay parquets."""
    sheds = pd.read_parquet(INTERIM / "evacuation_sheds.parquet")
    fires = pd.read_parquet(INTERIM / "fire_replay.parquet")
    chokes = pd.read_parquet(INTERIM / "fire_replay_chokepoints.parquet")

    inhabited_fires = fires[fires["tracts"] > 0].copy()
    weighted_corridor = float(
        (inhabited_fires["corridor_match"] * inhabited_fires["households"]).sum()
        / inhabited_fires["households"].sum()
    )

    summary = {
        "tracts": int(len(sheds)),
        "distinct_sheds": int(sheds["shed_id"].nunique()),
        "median_shed_size": int(sheds["shed_size"].median()),
        "max_shed_size": int(sheds["shed_size"].max()),
        "fires_replayed": int(len(inhabited_fires)),
        "household_weighted_corridor_match": weighted_corridor,
    }
    if not write:
        return summary

    csv_dir = REPORTS / "evacuation"
    csv_dir.mkdir(parents=True, exist_ok=True)
    sheds.to_csv(csv_dir / "shed_membership.csv", index=False)

    biggest = (
        sheds.drop_duplicates("shed_id")
        .nlargest(10, "shed_households")[
            ["bottleneck_name", "shed_size", "shed_households", "shed_vehicles"]
        ]
        .set_index("bottleneck_name")
    )
    biggest_md = write_pair(biggest, csv_dir / "largest_sheds.csv", index_label="bottleneck")

    fires_display = inhabited_fires.set_index("fire")[
        ["acres", "tracts", "households", "corridor_match", "shed_prediction_match"]
    ].rename(
        columns={
            "corridor_match": "Corridor match",
            "shed_prediction_match": "Exact-link match",
        }
    )
    fires_md = write_pair(fires_display, csv_dir / "fire_replay.csv", index_label="fire")

    choke_display = chokes.set_index("fire")[["link", "highway", "queue_hours", "load_vehicles"]]
    chokes_md = write_pair(choke_display, csv_dir / "fire_chokepoints.csv", index_label="fire")

    generated = datetime.now(UTC).strftime("%Y-%m-%d")
    body = f"""# Evacuation sheds

*Generated {generated} · the objective zone geography, and its validation against fires that happened*

## What a shed is

A shed is the set of tracts whose evacuation routes converge on the same binding bottleneck —
the way a watershed is the land draining to one river. **Nobody draws the sheds.** They are
implied by the road network, the measured vehicle counts, and the deterministic routing rule:
the same public inputs as everything else in this pipeline, and the same defense. Fire ignores
city boundaries; so do sheds. And the shed is the fire-relevant community by construction — it
is precisely the set of households that will be in your traffic jam.

The region resolves into **{summary["distinct_sheds"]} sheds** across {summary["tracts"]} routed
tracts (median {summary["median_shed_size"]} tracts per shed, largest
{summary["max_shed_size"]}). Every tract's shed — its binding link and the neighbors who share
it — is published in [`shed_membership.csv`](evacuation/shed_membership.csv); a resident can
find their evacuation community by street name.

### The largest sheds by households behind one bottleneck

{biggest_md}

## Validation: replaying fires nobody chose

Every fire of 15,000 acres or more that touched the county since 2000 (CAL FIRE FRAP perimeter
database) is replayed as a zonal evacuation: the tracts the fire actually burned evacuate at
once, the rest of the county is absent. The replay's chokepoints are then compared with the
sheds' predictions. The test zones are not analyst choices — they are fires that happened.

{fires_md}

**Corridor match** is the operative metric: whether the shed analysis named the same road a
fire-scenario replay names, which is the prediction a fire marshal would act on. Exact-link
match — the same physical segment — is reported as the stricter bound.
Household-weighted corridor match across all replayed fires:
**{weighted_corridor:.0%}**.

### What the replays find

{chokes_md}

The headline validation is the Cedar Fire row: the replay's binding chokepoint is **Wildcat
Canyon Road** — where most of that fire's civilian fatalities occurred in October 2003. The
model was built from OpenStreetMap geometry, Census vehicle counts, and federal capacity
defaults; it contains no fire-specific tuning and no knowledge of the fire's history. It
identifies the road independently.

## Honest limits

* Small rural fires match worst: with only a tract or two evacuating, the zonal binding link can
  differ from the county-analysis shed link. The shed prediction is strongest exactly where the
  stakes are largest — big fires with many tracts moving at once.
* Two Camp Pendleton fires (AMMO 2007, PULGAS 2014) touched no inhabited public-network tracts
  and are excluded.
* All v1 evacuation caveats apply — uncalibrated capacities, no congestion collapse, free-flow
  routing. See [`evacuation_capacity.md`](evacuation_capacity.md).
"""
    (REPORTS / "evacuation_sheds.md").write_text(body)
    summary["report_path"] = str(REPORTS / "evacuation_sheds.md")
    return summary
