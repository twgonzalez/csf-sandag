"""Replication of the CTCAC/HCD Opportunity Map score.

The 6th-cycle replication in ``report/replication.py`` asked whether an adopted methodology could
be recomputed from its own published documents. The answer there was no -- a load-bearing step was
missing. This module asks the same question of the map that will carry the fair-housing objective
in the 7th cycle.

**The answer here is yes, exactly.** TCAC publishes each of the eight input indicators, each
regional median, and the environmental burden flag alongside the score itself, and the score
follows from them by a rule simple enough to state in one line. Every San Diego tract with
complete indicator data reproduces.

That is worth saying plainly to a board: the transparency standard this project is arguing for is
not hypothetical or burdensome. The state's own fair-housing map already meets it.
"""

from __future__ import annotations

import pandas as pd

from ingest.opportunity_map import ALL_INDICATORS, _slug, load_opportunity_map

#: The score's floor. A tract that beats the regional median on nothing still scores 1, not 0, so
#: the published range is 1 through 9 before the environmental penalty is applied.
SCORE_BASE = 1


def replicate_opportunity_score(table: pd.DataFrame | None = None) -> pd.DataFrame:
    """Recompute the CTCAC/HCD Opportunity Score from its published inputs.

    Rule:
        Count the indicators on which the tract is **at or above** its region's median, add one,
        then subtract the environmental burden flag::

            score = count(indicator >= regional median) + 1 - environmental_burden_flag

        Two details in that line are load-bearing and were recovered by testing against the
        published output rather than read from the methodology:

        * The comparison is **at or above**, not strictly above. Using ``>`` misses eight San
          Diego tracts where an indicator sits exactly on its regional median.
        * The environmental burden flag is a **subtraction from the composite**, not a separate
          screen applied afterwards. It moves 43 San Diego tracts.

    Regional medians are taken from the columns TCAC publishes rather than recomputed, because
    the median is over TCAC's own region definition -- San Diego County is its own region here,
    but that is a TCAC choice and recomputing it would silently substitute ours for theirs.

    Args:
        table: An Opportunity Map frame from :func:`ingest.opportunity_map.load_opportunity_map`.
            Loaded if omitted.

    Returns:
        The input frame plus ``indicators_at_or_above_median``, ``replicated_score``,
        ``score_matches``, and ``indicators_missing``.
    """
    if table is None:
        table = load_opportunity_map()

    out = table.copy()
    slugs = [_slug(i) for i in ALL_INDICATORS]

    at_or_above = sum((out[s] >= out[f"regional_median_{s}"]).astype("int64") for s in slugs)
    out["indicators_missing"] = out[slugs].isna().sum(axis=1)
    out["indicators_at_or_above_median"] = at_or_above
    out["replicated_score"] = (
        at_or_above + SCORE_BASE - out["environmental_burden_flag"].fillna(0)
    ).astype("int64")
    out["score_matches"] = out["replicated_score"] == out["opportunity_score"]
    return out


def replication_summary(table: pd.DataFrame | None = None) -> dict:
    """Agreement between the replicated and published scores.

    Two exclusions, both deliberate:

    * **Tracts TCAC published as block groups.** Their tract-level score is a housing-unit
      weighted mean this pipeline computed, not a number TCAC published, so checking our
      arithmetic against our own arithmetic would prove nothing. They are counted separately as
      ``aggregated_tracts``.
    * **Tracts with a missing indicator.** TCAC does not document how it scores them, so counting
      them as failures would overstate the disagreement and counting them as successes would
      hide it.

    Returns:
        Keys ``complete_tracts``, ``complete_matches``, ``complete_match_rate``,
        ``incomplete_tracts``, ``incomplete_matches``, ``aggregated_tracts``, ``total_tracts``,
        and ``exact``.
    """
    scored = replicate_opportunity_score(table)
    aggregated = int((scored.get("geography", "tract") != "tract").sum())
    published = scored[scored.get("geography", "tract") == "tract"]
    complete = published[published["indicators_missing"] == 0]
    incomplete = published[published["indicators_missing"] > 0]

    complete_matches = int(complete["score_matches"].sum())
    return {
        "total_tracts": int(len(scored)),
        "aggregated_tracts": aggregated,
        "complete_tracts": int(len(complete)),
        "complete_matches": complete_matches,
        "complete_match_rate": complete_matches / len(complete) if len(complete) else 0.0,
        "incomplete_tracts": int(len(incomplete)),
        "incomplete_matches": int(incomplete["score_matches"].sum()),
        "exact": complete_matches == len(complete),
    }


def category_from_score(score: int) -> str:
    """The resource category a score falls in.

    Rule:
        Scores 8-9 are Highest Resource, 6-7 High, 4-5 Moderate, 0-3 Low. Derived from the
        published score-to-category mapping in the 2026 map, which is a fixed banding rather than
        a within-region percentile -- the regional comparison already happened when each indicator
        was compared to its regional median.

    Args:
        score: An Opportunity Score.

    Returns:
        One of the strings in :data:`ingest.opportunity_map.OPPORTUNITY_CATEGORIES`.
    """
    if score >= 8:
        return "Highest Resource"
    if score >= 6:
        return "High Resource"
    if score >= 4:
        return "Moderate Resource"
    return "Low Resource"


def check_category_banding(table: pd.DataFrame | None = None) -> dict:
    """Confirm :func:`category_from_score` reproduces the published category for every tract."""
    scored = replicate_opportunity_score(table)
    scored = scored[scored.get("geography", "tract") == "tract"]
    derived = scored["opportunity_score"].dropna().astype(int).map(category_from_score)
    published = scored.loc[derived.index, "opportunity_category"]
    matches = int((derived == published).sum())
    return {
        "tracts": int(len(derived)),
        "matches": matches,
        "exact": matches == len(derived),
    }


def lower_income_target_tracts(table: pd.DataFrame | None = None) -> pd.DataFrame:
    """Tracts in High or Highest Resource, which the AFFH gate measures performance against.

    Gov. Code Sec. 65584(d)(5) requires the allocation to affirmatively further fair housing. The
    operational test this pipeline uses is the share of lower-income units landing in these
    tracts, compared against a resource-only baseline.

    The ``high_poverty_segregated_flag`` is carried through deliberately. It is not a resource
    category and a tract can carry it at any category; losing track of it would defeat the point
    of the measure.
    """
    if table is None:
        table = load_opportunity_map()
    return table[table["opportunity_category"].isin(["High Resource", "Highest Resource"])].copy()
