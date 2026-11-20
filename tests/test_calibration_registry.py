"""Item 7 (2026-11-20): calibration registry + internal-pipeline fixtures.

Pins the registry to its live sources so the inventory can never drift
silently, and exercises the internal-data intake pipeline end to end
(validate -> build overrides -> apply), including every rejection the
pipeline is designed to make.

Sources pinned here (verified 2026-11-20 against e047f50):
- template_spec.py::TEMPLATE_VARIABLES (6 curated template values +
  supply_share_simulated 0.10) and TEMPLATE_ASSUMPTION_DATA.
- transmission.py::ADOPTED_VALUES (live-read by the registry itself).
- research harness run_desay_e047f50.py::_orderbook_wiring_variables
  (2020 (0.80, 1.00, 1.20)/6799.06; 2015 (0.15, 0.25, 0.40)/917.06).
- Track B harness run_desay_gapb.py::_margin_wiring_variables
  (longrun 0.0599/0.0658, reversion 0.25, adoption (-0.02, 0, 0.02),
  clamp [0.02, 0.15]) — UNMERGED branch fix/desay-gap-profit.
- Track C branch downside.py::DOWNSIDE_DEFAULT_* (UNMERGED branch
  fix/desay-gap-downside-on) — verified against the mingjian-gap-c
  worktree.
"""

from __future__ import annotations

import copy

import pytest

from planagent.services.calibration import internal_pipeline as ip
from planagent.services.calibration.registry import (
    CURATED_ENTRIES,
    registry_entries,
    replaceable_entries,
)
from planagent.services.calibration.transmission import ADOPTED_VALUES
from planagent.simulation.domain_packs.automotive import template_spec as ts
from planagent.simulation.domain_packs.automotive.template_spec import (
    TEMPLATE_VARIABLES,
)


# ---------------------------------------------------------------- registry


def test_registry_no_duplicate_ids():
    ids = [e["id"] for e in registry_entries()]
    assert len(ids) == len(set(ids)), "duplicate registry ids"


def test_registry_status_counts():
    # Inventory as recorded 2026-11-22 (65 entries: 33 curated + 32
    # template-derived). If the template gains a labeled assumption,
    # this fails loudly on purpose — update the inventory deliberately.
    # 2026-11-22: C1 ADAS chain added 4 simulated template entries
    # (template/adas_ceiling, adas_rate, adas_midpoint, adas_coupling):
    # simulated 51 -> 55, total 61 -> 65.
    # 2026-11-23: R&D margin promotion merged (item 1) added 8
    # simulated template entries (gross_base / gross_longrun /
    # gross_reversion / rd_base / rd_longrun / rd_reversion /
    # rd_adoption / other_share): simulated 55 -> 63, total 65 -> 73.
    # 2026-11-23: margin-profit transmission merged (item 3) added 1
    # simulated template entry (tier1_pass_through, fixed):
    # simulated 63 -> 64, total 73 -> 74.
    # 2026-11-25: D2C merged (fix/desay-2018-d2c) added 1 simulated
    # template entry (template/order_backlog_opening, fixed 0.0):
    # simulated 64 -> 65, total 74 -> 75. The new template variable
    # is the frozen tick-0 book the delivery schedule delivers
    # fractions of; its evidence_ref labels it assumption:
    # pending-calibration (the stock itself was never disclosed).
    # 2026-11-20: audit A2 merged (fix/audit-a2-terms) added 2
    # simulated template entries (template/template_revenue, fixed
    # 100.0; template/accounts_receivable, fixed 600.0): simulated
    # 65 -> 67, total 75 -> 77. Both evidence_refs label them
    # assumption:pending-calibration (generic-scale sales base /
    # opening DSO stock). price_cut_factor adds no registry entry
    # (definitional seed, 1.0 = no cut yet).
    from collections import Counter

    counts = Counter(e["status"] for e in registry_entries())
    assert counts["simulated"] == 67
    assert counts["kept_prior"] == 6
    assert counts["evidence"] == 2
    assert counts["calibrated_v3"] == 2
    assert sum(counts.values()) == 77


