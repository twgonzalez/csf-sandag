"""Tests for the two built jobs corrections: the military layer and the multi-site detector.

The offline tests pin the arithmetic of each correction against small synthetic worlds where
the right answer is computable by hand. The network test runs the real report and asserts the
Navy known-answer holds on real data -- the acceptance test docs/plan.md Phase 5 specifies.
"""

from __future__ import annotations

import pandas as pd
import pytest

import metrics.adjustments.military as military_mod
import metrics.adjustments.multi_site as multi_site_mod

# ---------------------------------------------------------------------------- multi-site


def _roster(schools_rows, offices_rows):
    schools = pd.DataFrame(schools_rows, columns=["cds_code", "district", "name", "tract_geoid"])
    offices = pd.DataFrame(offices_rows, columns=["cds_code", "district", "name", "tract_geoid"])
    return schools, offices, {"schools": len(schools), "district_offices": len(offices)}


def _wac(rows):
    return pd.DataFrame(rows, columns=["tract_geoid", "jobs_total", "educational_services"])


def test_multi_site_moves_a_clear_pileup(monkeypatch):
    """A district office holding nearly all sector jobs, with quiet schools, gets moved."""
    schools = [(f"s{i}", "Pileup Unified", f"school {i}", f"T{i % 5:03d}") for i in range(10)]
    offices = [("d0000000", "Pileup Unified", "office", "OFF")]
    wac = _wac([("OFF", 4000, 4000)] + [(f"T{i:03d}", 100, 100) for i in range(5)])

    monkeypatch.setattr(
        multi_site_mod, "load_school_roster", lambda **kw: _roster(schools, offices)
    )
    monkeypatch.setattr(multi_site_mod, "workplace_jobs", lambda: wac)

    deltas, log = multi_site_mod.school_district_correction()
    record = log["districts"][0]
    assert record["action"].startswith("moved")
    # excess = 4000 - 0.10 * (4000 + 500) = 3550; cap = 80 * 10 = 800 binds.
    assert record["moved"] == 800
    assert record["cap_bound"] is True
    assert abs(deltas["jobs_delta"].sum()) < 1e-9
    assert float(deltas.set_index("tract_geoid").loc["OFF", "jobs_delta"]) == -800


def test_multi_site_requires_spike_signature(monkeypatch):
    """A big office next to an equally big school tract is flagged, never moved."""
    schools = [(f"s{i}", "Even Unified", f"school {i}", f"T{i:03d}") for i in range(6)]
    offices = [("d0000000", "Even Unified", "office", "OFF")]
    wac = _wac([("OFF", 2000, 2000)] + [(f"T{i:03d}", 900, 900) for i in range(6)])

    monkeypatch.setattr(
        multi_site_mod, "load_school_roster", lambda **kw: _roster(schools, offices)
    )
    monkeypatch.setattr(multi_site_mod, "workplace_jobs", lambda: wac)

    deltas, log = multi_site_mod.school_district_correction()
    assert log["districts"][0]["action"].startswith("flagged")
    assert deltas.empty


def test_multi_site_ignores_small_districts_and_small_excess(monkeypatch):
    """Below the site or excess thresholds, nothing happens and the log says why."""
    schools = [(f"s{i}", "Tiny", f"school {i}", f"T{i:03d}") for i in range(3)]
    offices = [("d0000000", "Tiny", "office", "OFF")]
    wac = _wac([("OFF", 5000, 5000)])

    monkeypatch.setattr(
        multi_site_mod, "load_school_roster", lambda **kw: _roster(schools, offices)
    )
    monkeypatch.setattr(multi_site_mod, "workplace_jobs", lambda: wac)

    deltas, log = multi_site_mod.school_district_correction()
    assert deltas.empty
    assert log["districts"] == []  # three sites is under MIN_SITES; never examined


# ---------------------------------------------------------------------------- military


