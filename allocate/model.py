"""The tract-scored allocator — milestone D1.2.

One function, :func:`allocate`, takes the tract feature table, the RHND by income category, and a
loaded methodology, and returns tract allocations that sum exactly to the RHND. Jurisdiction
totals are **outputs**, produced by rolling tracts up through the unit-share crosswalk. Nothing
here ever scores a jurisdiction (Hard constraint 2), and nothing about any method is hard-coded
(the parameter file is the methodology).

The seed construction, in order, per income category:

1. Each factor applying to the category contributes ``factor.weight`` times its mass column,
   normalised over the tracts it covers (optionally restricted to named Opportunity Map
   categories).
2. The **floor** blends in a small uniform-by-mass weight across all tracts:
   ``seed' = (1 - floor_weight) * seed + floor_weight * mass_base_share``. The floor is applied
   to the seed, not the result, because zeros in a seed are structural
   (see :mod:`allocate.reconcile`) -- and without it a pure High/Highest rule gives four
   jurisdictions approximately zero lower-income units, violating Hard constraint 4 and Gov.
   Code Sec. 65584(d)(1).
3. The category's RHND multiplies the seed. Zero-sum holds by construction and is asserted
   anyway.

Rounding happens **at the output geography**: tract allocations stay fractional, are rolled up
through the crosswalk, and largest-remainder rounding is applied per category at the
jurisdiction level. Rounding tracts first and then splitting fractional tracts across
jurisdiction boundaries would re-break the integer totals the rounding just fixed.
"""

from __future__ import annotations

import pandas as pd

from allocate.params import Methodology
from allocate.reconcile import round_preserving_totals
from config import PROCESSED
from ingest.crosswalk import load_crosswalk, roll_up_to_jurisdictions
from ingest.opportunity_map import load_opportunity_map


class MethodologyNotRunnable(ValueError):
    """A methodology that loaded fine but cannot be executed by the tract allocator."""


def allocation_feature_table() -> pd.DataFrame:
    """The tract features a D1 parameter file may reference.

    Columns:
        ``tract_geoid``; ``housing_units_2020`` (2020 Census, summed from the block geography
        the crosswalk is built on, so the allocator and the roll-up share one unit count);
        ``opportunity_category`` (CTCAC/HCD 2026, null only for the all-water tract);
        ``capacity_score`` (the Capacity Map composite over the four measured indicators) and
        ``capacity_weighted_units`` = housing units x capacity score, the orthogonal design's
        siting mass.

    Grows as later phases land: each capacity indicator becomes a column here, and parameter
    files reference it by name.
    """
    from metrics.capacity import capacity_feature_table, score_capacity

    crosswalk = load_crosswalk()
    units = (
        crosswalk.groupby("tract_geoid", as_index=False)["housing_units_2020"]
        .sum()
        .sort_values("tract_geoid", ignore_index=True)
    )
    opportunity = load_opportunity_map()[["tract_geoid", "opportunity_category"]]
    out = units.merge(opportunity, on="tract_geoid", how="left", validate="one_to_one")

    capacity = score_capacity(capacity_feature_table())[["tract_geoid", "capacity_score"]]
    out = out.merge(capacity, on="tract_geoid", how="left", validate="one_to_one")
    # The orthogonal design's siting mass: existing housing units scaled by the Capacity Map
    # score (1..n+1, the state's own at-or-above-median counting rule applied to the four
    # measured capacity indicators). Within a resource bin, a tract with twice the capacity
    # score carries twice the weight per existing unit -- capacity decides siting, never bins.
    out["capacity_weighted_units"] = out["housing_units_2020"] * out["capacity_score"].fillna(1)
    return out


def _category_seed(features: pd.DataFrame, methodology: Methodology, category: str) -> pd.Series:
    """Build one income category's seed from the factors that apply to it."""
    applicable = [
        f for f in methodology.factors if f.applies_to is None or category in f.applies_to
    ]
    if not applicable:
        raise MethodologyNotRunnable(
            f"{methodology.name}: no factor applies to income category '{category}'"
        )
    total_weight = sum(f.weight for f in applicable)
    if abs(total_weight - 1.0) > 1e-9:
        raise MethodologyNotRunnable(
            f"{methodology.name}: factor weights for '{category}' sum to {total_weight}, not 1.0"
        )

    seed = pd.Series(0.0, index=features.index)
    for factor in applicable:
        if not factor.column:
            raise MethodologyNotRunnable(
                f"{methodology.name}: factor '{factor.name}' declares no feature column"
            )
        if factor.column not in features.columns:
            raise MethodologyNotRunnable(
                f"{methodology.name}: factor '{factor.name}' reads column '{factor.column}', "
                "which is not in the feature table"
            )
        mass = features[factor.column].astype("float64").fillna(0.0)
        if factor.restrict_to_categories is not None:
            mass = mass.where(
                features["opportunity_category"].isin(factor.restrict_to_categories), 0.0
            )
        mass_total = float(mass.sum())
        if mass_total <= 0:
            raise MethodologyNotRunnable(
                f"{methodology.name}: factor '{factor.name}' has zero total mass for "
                f"'{category}' -- its column or category restriction selects nothing"
            )
        seed = seed + factor.weight * (mass / mass_total)
    return seed


