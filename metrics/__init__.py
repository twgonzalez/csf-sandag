"""Layer 2: Tract metrics.

Pure functions from Layer 1 outputs to a single tract-level feature table. Still no allocation
decisions: nothing here knows how many units the region has to place, and nothing here decides
which tract deserves them. Each metric is one module whose docstring cites its source and states
its rule.
"""