def test_registry_transmission_values_are_live():
    live = {e["id"]: e["current"]["value"] for e in registry_entries()
            if e["group"] == "transmission_v3"}
    assert live == dict(ADOPTED_VALUES)
    assert live["nev_penetration_monthly_drift"] == 0.0068
    assert live["income_growth_rate_annual"] == 0.055


def test_registry_template_values_match_live_template():
    by_id = {v["id"]: v for v in TEMPLATE_VARIABLES}
    curated = {e["id"]: e for e in CURATED_ENTRIES}
    # order_intake_rate has no bare-id curated entry — the generic is
    # inventoried as order_intake_rate/template-generic.
    assert curated["order_intake_rate/template-generic"]["current"] == \
        by_id["order_intake_rate"]["distribution"]
    for vid in ("backlog_conversion", "order_decay",
                "annual_cut_rate", "payment_terms_months", "tier1_gross_margin"):
        assert curated[vid]["current"] == by_id[vid]["distribution"], vid
    assert ts.TEMPLATE_ASSUMPTION_DATA["supply_share_simulated"]["value"] == 0.10


def test_registry_harness_order_book_values_pinned():
    by_id = {e["id"]: e for e in CURATED_ENTRIES}
    assert by_id["order_intake_rate/desay-2020"]["current"] == {
        "type": "triangular", "min": 0.80, "mode": 1.00, "max": 1.30}
    assert by_id["order_intake_rate/desay-2015"]["current"] == {
        "type": "triangular", "min": 0.15, "mode": 0.25, "max": 0.40}
    assert by_id["order_backlog_opening/desay-2020"]["current"] == {
        "type": "fixed", "value": 6800}
    assert by_id["order_backlog_opening/desay-2015"]["current"] == {
        "type": "fixed", "value": 920}
    assert by_id["order_intake_flow_opening/desay-2020"]["current"] == {
        "type": "fixed", "value": 6800}
    assert by_id["order_intake_flow_opening/desay-2015"]["current"] == {
        "type": "fixed", "value": 920}
    assert by_id["backlog_conversion"]["current"] == {
        "type": "triangular", "min": 0.30, "mode": 0.40, "max": 0.60}
    assert by_id["order_decay"]["current"] == {
        "type": "triangular", "min": 0.10, "mode": 0.25, "max": 0.40}
    assert by_id["order_intake_rate/template-generic"]["current"] == {
        "type": "triangular", "min": 0.50, "mode": 1.00, "max": 1.50}


def test_registry_profit_chain_values_pinned():
    by_id = {e["id"]: e for e in CURATED_ENTRIES}
    assert by_id["margin_longrun/desay-2020"]["current"] == {
        "type": "fixed", "value": 0.0658}
    assert by_id["margin_longrun/desay-2015"]["current"] == {
        "type": "fixed", "value": 0.0598}
    assert by_id["margin_reversion"]["current"] == {"type": "fixed", "value": 0.16}
    assert by_id["margin_adoption"]["current"] == {
        "type": "triangular", "min": -0.02, "mode": 0.0, "max": 0.02}
    assert by_id["margin_clamp"]["current"] == {"type": "fixed", "value": [0.02, 0.15]}


def test_registry_downside_defaults_pinned():
    by_id = {e["id"]: e for e in CURATED_ENTRIES}
    assert by_id["downturn_occurs/default"]["current"] == {"type": "bernoulli", "p": 0.5}
    assert by_id["downturn_depth/default"]["current"] == {
        "type": "triangular", "min": 0.05, "mode": 0.20, "max": 0.35}
    assert by_id["downturn_start/default"]["current"] == {
        "type": "triangular", "min": 2, "mode": 3, "max": 4}
    assert by_id["downturn_duration/default"]["current"] == {
        "type": "triangular", "min": 1, "mode": 2, "max": 3}
    assert by_id["downturn_persistent/default"]["current"] == {
        "type": "bernoulli", "p": 0.15}