def allocate(
    methodology: Methodology,
    rhnd: dict[str, int],
    *,
    features: pd.DataFrame | None = None,
    write: bool = True,
) -> pd.DataFrame:
    """Run a tract-scored methodology against a regional determination.

    Args:
        methodology: A loaded, guardrail-screened methodology. Replication-only files are
            refused: they exist to be validated against, not to allocate.
        rhnd: Units per income category. The regional total is an input, never an output
            (Hard constraint 1).
        features: Tract feature table; built via :func:`allocation_feature_table` if omitted.
        write: Persist the tract allocation to ``data/processed/``.

    Returns:
        One row per tract: ``tract_geoid``, one fractional column per income category, and
        ``total``. Column sums equal ``rhnd`` exactly (asserted).

    Raises:
        MethodologyNotRunnable: Replication-only file, missing column, bad weights, or a factor
            selecting no mass.
    """
    if methodology.replication_only:
        raise MethodologyNotRunnable(
            f"{methodology.name} is replication_only: it validates the pipeline against the "
            "adopted 6th cycle and is barred from proposing an allocation."
        )
    if methodology.geography != "tract":
        raise MethodologyNotRunnable(
            f"{methodology.name} declares geography '{methodology.geography}'; the allocator "
            "scores tracts only (Hard constraint 2)."
        )

    if features is None:
        features = allocation_feature_table()

    floor_weight = float(methodology.parameters.get("floor_weight", 0.0))
    if not 0.0 <= floor_weight < 1.0:
        raise MethodologyNotRunnable(f"floor_weight must be in [0, 1); got {floor_weight}")
    mass_base = str(methodology.parameters.get("mass_base", "housing_units_2020"))
    if mass_base not in features.columns:
        raise MethodologyNotRunnable(f"mass_base column '{mass_base}' not in the feature table")
    base = features[mass_base].astype("float64").fillna(0.0)
    base_share = base / float(base.sum())

    out = features[["tract_geoid"]].copy()
    for category, units in rhnd.items():
        seed = _category_seed(features, methodology, category)
        seed = (1.0 - floor_weight) * seed + floor_weight * base_share
        allocated = float(units) * seed
        drift = abs(float(allocated.sum()) - float(units))
        if drift > max(1e-6, units * 1e-12):
            raise AssertionError(
                f"zero-sum violated for '{category}': allocated {allocated.sum():,.6f} "
                f"of {units:,} (Hard constraint 1)"
            )
        out[category] = allocated

    out["total"] = out[list(rhnd)].sum(axis=1)
    if write:
        out.to_parquet(PROCESSED / f"allocation_{methodology.name}_tracts.parquet", index=False)
    return out


def to_jurisdictions(tract_allocation: pd.DataFrame, rhnd: dict[str, int]) -> pd.DataFrame:
    """Roll a tract allocation up to jurisdictions and round to whole units.

    Largest-remainder rounding per category, at the jurisdiction level, so each category column
    sums exactly to its RHND (Hard constraint 1) after rounding.

    Raises:
        AssertionError: If any jurisdiction receives zero in any category (Hard constraint 4 and
            Gov. Code Sec. 65584(d)(1)) -- the methodology's floor is too low and must be raised
            in its parameter file, not patched here.
    """
    categories = [c for c in rhnd]
    rolled = roll_up_to_jurisdictions(
        tract_allocation[["tract_geoid", *categories]], categories
    ).set_index("jurisdiction")

    targets = pd.Series({c: int(rhnd[c]) for c in categories})
    integral = round_preserving_totals(rolled[categories], targets)

    zeros = [
        (jurisdiction, category)
        for jurisdiction in integral.index
        for category in categories
        if integral.loc[jurisdiction, category] <= 0
    ]
    if zeros:
        raise AssertionError(
            f"jurisdictions with a zero allocation (Hard constraint 4): {zeros}. "
            "Raise floor_weight in the methodology's parameter file."
        )

    integral["total"] = integral[categories].sum(axis=1)
    return integral


def affh_share(
    tract_allocation: pd.DataFrame, *, lower_income: tuple[str, ...] = ("very_low", "low")
) -> float:
    """Share of lower-income units landing in High or Highest Resource tracts.

    This is the operational AFFH test (Gov. Code Sec. 65584(d)(5)): computed for the
    resource-only baseline it becomes the gate constant every candidate methodology must meet or
    beat. Only computable for tract-scored allocations -- the adopted 6th cycle allocated to
    jurisdictions and cannot be measured this way, which is itself worth noticing.
    """
    opportunity = load_opportunity_map()[["tract_geoid", "opportunity_category"]]
    joined = tract_allocation.merge(opportunity, on="tract_geoid", how="left")
    lower = joined[list(lower_income)].sum(axis=1)
    in_target = joined["opportunity_category"].isin(["High Resource", "Highest Resource"])
    return float(lower[in_target].sum() / lower.sum())


class AffhGateViolation(ValueError):
    """A candidate methodology fell below the resource-only baseline's AFFH share."""


def enforce_affh_gate(candidate_share: float, baseline_share: float, name: str) -> None:
    """Refuse any allocation whose lower-income High/Highest share falls below the baseline.

    The gate from plan.md Phase 1, as machinery: the pipeline is structurally incapable of
    emitting an AFFH-regressive methodology. Tolerance covers float noise only.
    """
    if candidate_share < baseline_share - 1e-9:
        raise AffhGateViolation(
            f"methodology '{name}' places {candidate_share:.4f} of lower-income units in "
            f"High/Highest Resource tracts, below the resource-only baseline of "
            f"{baseline_share:.4f}. The AFFH gate (Gov. Code 65584(d)(5); plan.md Phase 1) "
            "refuses this allocation."
        )