def _patch_military_world(monkeypatch, *, acs, lodes_blocks, gq_blocks, county_total=1000):
    monkeypatch.setattr(military_mod, "county_uniformed_total", lambda: county_total)
    monkeypatch.setattr(military_mod, "california_active_duty", lambda **kw: county_total * 10)
    monkeypatch.setattr(
        military_mod, "workplace_workers_by_jurisdiction", lambda **kw: pd.DataFrame(acs)
    )
    monkeypatch.setattr(
        military_mod, "load_workplace_jobs", lambda **kw: pd.DataFrame(lodes_blocks)
    )
    monkeypatch.setattr(military_mod, "load_military_gq", lambda **kw: pd.DataFrame(gq_blocks))
    blocks = pd.DataFrame(
        {
            "block_geoid": ["B1", "B2", "B3"],
            "tract_geoid": ["TR1", "TR2", "TR3"],
            "jurisdiction": ["base_town", "base_town", "quiet_town"],
        }
    )
    monkeypatch.setattr(military_mod, "load_block_geography", lambda **kw: blocks)


def _reference_roster(tmp_path, monkeypatch, rows):
    ref = tmp_path / "reference"
    ref.mkdir()
    pd.DataFrame(
        rows, columns=["installation", "service", "jurisdiction", "workforce", "notes"]
    ).to_csv(ref / "military_installations.csv", index=False)
    monkeypatch.setattr(military_mod, "REFERENCE", ref)


def test_military_layer_sums_to_control_and_zeroes_nonroster(tmp_path, monkeypatch):
    """The county control total is exact, and towns without installations get nothing."""
    _reference_roster(tmp_path, monkeypatch, [("base", "navy", "base_town", "major", "")])
    _patch_military_world(
        monkeypatch,
        acs=[
            {"jurisdiction": "base_town", "acs_workplace_workers": 2000, "acs_workplace_moe": 10},
            {"jurisdiction": "quiet_town", "acs_workplace_workers": 1000, "acs_workplace_moe": 10},
        ],
        lodes_blocks=[
            {"block_geoid": "B1", "jobs_total": 500},
            {"block_geoid": "B2", "jobs_total": 400},
            {"block_geoid": "B3", "jobs_total": 950},
        ],
        gq_blocks=[{"block_geoid": "B1", "military_gq": 300}],
    )
    tracts, log = military_mod.military_jobs()
    assert tracts["military_jobs"].sum() == pytest.approx(1000)
    by = {r["jurisdiction"]: r["military_jobs"] for r in log["by_jurisdiction"]}
    assert by["quiet_town"] == 0
    assert by["base_town"] == pytest.approx(1000)
    # Placement followed quarters: all of base_town's jobs sit on B1's tract.
    assert tracts.set_index("tract_geoid")["military_jobs"]["TR1"] == pytest.approx(1000)


def test_military_minor_only_jurisdiction_gets_zero(tmp_path, monkeypatch):
    """A jurisdiction hosting only a `minor` site (an outlying field) is excluded."""
    _reference_roster(
        tmp_path,
        monkeypatch,
        [
            ("base", "navy", "base_town", "major", ""),
            ("field", "navy", "quiet_town", "minor", "no workforce"),
        ],
    )
    _patch_military_world(
        monkeypatch,
        acs=[
            {"jurisdiction": "base_town", "acs_workplace_workers": 2000, "acs_workplace_moe": 10},
            {"jurisdiction": "quiet_town", "acs_workplace_workers": 1000, "acs_workplace_moe": 10},
        ],
        lodes_blocks=[
            {"block_geoid": "B1", "jobs_total": 500},
            {"block_geoid": "B2", "jobs_total": 400},
            {"block_geoid": "B3", "jobs_total": 700},
        ],
        gq_blocks=[{"block_geoid": "B1", "military_gq": 300}],
    )
    _, log = military_mod.military_jobs()
    by = {r["jurisdiction"]: r["military_jobs"] for r in log["by_jurisdiction"]}
    assert by["quiet_town"] == 0


def test_military_ceiling_violation_raises(tmp_path, monkeypatch):
    """A county total above the state ceiling means a source was misread: hard stop."""
    _reference_roster(tmp_path, monkeypatch, [("base", "navy", "base_town", "major", "")])
    monkeypatch.setattr(military_mod, "county_uniformed_total", lambda: 1000)
    monkeypatch.setattr(military_mod, "california_active_duty", lambda **kw: 500)
    with pytest.raises(ValueError, match="ceiling"):
        military_mod.military_jobs()


# ---------------------------------------------------------------------------- integration


@pytest.mark.network
def test_navy_known_answer_on_real_data():
    """Phase 5 acceptance test: the 6th cycle's one error cannot recur, from open data alone."""
    from report.jobs_adjustments import write

    summary = write()
    assert summary["known_answer_passed"] is True
