# SANDAG 7th-Cycle RHNA -- Open-Data Allocation Pipeline
#
# `make all` runs the full pipeline from an empty cache to finished reports.
# `make validate` runs the 6th-cycle replication and fails if the error exceeds the documented
# threshold in report/replication.py.
#
# Everything runs through `uv run`, so there is no environment to activate and no way to
# accidentally run against a different set of library versions than the ones pinned in uv.lock.

PY := uv run --frozen python
export PYTHONPATH := $(CURDIR)

.DEFAULT_GOAL := help
.PHONY: help setup all validate ingest metrics allocate report test lint clean distclean

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## Create the virtualenv and install pinned dependencies
	uv sync --extra dev

all: setup ingest metrics allocate report  ## Full pipeline, empty cache to reports

ingest: setup  ## Layer 1: download public sources and build the crosswalk
	$(PY) -m cli ingest

metrics: ingest  ## Layer 2: build the tract feature table
	$(PY) -m cli metrics

allocate: metrics  ## Layer 3: run every methodology in params/
	$(PY) -m cli allocate

report: allocate  ## Layer 4: write markdown and CSV reports
	$(PY) -m cli report

validate: setup  ## 6th-cycle replication; fails if error exceeds threshold
	$(PY) -m cli validate

test: setup  ## Unit tests (offline only)
	uv run --frozen pytest -m "not network"

test-all: setup  ## Unit tests plus integration tests against real downloaded data
	uv run --frozen pytest

lint: setup  ## Format and lint
	uv run --frozen ruff format .
	uv run --frozen ruff check --fix .

clean:  ## Remove derived data and reports, keep the raw download cache
	rm -rf data/interim data/processed reports
	@echo "Raw cache kept. Use 'make distclean' to remove downloads too."

distclean: clean  ## Remove everything including the raw download cache
	rm -rf data/raw
