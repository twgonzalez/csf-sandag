"""Shared formatting for report tables.

Kept in one place so every report renders a unit count, a percentage and a delta the same way,
and so the markdown and the CSV never drift apart. The markdown renderer is written out here
rather than delegated to a formatting library: it is twenty lines, it removes a dependency, and
it guarantees byte-identical output across machines (Hard constraint 7).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ingest.sixth_cycle import load_jurisdictions


def display_names(index: pd.Index) -> pd.Index:
    """Map jurisdiction keys to the names a planner would recognise in a board packet."""
    names = load_jurisdictions().set_index("jurisdiction")["name"]
    return pd.Index([names.get(k, k) for k in index], name="Jurisdiction")


def _format(value: object) -> str:
    """Render one cell: thousands separators for counts, three decimals for percentages."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | pd.Int64Dtype().type):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.3f}"
    return str(value)


def to_markdown(frame: pd.DataFrame, *, index_label: str = "Jurisdiction") -> str:
    """Render a frame as a GitHub-flavoured markdown table, numbers right-aligned."""
    header = [index_label, *(str(c) for c in frame.columns)]
    rows = [[str(idx), *(_format(v) for v in frame.loc[idx])] for idx in frame.index]
    widths = [
        max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i])
        for i in range(len(header))
    ]
    # First column left-aligned (names); the rest right-aligned (numbers).
    align = ["|" + "-" * (widths[0] + 2)] + [
        "|" + "-" * (widths[i] + 1) + ":" for i in range(1, len(widths))
    ]

    lines = [
        "| " + " | ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)) + " |",
        "".join(align) + "|",
    ]
    for row in rows:
        cells = [row[0].ljust(widths[0])] + [row[i].rjust(widths[i]) for i in range(1, len(row))]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_pair(frame: pd.DataFrame, csv_path: Path, *, index_label: str = "jurisdiction") -> str:
    """Write a frame to CSV and return its markdown rendering.

    Every table in every report goes through here, so the CSV a reader downloads always holds the
    same numbers as the markdown they were reading.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index_label=index_label)
    return to_markdown(frame, index_label=index_label.replace("_", " ").title())
