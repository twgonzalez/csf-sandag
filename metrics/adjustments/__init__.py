"""Corrections that stand between raw LODES counts and a jobs number fit to allocate housing on.

Phase 5 of the plan specifies three: the uniformed-military layer plus the multi-site employer
correction (built here), QCEW sector reconciliation and seasonal annualisation (specified, not
yet built). Each correction is a separate, toggleable module that logs every change it makes,
so a reader can check any single move against the sources.
"""
