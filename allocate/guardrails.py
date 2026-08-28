"""Statutory guardrails, enforced in code.

Gov. Code Sec. 65584.04(e)(2)(B) prohibits a COG from basing any part of a jurisdiction's share
of the regional need on certain things. Hard constraint 5 makes that a property of this pipeline
rather than a matter of care: a parameter file naming a prohibited factor is refused at load
time, the refusal is written to the run log, and no allocation is produced.

The prohibited categories, quoted from the statute and from SANDAG's own restatement of them in
the *6th Cycle RHNA Methodology*, p. 2:

1. "Any ordinance, policy, voter-approved measure, or standard of a city or county that directly
   or indirectly limits the number of residential building permits issued by a city or county."
2. "Prior underproduction of housing in a city or county from the previous regional housing need
   allocation."
3. "Stable population numbers in a city or county from the previous regional housing needs
   cycle."

Matching is on the factor's *name and declared source*, not on its values, because the values
cannot tell you what a number means. A factor called ``developable_acres`` sourced from a
jurisdiction's zoning map is a growth cap wearing a neutral name; the check that catches it is
the one that reads the source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Substrings that identify a prohibited factor, grouped by the statutory category they violate.
#: Deliberately broad: a false positive costs one line in a parameter file explaining the intent,
#: while a false negative puts an unlawful factor into an adopted methodology.
PROHIBITED_PATTERNS: dict[str, list[str]] = {
    "Gov. Code 65584.04(e)(2)(B)(i) - local permit limits": [
        r"growth\s*cap",
        r"growth\s*control",
        r"growth\s*management",
        # A permit cap or quota is essentially always the prohibited thing. A permit *limit* is
        # ambiguous -- an NPDES discharge permit limit is a federal water-quality parameter and
        # has nothing to do with building permits -- so that form requires residential context.
        r"permit\s*(cap|quota)",
        r"(building|residential|dwelling|housing)\s*permits?\s*(cap|limit|quota|allocation)",
        r"permits?\s*(cap|limit|quota|allocation)\s*(on|for)\s*(housing|residential|dwelling|units?)",
        r"limits?\s*the\s*number\s*of\s*residential\s*building\s*permits",
        r"measure\s*[a-z]\b",
        r"voter[\s_-]*approved",
        r"\bzoning\b",
        r"zoned\s*capacity",
        r"general\s*plan\s*(capacity|buildout|limit)",
        r"local\s*ordinance",
        r"density\s*limit",
        r"height\s*limit",
        r"urban\s*(growth|limit)\s*(boundary|line)",
    ],
    "Gov. Code 65584.04(e)(2)(B)(ii) - prior underproduction": [
        r"prior\s*(under)?production",
        r"underproduction",
        r"past\s*permits?",
        r"permits?\s*issued",
        r"rhna\s*progress",
        r"previous\s*cycle\s*(performance|shortfall)",
        r"unbuilt\s*rhna",
        r"carryover",
    ],
    "Gov. Code 65584.04(e)(2)(B)(iii) - stable population": [
        r"stable\s*population",
        r"population\s*stability",
        r"no\s*growth",
        r"flat\s*population",
        r"built\s*out",
        r"buildout\s*status",
    ],
}

#: Parameter files separate words with underscores or hyphens; the statute does not.
_NORMALISE = re.compile(r"[_\-]+")

_COMPILED = {
    category: [re.compile(p, re.IGNORECASE) for p in patterns]
    for category, patterns in PROHIBITED_PATTERNS.items()
}


@dataclass(frozen=True)
class Refusal:
    """One prohibited factor found in a parameter file."""

    factor: str
    matched_text: str
    statute: str

    def explain(self) -> str:
        """The line written to the run log, in the form a planner can act on."""
        return (
            f"REFUSED factor '{self.factor}': the text '{self.matched_text}' identifies a factor "
            f"prohibited by {self.statute}. This factor cannot be used to determine any "
            f"jurisdiction's share of the regional housing need. If the factor is not what its "
            f"name suggests, rename it and state its source explicitly in the parameter file."
        )


class ProhibitedFactor(ValueError):
    """Raised when a parameter file names a factor Gov. Code Sec. 65584.04(e)(2)(B) forbids."""

    def __init__(self, refusals: list[Refusal]) -> None:
        self.refusals = refusals
        super().__init__("\n".join(r.explain() for r in refusals))


#: False positives a human has adjudicated, each with the reason it is not what it looks like.
#: This exists so an ambiguous match is resolved in the open, in one auditable place, rather than
#: by quietly widening or narrowing a regular expression until the tripwire stops firing. A
#: pattern tuned until it stops complaining is a pattern that will miss the real thing later.
#:
#: Keyed by factor name; the value must state why the match is spurious.
ACKNOWLEDGED_FALSE_POSITIVES: dict[str, str] = {
    "sewer_units_accommodatable": (
        "Matches on 'permit limits' in its source description. The reference is to NPDES "
        "discharge permit limits -- a federal Clean Water Act parameter on treated effluent "
        "volume -- not to a local limit on residential building permits. Gov. Code "
        "65584.04(e) names sewer capacity as a factor a COG SHALL consider, so the underlying "
        "measure is not merely permitted but required."
    ),
}


def screen_factor(name: str, *, source: str = "", description: str = "") -> list[Refusal]:
    """Check one factor's name, source and description against the prohibited categories.

    Args:
        name: The factor's name as it appears in the parameter file.
        source: The declared data source. Screened as well as the name, because a prohibited
            input can arrive under a neutral label.
        description: The factor's prose description, screened for the same reason.

    Returns:
        A list of refusals, empty if the factor is permissible.
    """
    # Underscores and hyphens are separators in a parameter file but not in the statute's
    # language, so 'stable_population' and 'stable population' must screen identically.
    haystacks = {
        where: _NORMALISE.sub(" ", text or "")
        for where, text in (("name", name), ("source", source), ("description", description))
    }
    acknowledged = name in ACKNOWLEDGED_FALSE_POSITIVES
    refusals = []
    for category, patterns in _COMPILED.items():
        for pattern in patterns:
            for where, text in haystacks.items():
                match = pattern.search(text or "")
                if match:
                    if acknowledged:
                        # Adjudicated as spurious; the reason is recorded in
                        # ACKNOWLEDGED_FALSE_POSITIVES and surfaced by acknowledged_reasons().
                        break
                    refusals.append(
                        Refusal(
                            factor=name,
                            matched_text=f"{match.group(0)} (in {where})",
                            statute=category,
                        )
                    )
                    break
            else:
                continue
            break
    return refusals


def screen_parameters(parameters: dict) -> list[Refusal]:
    """Screen every factor in a loaded parameter file.

    Args:
        parameters: A parsed methodology parameter file. Factors are read from the ``factors``
            table; each entry may carry ``source`` and ``description`` keys.

    Returns:
        Every refusal found, across all factors.
    """
    refusals: list[Refusal] = []
    for name, spec in (parameters.get("factors") or {}).items():
        spec = spec if isinstance(spec, dict) else {}
        refusals.extend(
            screen_factor(
                name,
                source=str(spec.get("source", "")),
                description=str(spec.get("description", "")),
            )
        )
    return refusals


def enforce(parameters: dict) -> None:
    """Raise if a parameter file names any prohibited factor.

    Raises:
        ProhibitedFactor: With every refusal explained, so a planner sees the whole list rather
            than fixing them one run at a time.
    """
    refusals = screen_parameters(parameters)
    if refusals:
        raise ProhibitedFactor(refusals)


def acknowledged_reasons() -> dict[str, str]:
    """Factors whose statutory match a human has adjudicated as spurious, with the reason.

    Reported alongside every screen result so that a suppressed match is visible rather than
    silent. A reviewer should be able to see what the screen caught *and* chose not to refuse.
    """
    return dict(ACKNOWLEDGED_FALSE_POSITIVES)
