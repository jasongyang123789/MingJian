"""Tests for transmission-coefficient calibration v3.

Covers the decision-time panel (firewall: nothing after 2025-12-31),
the estimators, the adoption gates, the template wiring (the builtin
automotive template reads ADOPTED_VALUES), and the proof that the
calibrated values are actually USED — the tick drivers move the state
along the calibrated paths, and the income mapping factor reproduces
the implied annual elasticity through the real retail driver.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from planagent.services.calibration.transmission import (
    ADOPTED_VALUES,
    ANNUAL_PANEL,
    CALIBRATION_REPORT,
    DATA_CUTOFF,
    DECISION_TIME,
    TRANSMISSION_COEFFICIENT_IDS,
    calibrate_transmission_coefficients,
)
from planagent.services.distributions import sample_variable_set
from planagent.services.variables import evaluate_tick_drivers
from planagent.services.variables.models import VariableSet
from planagent.services.variables.presets import builtin_template


def test_panel_is_decision_time_only() -> None:
    """Hindsight firewall: the panel ends at the 2025-12-31 cutoff."""

    assert DECISION_TIME == "2026-01-01"
    assert DATA_CUTOFF == "2025-12-31"
    years = [row["year"] for row in ANNUAL_PANEL]
    assert years == [2019, 2020, 2021, 2022, 2023, 2024, 2025]
    assert max(years) == 2025
    # Every row carries every series (NEV penetration only from 2023,
    # when the CAAM total-caliber annual rate is published).
    for row in ANNUAL_PANEL:
        assert row["retail_10k"] > 0
        assert row["income_cny"] > 0
        assert row["lpr_1y_yearend_pct"] > 0
        assert row["avg_price_cny10k"] > 0
    assert [row["nev_penetration_caam"] for row in ANNUAL_PANEL] == [
        None,
        None,
        None,
        None,
        0.316,
        0.409,
        0.479,
    ]


def test_panel_growth_rates_match_levels() -> None:
    """Spot-checks: growth derived from levels equals the cited rates."""

    by_year = {row["year"]: row for row in ANNUAL_PANEL}
    income_growth_2025 = by_year[2025]["income_cny"] / by_year[2024]["income_cny"] - 1
    assert income_growth_2025 == pytest.approx(0.0499, abs=0.001)
    retail_growth_2025 = by_year[2025]["retail_10k"] / by_year[2024]["retail_10k"] - 1
    assert retail_growth_2025 == pytest.approx(0.0371, abs=0.001)
    assert by_year[2024]["lpr_1y_yearend_pct"] - by_year[2025][
        "lpr_1y_yearend_pct"
    ] == pytest.approx(0.10)


def test_report_is_deterministic_and_serializable() -> None:
    """Same inputs, same report — and the report is plain JSON data."""

    again = calibrate_transmission_coefficients()
    assert again == CALIBRATION_REPORT
    json.dumps(CALIBRATION_REPORT)
    assert CALIBRATION_REPORT["decision_time"] == DECISION_TIME
    assert CALIBRATION_REPORT["data_cutoff"] == DATA_CUTOFF
    assert CALIBRATION_REPORT["n_growth_observations"] == 6
    assert CALIBRATION_REPORT["growth_years"] == [2020, 2021, 2022, 2023, 2024, 2025]


def test_adopted_and_kept_sets() -> None:
    """Exactly two coefficients are adopted; six stay placeholders."""

    assert CALIBRATION_REPORT["adopted"] == [
        "income_growth_rate_annual",
        "nev_penetration_monthly_drift",
    ]
    assert CALIBRATION_REPORT["kept_prior"] == [
        "confidence_sensitivity",
        "income_sensitivity",
        "lpr_sensitivity",
        "material_passthrough",
        "price_sensitivity",
        "margin_material_sensitivity",
    ]
    assert ADOPTED_VALUES == {
        "confidence_sensitivity": 0.05,
        "income_sensitivity": 0.05,
        "lpr_sensitivity": 0.10,
        "material_passthrough": 0.30,
        "price_sensitivity": 0.20,
        "margin_material_sensitivity": 0.02,
        "income_growth_rate_annual": 0.055,
        "nev_penetration_monthly_drift": 0.0068,
    }


def test_nev_drift_adoption_record() -> None:
    record = CALIBRATION_REPORT["coefficients"]["nev_penetration_monthly_drift"]
    assert record["status"] == "adopted"
    assert record["adopted_value"] == 0.0068
    assert record["trend_slope_pp_per_year"] == pytest.approx(8.15, abs=0.01)
    assert record["trend_r2"] == pytest.approx(0.993, abs=0.001)
    assert record["trend_drift_per_month"] == pytest.approx(0.00679, abs=0.0001)
    assert record["drift_2025_only_per_month"] == pytest.approx(0.00583, abs=0.0001)
    assert record["drift_monthly_anchors_per_month"] == pytest.approx(0.0072, abs=0.0001)
    # Logistic cross-check: recent segment below the trend, older above.
    assert record["logistic_drifts_per_month"][0] == pytest.approx(0.0084, abs=0.0001)
    assert record["logistic_drifts_per_month"][1] == pytest.approx(0.0059, abs=0.0001)


def test_income_growth_adoption_record() -> None:
    record = CALIBRATION_REPORT["coefficients"]["income_growth_rate_annual"]
    assert record["status"] == "adopted"
    assert record["adopted_value"] == 0.055
    assert record["observed_mean"] == pytest.approx(0.0592, abs=0.001)
    assert record["fitted_value"] == pytest.approx(0.0550, abs=0.0005)
    assert record["prior_gate_passed"] is True
    # The gate passes narrowly — the record must not oversell it.
    assert record["loo_rmse"] < record["prior_only_rmse"]
    assert record["loo_rmse"] > 0.9 * record["prior_only_rmse"]


def test_elasticities_kept_by_the_mean_gate() -> None:
    """The joint fit passes the prior gate but fails the mean gate.

    That is the honest outcome: the annual panel (n=6) cannot beat
    "predict the mean", so no point estimate is adopted for income /
    LPR / price — the fitted values are recorded as rejected fits,
    not applied.
    """

    for coefficient in ("income_sensitivity", "lpr_sensitivity", "price_sensitivity"):
        record = CALIBRATION_REPORT["coefficients"][coefficient]
        assert record["status"] == "kept_prior"
        assert record["reason"] == "quality_gate_mean_baseline"
        assert record["adopted_value"] == record["prior"]
        assert record["prior_gate_passed"] is True
        assert record["mean_gate_passed"] is False
        assert record["joint_loo_rmse_pp"] == pytest.approx(7.64, abs=0.05)
        assert record["joint_prior_only_rmse_pp"] == pytest.approx(11.88, abs=0.05)
        assert record["joint_mean_baseline_loo_rmse_pp"] == pytest.approx(5.14, abs=0.05)
        assert record["mapped_fitted_value"] != pytest.approx(record["prior"])
    income = CALIBRATION_REPORT["coefficients"]["income_sensitivity"]
    assert income["mapped_fitted_value"] == pytest.approx(0.153, abs=0.005)
    assert income["joint_slope_pp_per_pp"] == pytest.approx(1.01, abs=0.02)
    assert income["bivariate_diagnostics"]["ols_slope_all_years"] == pytest.approx(1.18, abs=0.02)
    assert income["bivariate_diagnostics"]["ols_slope_excl_2020"] == pytest.approx(0.27, abs=0.02)
    price = CALIBRATION_REPORT["coefficients"]["price_sensitivity"]
    assert price["mapped_fitted_value"] == pytest.approx(0.039, abs=0.005)
    lpr = CALIBRATION_REPORT["coefficients"]["lpr_sensitivity"]
    assert lpr["mapped_fitted_value"] == pytest.approx(0.112, abs=0.005)


def test_unidentified_coefficients_record_reasons() -> None:
    """Confidence / passthrough / margin: no fit attempted, reason kept."""

    reasons = {
        "confidence_sensitivity": "unidentified_no_verifiable_series",
        "material_passthrough": "unidentified_one_clean_observation_wrong_sign",
        "margin_material_sensitivity": "unidentified_wrong_sign_episode",
    }
    for coefficient, reason in reasons.items():
        record = CALIBRATION_REPORT["coefficients"][coefficient]
        assert record["status"] == "kept_prior"
        assert record["reason"] == reason
        assert record["adopted_value"] == record["prior"]
        assert record["sources"], coefficient
        assert record["notes"], coefficient


def test_template_uses_adopted_values() -> None:
    """The builtin template IS the calibration: values + provenance."""

    template = builtin_template("automotive")
    by_id = {variable.id: variable for variable in template.variables}
    for coefficient in TRANSMISSION_COEFFICIENT_IDS:
        assert by_id[coefficient].distribution.value == ADOPTED_VALUES[coefficient], coefficient
    for coefficient in ("income_growth_rate_annual", "nev_penetration_monthly_drift"):
        assert by_id[coefficient].evidence_ref.startswith("calibration:v3"), coefficient
    for coefficient in (
        "confidence_sensitivity",
        "income_sensitivity",
        "lpr_sensitivity",
        "material_passthrough",
        "price_sensitivity",
        "margin_material_sensitivity",
    ):
        assert by_id[coefficient].evidence_ref.startswith("assumption:pending-calibration"), (
            coefficient
        )
        assert "transmission.CALIBRATION_REPORT" in by_id[coefficient].evidence_ref, coefficient
    # The LPR proxy baseline is now defined, not "1.0 = baseline".
    assert "3.85%" in by_id["lpr_proxy"].evidence_ref


def test_calibrated_drivers_move_state_along_calibrated_paths() -> None:
    """USED proof 1: 12 ticks of the real drivers, calibrated values.

    Income compounds at 5.50%/yr and NEV penetration drifts 0.0068/mo
    — the sampled template values flow through evaluate_tick_drivers
    into the state, they are not just stored in the report.
    """

    template = builtin_template("automotive")
    sampled = sample_variable_set(VariableSet(variables=list(template.variables)), random.Random(7))
    assert sampled["income_growth_rate_annual"] == 0.055
    assert sampled["nev_penetration_monthly_drift"] == 0.0068
    by_output = {formula.output: formula for formula in template.formulas}
    drivers = [by_output["income_index"], by_output["nev_penetration"]]
    state = {"income_index": 1.0, "nev_penetration": 0.479}
    for tick in range(1, 13):
        state.update(evaluate_tick_drivers(drivers, sampled, state, tick))
    # (1 + 0.055/12)^12, up to the drivers' 4-decimal rounding.
    assert state["income_index"] == pytest.approx((1 + 0.055 / 12) ** 12, abs=0.001)
    assert state["nev_penetration"] == pytest.approx(0.479 + 12 * 0.0068, abs=1e-9)


def test_income_mapping_factor_through_the_real_retail_driver() -> None:
    """USED proof 2: the income mapping factor, verified end to end.

    With confidence at baseline (demand growth 0), LPR and price at
    baseline, and no pull-forward drag, the ONLY retail driver term
    is income. Twelve ticks of the real income + retail drivers must
    produce the annual log-effect the mapping factor predicts:
    income_sensitivity * factor(0.055) * 0.055, where factor ~ 6.61.
    This pins the mapping the calibration uses to the driver code.
    """

    template = builtin_template("automotive")
    sampled = sample_variable_set(VariableSet(variables=list(template.variables)), random.Random(7))
    by_output = {formula.output: formula for formula in template.formulas}
    drivers = [
        by_output["pull_forward_stock"],
        by_output["price_index"],
        by_output["income_index"],
        by_output["sales_volume_retail"],
    ]
    base_values = {
        **sampled,
        "demand_growth_rate": 0.0,
        "demand_level_factor": 1.0,
        "pull_forward_stock_initial": 0.0,
    }
    state = {
        "income_index": 1.0,
        "sales_volume_retail": 197.9,
        "lpr_proxy": 1.0,
        "price_index": 1.0,
        "material_cost_index": 1.0,
        "pull_forward_stock": 0.0,
    }
    for tick in range(1, 13):
        state.update(evaluate_tick_drivers(drivers, base_values, state, tick))
    growth = sampled["income_growth_rate_annual"]
    sensitivity = sampled["income_sensitivity"]
    factor = sum((1 + growth / 12) ** t - 1 for t in range(1, 13)) / growth
    assert factor == pytest.approx(6.61, abs=0.05)
    expected_log_effect = sensitivity * factor * growth
    actual_log_effect = math.log(state["sales_volume_retail"] / 197.9)
    assert actual_log_effect == pytest.approx(expected_log_effect, rel=0.02)
    # The kept placeholder (0.05) behaves like an annual income
    # elasticity of ~0.33 — low; the rejected joint fit implied ~1.0.
    assert expected_log_effect / growth == pytest.approx(0.33, abs=0.02)
