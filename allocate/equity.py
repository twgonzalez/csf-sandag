"""The equity adjustment: allocating a lower share to categories a place already has too many of.

Gov. Code Sec. 65584(d)(4) requires the methodology to further "allocating a lower proportion of
housing need to an income category when a jurisdiction already has a disproportionately high
share of households in that income category." SANDAG's 6th-cycle answer was an inverse-ratio
scaling factor, and it is implemented here as its own function so a 7th-cycle parameter file can
keep it, replace it, or turn it off, and the sensitivity report can show what it is worth.
"""

from __future__ import annotations

import pandas as pd


def inverse_ratio_scaling_factor(
    household_shares: pd.DataFrame, regional_shares: pd.Series
) -> pd.DataFrame:
    """SANDAG's 6th-cycle equity scaling factor.

    Rule, quoted from the *6th Cycle RHNA Methodology*, Appendix FAQ #15, p. 27:
        "a jurisdiction's share of households in an income category is compared to the region's
        share of households in the same income category by determining the relative difference
        between the two percentages. The relative difference is found by taking the inverse ratio
        of a jurisdiction's share of households within an income category to the region's share."

        ``= 1 / (Jurisdiction's Percent of Very Low Households / Regional Percent of Very Low
        Households)``

    A factor above 1 pushes units toward that category, which happens when the jurisdiction has
    proportionally fewer such households than the region. A factor below 1 pulls units away.

    Args:
        household_shares: Jurisdiction-indexed matrix of existing-household shares by income
            category. Each row should sum to about 1.0.
        regional_shares: Regional household share for each income category.

    Returns:
        Matrix of scaling factors, same shape as ``household_shares``.

    Raises:
        ValueError: If any jurisdiction has zero households in a category. The rule divides by
            that share, so a zero makes the factor infinite; the caller must decide what a
            jurisdiction with literally no households of a given income means before the
            arithmetic can proceed.
    """
    zeros = household_shares.eq(0)
    if zeros.any().any():
        offenders = [
            f"{row}/{col}"
            for row in household_shares.index
            for col in household_shares.columns
            if zeros.loc[row, col]
        ]
        raise ValueError(
            "the inverse-ratio equity adjustment divides by a jurisdiction's household share, "
            f"which is zero for: {offenders}"
        )
    return regional_shares / household_shares


def equity_seed(household_shares: pd.DataFrame, regional_shares: pd.Series) -> pd.DataFrame:
    """The share of a jurisdiction's units that the equity adjustment sends to each category.

    Rule, from the same FAQ:
        "The relative difference is used as a scaling factor that adjusts the region's percentage
        of households in an income category ... and uses this adjusted percentage as the
        jurisdiction's share of its housing allocation for that income category."

    So the seed value is ``regional_share * scaling_factor``, i.e. ``regional_share ** 2 /
    jurisdiction_share``.

    Note:
        These shares do **not** sum to 1.0 within a jurisdiction, and SANDAG's published Table 5
        does not claim they do -- Carlsbad's four categories sum to 111.9 percent. They are
        relative preferences, not a distribution. Turning them into an allocation requires
        reconciling to both margins; see :mod:`allocate.reconcile`.

    Args:
        household_shares: Jurisdiction-indexed existing-household shares by income category.
        regional_shares: Regional household share for each income category.

    Returns:
        Matrix of relative preferences, same shape as ``household_shares``.
    """
    return inverse_ratio_scaling_factor(household_shares, regional_shares).mul(
        regional_shares, axis=1
    )
