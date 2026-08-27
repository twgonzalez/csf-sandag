"""Command-line entry points for the pipeline.

Each subcommand corresponds to one layer, and ``make`` targets call these rather than importing
modules directly, so that running a stage by hand and running it through ``make all`` do exactly
the same thing.
"""

from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

import cache
from config import INCOME_4

console = Console()


@click.group()
def cli() -> None:
    """SANDAG 7th-cycle RHNA open-data allocation pipeline."""


@cli.command()
@click.option("--refresh", is_flag=True, help="Re-download sources even if already cached.")
def ingest(refresh: bool) -> None:
    """Layer 1: download public sources and build the tract-to-jurisdiction crosswalk."""
    from ingest import census_api
    from ingest.acs import load_all
    from ingest.crosswalk import build_crosswalk
    from ingest.lodes import load_residence_jobs, load_workplace_jobs
    from ingest.sixth_cycle import check_allocation_sources_agree, load_adopted_allocation

    console.print("[bold]Layer 1: ingest[/bold]")
    console.print(f"  Census path: {census_api.describe_source()}")

    load_adopted_allocation(refresh=refresh)
    check_allocation_sources_agree()
    console.print("  6th-cycle baseline: portal matches adopted Plan Table 4.7")

    crosswalk = build_crosswalk(refresh=refresh)
    split = crosswalk[crosswalk["is_split"]]["tract_geoid"].nunique()
    console.print(
        f"  crosswalk: {crosswalk['tract_geoid'].nunique()} tracts, "
        f"{split} crossing a jurisdiction boundary"
    )

    wac = load_workplace_jobs(refresh=refresh)
    load_residence_jobs(refresh=refresh)
    console.print(f"  LODES: {int(wac['jobs_total'].sum()):,} workplace jobs")

    tables = load_all(refresh=refresh)
    console.print(f"  ACS: {len(tables)} tables at tract level")

    console.print(f"  raw cache: {len(cache.manifest_rows())} files, checksums recorded")


@cli.command()
def metrics() -> None:
    """Layer 2: build the tract feature table."""
    from metrics.feature_table import build

    console.print("[bold]Layer 2: tract metrics[/bold]")
    table = build()
    console.print(f"  feature table: {len(table)} tracts x {table.shape[1]} columns")
    console.print(
        f"  county jobs-housing balance: "
        f"{table['jobs_total'].sum() / table['housing_units'].sum():.3f}"
    )


@cli.command()
def allocate() -> None:
    """Layer 3: run the allocation for every methodology in params/."""
    from allocate.sixth_cycle import allocate_sixth_cycle
    from config import PROCESSED

    console.print("[bold]Layer 3: allocation[/bold]")
    result = allocate_sixth_cycle()
    result.to_parquet(PROCESSED / "allocation_sixth_cycle.parquet")
    console.print(f"  sixth_cycle: {int(result['total'].sum()):,} units across 19 jurisdictions")


@cli.command()
def report() -> None:
    """Layer 4: write the markdown and CSV reports."""
    from report.replication import build

    console.print("[bold]Layer 4: reports[/bold]")
    summary = build()
    console.print(f"  {summary['report_path']}")


@cli.command()
def validate() -> None:
    """Run the 6th-cycle replication and fail if the error exceeds the documented threshold."""
    from allocate.sixth_cycle import allocate_sixth_cycle
    from ingest.sixth_cycle import adopted_allocation_wide
    from report.replication import ABSOLUTE_TOLERANCE_UNITS, RELATIVE_TOLERANCE
    from report.replication import validate as run

    summary = run()

    model = allocate_sixth_cycle()
    published = adopted_allocation_wide()
    table = Table(title="6th-Cycle Replication")
    table.add_column("Jurisdiction")
    table.add_column("Model", justify="right")
    table.add_column("Adopted", justify="right")
    table.add_column("Diff", justify="right")
    for key in model.index:
        diff = int(model.loc[key, "total"] - published.loc[key, "total"])
        table.add_row(
            key.replace("_", " ").title(),
            f"{int(model.loc[key, 'total']):,}",
            f"{int(published.loc[key, 'total']):,}",
            f"{diff:+d}" if diff else "0",
        )
    table.add_section()
    table.add_row(
        "Region",
        f"{int(model['total'].sum()):,}",
        f"{int(published['total'].sum()):,}",
        "0",
        style="bold",
    )
    console.print(table)

    for category in INCOME_4:
        console.print(
            f"  {category.replace('_', ' '):>15}: "
            f"{int(model[category].sum()):>7,} (adopted {int(published[category].sum()):,})"
        )

    console.print(
        f"\n[bold green]PASS[/bold green] — largest jurisdiction error "
        f"{summary['max_jurisdiction_error_units']} units "
        f"({summary['max_jurisdiction_error_pct']:.3f}%), largest cell error "
        f"{summary['max_cell_error_units']} units. "
        f"Thresholds: {ABSOLUTE_TOLERANCE_UNITS} units / {RELATIVE_TOLERANCE * 100:.0f}%."
    )


if __name__ == "__main__":
    cli()
