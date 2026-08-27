"""Tests for the biproportional fit and the integer rounding that follows it.

These use small synthetic fixtures so a failure points at the arithmetic rather than at a data
source. The real-data assertions live in ``test_integration.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from allocate.reconcile import DidNotConverge, fit_to_margins, round_preserving_totals


@pytest.fixture
def seed() -> pd.DataFrame:
    return pd.DataFrame(
        [[1.0, 2.0, 3.0], [4.0, 1.0, 1.0], [1.0, 1.0, 8.0]],
        index=["alpha", "bravo", "charlie"],
        columns=["low", "moderate", "above_moderate"],
    )


def test_fit_hits_both_margins(seed: pd.DataFrame) -> None:
    rows = pd.Series({"alpha": 100.0, "bravo": 250.0, "charlie": 650.0})
    columns = pd.Series({"low": 300.0, "moderate": 200.0, "above_moderate": 500.0})

    result = fit_to_margins(seed, rows, columns)

    assert np.allclose(result.sum(axis=1), rows)
    assert np.allclose(result.sum(axis=0), columns)


def test_fit_preserves_odds_ratios(seed: pd.DataFrame) -> None:
    """IPF is the minimum distortion of the seed consistent with the margins.

    The formal property is that every 2x2 cross-product ratio is unchanged. That is what makes
    the seed a statement of the methodology's preferences rather than a first guess.
    """
    rows = pd.Series({"alpha": 100.0, "bravo": 250.0, "charlie": 650.0})
    columns = pd.Series({"low": 300.0, "moderate": 200.0, "above_moderate": 500.0})

    result = fit_to_margins(seed, rows, columns)

    def odds(matrix: pd.DataFrame) -> float:
        return (matrix.iloc[0, 0] * matrix.iloc[1, 1]) / (matrix.iloc[0, 1] * matrix.iloc[1, 0])

    assert odds(result) == pytest.approx(odds(seed))


def test_inconsistent_margins_are_refused(seed: pd.DataFrame) -> None:
    rows = pd.Series({"alpha": 100.0, "bravo": 250.0, "charlie": 650.0})
    columns = pd.Series({"low": 300.0, "moderate": 200.0, "above_moderate": 499.0})

    with pytest.raises(ValueError, match="margins are inconsistent"):
        fit_to_margins(seed, rows, columns)


def test_all_zero_row_with_nonzero_target_is_refused() -> None:
    """Hard constraint 4: a jurisdiction cannot be fitted out of a zero seed row."""
    seed = pd.DataFrame([[0.0, 0.0], [1.0, 1.0]], index=["alpha", "bravo"], columns=["low", "high"])
    rows = pd.Series({"alpha": 10.0, "bravo": 90.0})
    columns = pd.Series({"low": 50.0, "high": 50.0})

    with pytest.raises(ValueError, match="all-zero seed"):
        fit_to_margins(seed, rows, columns)


def test_negative_seed_is_refused() -> None:
    seed = pd.DataFrame([[-1.0, 2.0], [1.0, 1.0]], index=["a", "b"], columns=["x", "y"])
    with pytest.raises(ValueError, match="negative"):
        fit_to_margins(seed, pd.Series({"a": 1.0, "b": 1.0}), pd.Series({"x": 1.0, "y": 1.0}))


def test_non_convergence_raises() -> None:
    seed = pd.DataFrame([[1.0, 0.0], [0.0, 1.0]], index=["a", "b"], columns=["x", "y"])
    rows = pd.Series({"a": 10.0, "b": 90.0})
    columns = pd.Series({"x": 50.0, "y": 50.0})
    with pytest.raises(DidNotConverge):
        fit_to_margins(seed, rows, columns, max_iterations=5)


def test_rounding_preserves_column_totals() -> None:
    matrix = pd.DataFrame(
        [[1.4, 2.6], [1.3, 2.7], [1.3, 2.7]], index=["a", "b", "c"], columns=["low", "high"]
    )
    targets = pd.Series({"low": 4, "high": 8})

    result = round_preserving_totals(matrix, targets)

    assert result["low"].sum() == 4
    assert result["high"].sum() == 8
    assert result.dtypes.eq("int64").all()


def test_rounding_is_deterministic_under_ties() -> None:
    """Equal remainders must break the same way every run (Hard constraint 7)."""
    matrix = pd.DataFrame(
        [[1.5], [1.5], [1.5], [1.5]], index=["a", "b", "c", "d"], columns=["units"]
    )
    targets = pd.Series({"units": 8})

    first = round_preserving_totals(matrix, targets)
    second = round_preserving_totals(matrix.copy(), targets)

    pd.testing.assert_frame_equal(first, second)
    assert first["units"].sum() == 8


def test_rounding_handles_downward_shortfall() -> None:
    matrix = pd.DataFrame([[2.9], [2.9], [2.9]], index=["a", "b", "c"], columns=["units"])
    result = round_preserving_totals(matrix, pd.Series({"units": 8}))
    assert result["units"].sum() == 8