def test_registry_dormant_channels_flagged():
    by_id = {e["id"]: e for e in CURATED_ENTRIES}
    for vid in ("annual_cut_rate", "payment_terms_months"):
        assert "DORMANT" in by_id[vid]["channel"], vid
        assert by_id[vid]["status"] == "simulated"


def test_registry_every_simulated_entry_has_replacement_path():
    for e in registry_entries():
        if e["status"] == "simulated":
            assert e["replacement_path"], e["id"]
            assert e["evidence"], e["id"]


def test_registry_replaceable_fields_are_pipeline_parameters():
    for e in replaceable_entries():
        assert e["internal_field"] in ip.INTERNAL_PARAMETER_SPECS, e["id"]
    assert len(replaceable_entries()) == 17


# ---------------------------------------------------------------- pipeline


def _dataset(records, decision_time="2020-12-31"):
    return {
        "schema_version": ip.INTERNAL_SCHEMA_VERSION,
        "source": "test-fixture",
        "decision_time": decision_time,
        "records": records,
    }


def _rate_record(**over):
    rec = {
        "parameter_id": "order_intake_rate",
        "case": "desay-2020",
        "unit": "ratio (annualised new orders / current revenue)",
        "period_end": "2020-12-31",
        "source_ref": "fixture: 2020 annual report summary",
        "value": {"min": 0.90, "mode": 1.03, "max": 1.15},
    }
    rec.update(over)
    return rec


def test_pipeline_validate_happy_path_and_coverage():
    report = ip.validate_internal_dataset(
        _dataset([_rate_record(),
                  {"parameter_id": "order_backlog_opening",
                   "case": "desay-2020",
                   "unit": "RMB m",
                   "period_end": "2020-12-31",
                   "source_ref": "fixture: order book extract",
                   "value": 7000.0}]),
        decision_time="2020-12-31",
    )
    assert report["ok"], report["errors"]
    assert len(report["records"]) == 2
    assert report["records"][0]["distribution"] == {
        "type": "triangular", "min": 0.90, "mode": 1.03, "max": 1.15}
    # Coverage is per case: the 2020 record covers the 2020 entry only.
    assert "order_intake_rate/desay-2020" in report["coverage"]["covered"]
    assert "order_backlog_opening/desay-2020" in report["coverage"]["covered"]
    assert "order_intake_rate/desay-2015" in report["coverage"]["still_simulated"]
    assert "order_backlog_opening/desay-2015" in report["coverage"]["still_simulated"]
    # ... and never the template generic (a case value is not global).
    assert "order_intake_rate/template-generic" in report["coverage"]["still_simulated"]


def test_pipeline_rejects_wrong_schema_unit_and_late_period():
    bad = _dataset([_rate_record(unit="percent")])
    assert not ip.validate_internal_dataset(bad, decision_time="2020-12-31")["ok"]
    bad = _dataset([{"schema_version": "other"}])
    assert not ip.validate_internal_dataset(bad, decision_time="2020-12-31")["ok"]
    bad = _dataset([_rate_record(period_end="2021-06-30")])
    rep = ip.validate_internal_dataset(bad, decision_time="2020-12-31")
    assert not rep["ok"]
    assert any("AFTER decision_time" in e for e in rep["errors"])
    # Header decision_time must match the caller's — the header alone
    # never sets the firewall.
    good = _dataset([_rate_record()], decision_time="2020-06-30")
    rep = ip.validate_internal_dataset(good, decision_time="2020-12-31")
    assert not rep["ok"]


