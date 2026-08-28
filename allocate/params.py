"""Methodology parameter files: the schema and the loader.

The parameter file **is** the methodology (project brief, Layer 3). Nothing about a method is
hard-coded in the allocator; everything a methodology chooses -- factors, weights, income-split
rule, floors, mass bases -- lives in a TOML file in ``params/``, and two methodologies differ
only in their files. That is what makes the delta report meaningful: every column is a file, and
rerunning the file reproduces the column byte for byte.

The loader is also the enforcement point for two hard constraints, applied before any allocation
arithmetic can run:

* **Hard constraint 5** -- every factor is screened against Gov. Code Sec. 65584.04(e)(2)(B) by
  :mod:`allocate.guardrails`. A prohibited factor refuses the whole file, and the refusal is
  written to the run log with its statutory citation.
* **Hard constraint 2** -- the declared geography must be ``tract``. A jurisdiction-scored
  methodology is refused unless the file carries ``replication_only = true``, which exists for
  exactly one file: the adopted 6th-cycle method, kept as a validation harness and barred from
  proposing anything.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from allocate.guardrails import ProhibitedFactor, acknowledged_reasons, screen_parameters
from config import PARAMS, REPORTS

#: Where refusals are recorded. Constraint 5 requires the refusal to be explained in the run
#: log, not just raised -- a planner who hands the pipeline a parameter file and gets a stack
#: trace has been told less than the statute requires us to say.
RUN_LOG = REPORTS / "run_log.md"


class InvalidMethodology(ValueError):
    """A parameter file that is malformed or violates a structural rule.

    Distinct from :class:`allocate.guardrails.ProhibitedFactor`, which is about the *statute*;
    this is about the *schema*. The distinction matters in the run log: one says "fix your
    file", the other says "the law forbids this factor".
    """


@dataclass(frozen=True)
class Factor:
    """One allocation factor, as declared in a parameter file.

    Attributes:
        name: The factor's key in the file. Must name a column in the tract feature table by the
            time the allocator runs (checked there, not here -- the loader has no data).
        weight: Share of the category's units this factor distributes. Weights across factors
            addressing the same income group must sum to 1; checked by the allocator.
        source: Where the underlying data comes from. Required -- an uncited factor is refused,
            because the methodology appendix under Sec. 65584.04(f) is generated from these
            declarations and an empty citation would surface there.
        description: The rule, in a sentence. Required, same reason.
    """

    name: str
    weight: float
    source: str
    description: str


@dataclass(frozen=True)
class Methodology:
    """A loaded, validated, guardrail-screened methodology.

    Attributes:
        name: Stable identifier, used in report columns and output filenames.
        label: Human-readable name for report headings.
        geography: ``"tract"`` for anything this pipeline would propose. ``"jurisdiction"``
            survives loading only under ``replication_only``.
        replication_only: True for the archived 6th-cycle method. The allocator refuses to run
            a replication-only file; it exists to be validated against, not to allocate.
        factors: The screened factor table.
        income_split: The income-split rule and its settings, passed through to the allocator.
        parameters: Named tuning values (floors, mass bases, scenario pins). Every judgement
            call a methodology makes should appear here by name rather than as a constant in
            code, so the report can print it.
        source_path: The file this came from, for the run log and the appendix.
        raw: The full parsed TOML, for anything a report wants to quote verbatim.
    """

    name: str
    label: str
    geography: str
    replication_only: bool
    factors: tuple[Factor, ...]
    income_split: dict
    parameters: dict
    source_path: Path
    raw: dict = field(repr=False)


def _log(lines: list[str]) -> None:
    """Append to the run log, creating it with a header on first write."""
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    if not RUN_LOG.exists():
        RUN_LOG.write_text(
            "# Run log\n\nRefusals and notable events, newest last. Each entry cites the rule "
            "it enforces.\n"
        )
    with RUN_LOG.open("a") as fh:
        fh.write(f"\n## {stamp}\n\n")
        for line in lines:
            fh.write(f"- {line}\n")


def load_methodology(path: str | Path) -> Methodology:
    """Load, validate, and screen one methodology parameter file.

    Order of checks is deliberate: schema first (so a malformed file gets a schema error, not a
    confusing statutory one), then the statutory screen, then the geography rule. Every refusal
    is written to the run log before the exception propagates.

    Args:
        path: Path to a TOML file, or a bare name resolved against ``params/``.

    Returns:
        A validated :class:`Methodology`.

    Raises:
        InvalidMethodology: Malformed file, missing required keys, uncited factor, or a
            jurisdiction-scored file without the replication flag.
        allocate.guardrails.ProhibitedFactor: A factor Gov. Code Sec. 65584.04(e)(2)(B) forbids.
    """
    path = Path(path)
    if not path.suffix:
        path = path.with_suffix(".toml")
    if not path.exists() and not path.is_absolute():
        path = PARAMS / path.name

    try:
        raw = tomllib.loads(path.read_text())
    except FileNotFoundError:
        raise InvalidMethodology(f"no parameter file at {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise InvalidMethodology(f"{path.name} is not valid TOML: {exc}") from None

    meta = raw.get("methodology")
    if not isinstance(meta, dict):
        raise InvalidMethodology(f"{path.name} has no [methodology] table")
    for key in ("name", "geography"):
        if key not in meta:
            raise InvalidMethodology(f"{path.name}: [methodology] is missing '{key}'")

    replication_only = bool(meta.get("replication_only", False))
    geography = str(meta["geography"])

    factors = _parse_factors(raw, path)

    # Statutory screen -- Hard constraint 5. Screened even for replication-only files: the
    # archived 6th-cycle method must itself be lawful, and the screen proves it on every load.
    refusals = screen_parameters(raw)
    if refusals:
        _log(
            [f"REFUSED `{path.name}`: {r.explain()}" for r in refusals]
            + [
                f"Adjudicated false positives in effect: {sorted(acknowledged_reasons())}"
                if acknowledged_reasons()
                else "No adjudicated false positives in effect."
            ]
        )
        raise ProhibitedFactor(refusals)

    # Geography rule -- Hard constraint 2.
    if geography != "tract" and not replication_only:
        message = (
            f"{path.name} declares geography = '{geography}'. All scoring happens at the census "
            "tract; jurisdictions are never scored directly (Hard constraint 2). Only the "
            "archived 6th-cycle replication may declare jurisdiction geography, under "
            "replication_only = true."
        )
        _log([f"REFUSED `{path.name}`: {message}"])
        raise InvalidMethodology(message)

    return Methodology(
        name=str(meta["name"]),
        label=str(meta.get("label", meta["name"])),
        geography=geography,
        replication_only=replication_only,
        factors=factors,
        income_split=dict(raw.get("income_split", {})),
        parameters=dict(raw.get("parameters", {})),
        source_path=path,
        raw=raw,
    )


def _parse_factors(raw: dict, path: Path) -> tuple[Factor, ...]:
    """Validate the factor table: every factor cited, every weight a number.

    A factor without a source is refused here rather than discovered later, because the
    Sec. 65584.04(f) appendix is generated from these declarations and an uncited factor would
    surface as an empty citation in the document HCD reads.
    """
    table = raw.get("factors") or {}
    if not isinstance(table, dict):
        raise InvalidMethodology(f"{path.name}: [factors] must be a table of factor tables")

    factors = []
    for name, spec in table.items():
        if not isinstance(spec, dict):
            raise InvalidMethodology(f"{path.name}: factor '{name}' must be a table")
        missing = [k for k in ("source", "description") if not str(spec.get(k, "")).strip()]
        if missing:
            raise InvalidMethodology(
                f"{path.name}: factor '{name}' is missing {missing}. Every factor must cite its "
                "source and state its rule -- the Sec. 65584.04(f) appendix is generated from "
                "these fields."
            )
        weight = spec.get("weight", 0.0)
        if not isinstance(weight, int | float) or isinstance(weight, bool):
            raise InvalidMethodology(f"{path.name}: factor '{name}' weight must be a number")
        factors.append(
            Factor(
                name=str(name),
                weight=float(weight),
                source=str(spec["source"]),
                description=str(spec["description"]),
            )
        )
    return tuple(factors)


def list_methodologies() -> list[Path]:
    """Every parameter file in ``params/``, sorted for deterministic run order."""
    return sorted(PARAMS.glob("*.toml"))
