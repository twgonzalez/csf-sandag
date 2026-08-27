"""Layer 1: Ingest.

One module per public source. Each module downloads from a cited URL, caches the raw file with a
checksum, and emits a tidy parquet at tract or block level with a documented schema.

This layer is methodology-agnostic. It contains no allocation logic and makes no judgement about
which jurisdiction should receive units. If you find yourself weighing something here, it belongs
in ``metrics/`` or ``allocate/``.
"""
