"""Layer 3: Allocation model.

The parameter files in ``params/`` are the methodology. Nothing about a method is hard-coded
here: this layer reads a parameter file, applies the factors it names to the tract feature table,
and returns tract allocations that sum exactly to the RHND.

Entry points:

:mod:`allocate.sixth_cycle`
    **Built.** A replication harness for SANDAG's adopted 6th-cycle method, which scored
    jurisdictions directly and so cannot be expressed in the general allocator without violating
    Hard constraint 2. It exists to validate the arithmetic, not to be adopted.
``allocate/model.py``
    **Not yet built.** The general, tract-scored allocator a 7th-cycle methodology will use.
    See ``docs/status.md``.
"""