def test_pipeline_rejects_unknown_duplicate_and_fit_only():
    rep = ip.validate_internal_dataset(
        _dataset([_rate_record(parameter_id="nev_penetration_monthly_drift")]),
        decision_time="2020-12-31")
    assert not rep["ok"]
    assert any("unknown parameter_id" in e for e in rep["errors"])
    rep = ip.validate_internal_dataset(
        _dataset([_rate_record(), _rate_record()]),
        decision_time="2020-12-31")
    assert not rep["ok"]
    assert any("duplicate" in e for e in rep["errors"])
    # margin_reversion without a fit record is rejected, not estimated.
    rep = ip.validate_internal_dataset(
        _dataset([{"parameter_id": "margin_reversion",
                   "unit": "fraction per tick",
                   "period_end": "2020-12-31",
                   "source_ref": "fixture",
                   "value": 0.30}]),
        decision_time="2020-12-31")
    assert not rep["ok"]
    assert any("FIT-ONLY" in e for e in rep["errors"])
    # ... with a fit record it validates.
    rep = ip.validate_internal_dataset(
        _dataset([{"parameter_id": "margin_reversion",
                   "unit": "fraction per tick",
                   "period_end": "2020-12-31",
                   "source_ref": "fixture",
                   "fit_record": {"method": "OLS on realised net-margin path",
                                  "series": "2013-2020 audited net margin"},
                   "value": 0.30}]),
        decision_time="2020-12-31")
    assert rep["ok"], rep["errors"]


def test_pipeline_supply_share_sum_enforced():
    def share(oem, model, trim, product, value, supplier=None):
        rec = {"parameter_id": "supply_share", "oem": oem, "model": model,
               "trim": trim, "product": product,
               "unit": "share (0-1)", "period_end": "2020-12-31",
               "source_ref": "fixture", "value": value}
        if supplier is not None:
            rec["supplier"] = supplier
        return rec

    # Part D ruling: two suppliers splitting ONE slot are two records
    # with the same slot scope — that must PASS (sum arbitrates).
    rep = ip.validate_internal_dataset(
        _dataset([share("FAW-VW", "T-Roc", "280TSI", "P01", 0.6, "Ho"),
                  share("FAW-VW", "T-Roc", "280TSI", "P01", 0.4, "Rival")]),
        decision_time="2020-12-31")
    assert rep["ok"], rep["errors"]
    # Same supplier twice for one slot is still a duplicate.
    rep = ip.validate_internal_dataset(
        _dataset([share("FAW-VW", "T-Roc", "280TSI", "P01", 0.6, "Ho"),
                  share("FAW-VW", "T-Roc", "280TSI", "P01", 0.4, "Ho")]),
        decision_time="2020-12-31")
    assert not rep["ok"]
    assert any("duplicate" in e for e in rep["errors"])
    # A single record that does not sum to 1 fails the sum check.
    rep = ip.validate_internal_dataset(
        _dataset([share("FAW-VW", "T-Roc", "280TSI", "P01", 0.6)]),
        decision_time="2020-12-31")
    assert not rep["ok"]
    assert any("sum to" in e for e in rep["errors"])


def test_pipeline_dormant_parameter_warns_but_passes():
    rep = ip.validate_internal_dataset(
        _dataset([{"parameter_id": "annual_cut_rate",
                   "oem": "FAW-VW", "product": "P01",
                   "unit": "rate per year", "period_end": "2020-12-31",
                   "source_ref": "fixture",
                   "value": {"min": 0.02, "mode": 0.03, "max": 0.05}}]),
        decision_time="2020-12-31")
    assert rep["ok"], rep["errors"]
    assert any("DORMANT" in w for w in rep["warnings"])


def test_pipeline_range_converts_to_midpoint_triangular():
    # backlog_conversion is UNSCOPED, so it flows through to overrides;
    # order_intake_rate is case-scoped and stops at the manifest (see
    # test_pipeline_build_overrides_scoped_records_get_routes).
    rep = ip.validate_internal_dataset(
        _dataset([{"parameter_id": "backlog_conversion",
                   "unit": "fraction per tick",
                   "period_end": "2020-12-31",
                   "source_ref": "fixture",
                   "value": {"low": 0.30, "high": 0.50}}]),
        decision_time="2020-12-31")
    assert rep["ok"], rep["errors"]
    assert rep["records"][0]["distribution"] == {
        "type": "triangular", "min": 0.30, "mode": 0.40, "max": 0.50}
    overrides, manifest = ip.build_replacement_overrides(rep, source="fixture")
    assert manifest[0]["converted_from_range"] is True
    assert overrides["backlog_conversion"] == {
        "type": "triangular", "min": 0.30, "mode": 0.40, "max": 0.50}
    # The same conversion also applies at validation time for a scoped
    # record (it just never reaches overrides).
    rep = ip.validate_internal_dataset(
        _dataset([_rate_record(value={"low": 0.90, "high": 1.10})]),
        decision_time="2020-12-31")
    assert rep["ok"], rep["errors"]
    assert rep["records"][0]["distribution"] == {
        "type": "triangular", "min": 0.90, "mode": 1.00, "max": 1.10}


