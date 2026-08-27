"""Biproportional reconciliation of an allocation matrix to fixed row and column totals.

Hard constraint 1 says the regional total is an input and every run must sum exactly to the RHND
by income category. An allocation therefore has two sets of fixed margins at once:

* **row totals** -- how many units each jurisdiction (or tract) receives, set by the factors;
* **column totals** -- how many units each income category receives, set by HCD.

Any rule that computes a jurisdiction's income mix independently will miss the column totals.
The standard fix is iterative proportional fitting (IPF, also called RAS or biproportional
fitting): scale rows to hit the row totals, scale columns to hit the column totals, repeat. It
converges to the unique matrix that matches both margins while preserving the *odds ratios* of
the seed, which is what makes it the right tool here -- the seed encodes the methodology's
preferences, and IPF is the minimum distortion of those preferences consistent with the margins.

This is also, empirically, what SANDAG's adopted 6th-cycle allocation does, though the published
methodology never says so. See ``report/replication.py`` and ``docs/status.md``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class DidNotConverge(RuntimeError):
    """Raised when IPF fails to hit both margins within tolerance."""


def fit_to_margins(
    seed: pd.DataFrame,
    row_totals: pd.Series,
    column_totals: pd.Series,
    *,
    tolerance: float = 1e-10,
    max_iterations: int = 1000,
) -> pd.DataFrame:
    """Scale ``seed`` so its row and column sums equal the given totals.

    Args:
        seed: Non-negative matrix of relative preferences. Rows are the output geography,
            columns are income categories. Zeros are structural: a zero in the seed stays zero,
            which is why callers must apply the nonzero floor (Hard constraint 4) to the seed
            rather than to the result.
        row_totals: Desired sum for each row, indexed like ``seed.index``.
        column_totals: Desired sum for each column, indexed like ``seed.columns``.
        tolerance: Maximum absolute deviation from either margin at convergence.
        max_iterations: Give up after this many row-and-column passes.

    Returns:
        A matrix with the same shape and index as ``seed`` matching both margins.

    Raises:
        ValueError: If the margins are inconsistent (row totals and column totals must sum to
            the same number -- the RHND), if the seed has negative entries, or if a row or
            column with a nonzero target is entirely zero in the seed.
        DidNotConverge: If the tolerance is not met within ``max_iterations``.
    """
    if (seed.values < 0).any():
        raise ValueError("seed matrix contains negative values")

    row_sum = float(row_totals.sum())
    col_sum = float(column_totals.sum())
    if abs(row_sum - col_sum) > max(1e-6, abs(row_sum) * 1e-12):
        raise ValueError(
            f"margins are inconsistent: row totals sum to {row_sum:,.6f} but column totals sum "
            f"to {col_sum:,.6f}. Both must equal the RHND (Hard constraint 1)."
        )

    row_totals = row_totals.reindex(seed.index)
    column_totals = column_totals.reindex(seed.columns)
    if row_totals.isna().any() or column_totals.isna().any():
        raise ValueError("row_totals and column_totals must be indexed like the seed")

    dead_rows = seed.index[(seed.sum(axis=1) == 0) & (row_totals > 0)]
    if len(dead_rows):
        raise ValueError(
            f"rows with a nonzero target but an all-zero seed cannot be fitted: "
            f"{list(dead_rows)}. Apply the nonzero floor to the seed first."
        )
    dead_cols = seed.columns[(seed.sum(axis=0) == 0) & (column_totals > 0)]
    if len(dead_cols):
        raise ValueError(
            f"columns with a nonzero target but an all-zero seed cannot be fitted: "
            f"{list(dead_cols)}"
        )

    matrix = seed.to_numpy(dtype="float64").copy()
    rows = row_totals.to_numpy(dtype="float64")
    cols = column_totals.to_numpy(dtype="float64")

    for _ in range(max_iterations):
        current_rows = matrix.sum(axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            scale = np.where(current_rows > 0, rows / current_rows, 0.0)
        matrix *= scale[:, None]

        current_cols = matrix.sum(axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            scale = np.where(current_cols > 0, cols / current_cols, 0.0)
        matrix *= scale[None, :]

        row_error = np.abs(matrix.sum(axis=1) - rows).max()
        col_error = np.abs(matrix.sum(axis=0) - cols).max()
        if max(row_error, col_error) <= tolerance:
            break
    else:
        raise DidNotConverge(
            f"IPF did not converge in {max_iterations} iterations "
            f"(row error {row_error:.3e}, column error {col_error:.3e})"
        )

    return pd.DataFrame(matrix, index=seed.index, columns=seed.columns)


def round_preserving_totals(
    matrix: pd.DataFrame, column_totals: pd.Series | None = None
) -> pd.DataFrame:
    """Round a fractional allocation to whole units without losing or inventing any.

    Housing units are not divisible, but the fitted matrix is fractional and Hard constraint 1
    forbids the totals from drifting. This uses the largest-remainder (Hamilton) method within
    each income category: floor everything, then hand the leftover units to the cells with the
    largest discarded fractions.

    Ties are broken by row order, which is alphabetical by jurisdiction, so the result is
    deterministic (Hard constraint 7) rather than dependent on floating-point noise.

    Args:
        matrix: Fractional allocation, rows by output geography, columns by income category.
        column_totals: Integer target for each column. Defaults to the rounded column sums of
            ``matrix``.

    Returns:
        An integer matrix whose column sums equal ``column_totals`` exactly.
    """
    if column_totals is None:
        column_totals = matrix.sum(axis=0).round().astype("int64")

    out = pd.DataFrame(0, index=matrix.index, columns=matrix.columns, dtype="int64")
    for column in matrix.columns:
        values = matrix[column].to_numpy(dtype="float64")
        floors = np.floor(values).astype("int64")
        shortfall = int(column_totals[column]) - int(floors.sum())
        if shortfall > 0:
            remainders = values - floors
            # Stable sort on the negated remainder gives largest-first with row-order ties.
            winners = np.argsort(-remainders, kind="stable")[:shortfall]
            floors[winners] += 1
        elif shortfall < 0:
            remainders = values - floors
            losers = np.argsort(remainders, kind="stable")[:-shortfall]
            floors[losers] -= 1
        out[column] = floors
    return out