def test_pipeline_build_overrides_scoped_records_get_routes():
    rep = ip.validate_internal_dataset(
        _dataset([_rate_record(),
                  {"parameter_id": "backlog_conversion",
                   "unit": "fraction per tick",
                   "period_end": "2020-12-31",
                   "source_ref": "fixture",
                   "value": {"min": 0.30, "mode": 0.45, "max": 0.60}},
                  {"parameter_id": "supply_share",
                   "oem": "FAW-VW", "model": "T-Roc", "trim": "280TSI",
                   "product": "P01",
                   "unit": "share (0-1)", "period_end": "2020-12-31",
                   "source_ref": "fixture", "value": 1.0}]),
        decision_time="2020-12-31")
    assert rep["ok"], rep["errors"]
    overrides, manifest = ip.build_replacement_overrides(rep, source="fixture")
    # Only the UNSCOPED record lands in overrides. Case-scoped records
    # (order_intake_rate, supply_share) do NOT get silently applied to
    # a bare variable — they get a route in the manifest instead.
    assert set(overrides) == {"backlog_conversion"}
    assert overrides["backlog_conversion"] == {
        "type": "triangular", "min": 0.30, "mode": 0.45, "max": 0.60}
    rate = next(m for m in manifest if m["parameter_id"] == "order_intake_rate")
    assert rate["applied"] is False
    assert "case-level" in rate["route"]
    scoped = next(m for m in manifest if m["parameter_id"] == "supply_share")
    assert scoped["applied"] is False
    assert "S-layer" in scoped["route"]
    with pytest.raises(ip.InternalCalibrationError):
        ip.build_replacement_overrides(
            {"ok": False, "errors": ["boom"], "records": []}, source="fixture")


def test_pipeline_apply_replaces_and_never_mutates_input():
    variables = [
        {"id": "order_intake_rate", "unit": "x",
         "distribution": {"type": "triangular", "min": 0.80, "mode": 1.00, "max": 1.20},
         "evidence_ref": "simulated:industry-average"},
        {"id": "cash", "unit": "k",
         "distribution": {"type": "fixed", "value": 100},
         "evidence_ref": "estimate: founder judgment"},
    ]
    snapshot = copy.deepcopy(variables)
    new_vars, applied = ip.apply_overrides_to_variables(
        variables,
        {"order_intake_rate": {"type": "triangular", "min": 0.90, "mode": 1.03, "max": 1.15}},
        source="fixture-2020",
    )
    assert variables == snapshot  # input untouched
    assert new_vars[0]["distribution"] == {
        "type": "triangular", "min": 0.90, "mode": 1.03, "max": 1.15}
    assert new_vars[0]["evidence_ref"] == "internal:fixture-2020"
    assert new_vars[1] == variables[1]  # unrelated variable untouched
    assert applied[0]["old"] == {"type": "triangular", "min": 0.80, "mode": 1.00, "max": 1.20}
    # Unknown override id fails loudly instead of being dropped.
    with pytest.raises(ip.InternalCalibrationError):
        ip.apply_overrides_to_variables(
            variables, {"no_such_variable": {"type": "fixed", "value": 1}})
    # Scoped keys (with ':') are refused here — they have their own route.
    with pytest.raises(ip.InternalCalibrationError):
        ip.apply_overrides_to_variables(
            variables, {"supply_share:FAW-VW": {"type": "fixed", "value": 0.5}})
