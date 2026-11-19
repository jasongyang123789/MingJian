"""Transmission-coefficient calibration v3 (elasticity calibration).

The automotive template's transmission coefficients (income / LPR /
price sensitivities, material passthrough, margin response, NEV
penetration drift, income growth) shipped as labeled-assumption
placeholders (synthesis C5: "no public elasticity exists", "no
initial value"). This module replaces what the data can replace and
records, with evidence, what it cannot.

Decision-time discipline (hindsight firewall, Sprint 5/10)
-----------------------------------------------------------
All estimation uses data available at the decision time
``DECISION_TIME = 2026-01-01`` — i.e. observations through
``DATA_CUTOFF = 2025-12-31`` only. Nothing from 2026 is used: the
2026 policy-cliff year is the OUTCOME the calibrated model simulates,
so fitting to it would be hindsight. A later decision time re-runs
this module on a longer panel; the cutoff is a module constant, not
a hidden choice.

Estimation design
-----------------
* NEV penetration drift: OLS trend on the CAAM total-caliber annual
  penetrations 2023-2025, cross-checked against the 2025-only drift,
  the 2025 monthly anchors, and a logistic-implied instantaneous
  drift at the current penetration. Adopted when the trend R^2 >= 0.9
  and both cross-checks sit within 0.002/mo of the trend value.
* Income growth rate: ridge-shrunk location fit
  (:func:`ridge_location_fit`, prior = the 0.05 NBS-2025 anchor) of
  the 2020-2025 nominal per-capita disposable-income growth rates.
* Income / LPR / price sensitivities: ONE joint centered
  ridge-to-prior fit of annual retail growth on the three drivers
  (percentage-point units, priors = the placeholder-implied
  regression slopes, so the fit is shrinkage away from the
  placeholders, not from zero). Adoption requires BOTH gates:
  (1) the codebase's prior gate — fitted LOO RMSE <= prior-only
  RMSE; (2) a mean gate — fitted LOO RMSE <= the leave-one-out
  mean-prediction RMSE. A fit that cannot beat "predict the mean"
  is noise, however it compares to a bad prior, and its coefficient
  stays a labeled placeholder. Bivariate OLS slopes (with and
  without the 2020 COVID year) are recorded as stability
  diagnostics.
* Confidence / material-passthrough / margin sensitivities: NOT
  estimable from the verified annual data (reasons recorded per
  coefficient). They stay labeled placeholders; the module records
  the failed identification instead of inventing a value.

Model-unit mappings (the regression slopes are annual, the template
coefficients are monthly semi-elasticities — the factors below are
the exact steady-state conversions, documented so a reader can
re-derive them):
* income: a persistent annual income growth rate ``g`` lifts the
  income index to ``(1 + g/12)**t`` in month ``t``; the 12-month
  retail log-effect of ``income_sensitivity`` is
  ``income_sensitivity * sum_t ((1+g/12)**t - 1)``. The factor
  ``_income_annual_factor(g) = sum_t ((1+g/12)**t - 1) / g`` (~6.6
  at g = 5%) converts the annual income elasticity ``beta`` to the
  monthly coefficient ``beta / factor``.
* price: a persistent price-level shift ``dp`` drags monthly growth
  by ``price_sensitivity * dp`` every month, so the annual effect
  is ``12 * price_sensitivity * dp``; ``price_sensitivity =
  -beta_price / 12``.
* LPR: ``lpr_proxy`` is DEFINED here as ``1y LPR / 3.85%`` (3.85%
  = the 2020-2021 modal 1y LPR, the pre-easing level; the pack
  previously left the baseline undefined). A persistent 1pp LPR
  cut moves the proxy by ``-1/3.85`` and the annual retail effect
  is ``12 * lpr_sensitivity / 3.85`` per pp; ``lpr_sensitivity =
  -beta_lpr / (12 / 3.85)``.

Everything here is deterministic given its inputs (seeded bootstrap)
and pure (no I/O): the panel is embedded below with a source per
series, so the fit is reproducible from the module alone. The
builtin automotive template reads :data:`ADOPTED_VALUES` from this
module — the calibrated values are the template's values, not a
side table.
"""

from __future__ import annotations

import math
from typing import Any

from .estimator import (
    DEFAULT_BOOTSTRAP_DRAWS,
    DEFAULT_CALIBRATION_SEED,
    DEFAULT_RIDGE_STRENGTH,
    bootstrap_coefficient_intervals,
    fit_centered_ridge_to_prior,
    leave_one_out_rmse,
    prior_only_rmse,
    ridge_location_fit,
)

#: Decision time for this calibration: the model simulates 2026+, so
#: only data available on 2026-01-01 may enter the fit.
DECISION_TIME = "2026-01-01"

#: Last observation date admitted to any fit below.
DATA_CUTOFF = "2025-12-31"

#: LPR-proxy baseline (see module docstring): 1y LPR / this value.
#: 3.85% is the 2020-2021 modal 1y LPR, the level before the
#: 2022-2025 easing cycle (PBOC monthly quotes).
LPR_PROXY_BASELINE_PCT = 3.85

#: Placeholder values the joint-fit priors are derived from (the
#: template's current fixed values). The priors are the regression
#: slopes these placeholders imply, via the mapping factors.
PLACEHOLDERS: dict[str, float] = {
    "confidence_sensitivity": 0.05,
    "income_sensitivity": 0.05,
    "lpr_sensitivity": 0.10,
    "material_passthrough": 0.30,
    "price_sensitivity": 0.20,
    "margin_material_sensitivity": 0.02,
    "income_growth_rate_annual": 0.05,
    "nev_penetration_monthly_drift": 0.002,
}

#: Coefficients this module calibrates, in template order.
TRANSMISSION_COEFFICIENT_IDS: list[str] = [
    "confidence_sensitivity",
    "income_sensitivity",
    "lpr_sensitivity",
    "material_passthrough",
    "price_sensitivity",
    "margin_material_sensitivity",
    "income_growth_rate_annual",
    "nev_penetration_monthly_drift",
]

#: Annual decision-time panel, 2019-2025 levels. Growth observations
#: are 2020-2025 (n = 6). Every series is a published total, one
#: caliber per series, all through 2025-12-31.
#:
#: - retail_10k: CPCA narrow passenger-car retail, 10k vehicles.
#:   2019-2022 from the CPCA series as charted by Zhongtai Securities
#:   (2024 strategy: 2019: 2,069; 2021: 2,016; 2022: 2,055);
#:   2020: 1,929 (CPCA via Caixin/C Zhongtai); 2023: 2,170.3
#:   (CPCA); 2024: 2,289.4 (CPCA, +5.5%); 2025: 2,374.4 (CPCA,
#:   +3.8%). CPCA revises past years slightly; chart values are
#:   rounded to the nearest 10k.
#: - income_cny: NBS per-capita disposable income, national
#:   residents, CNY/year (Statistical Communiques 2019-2025).
#: - lpr_1y_yearend_pct: 1y LPR at year-end, % (PBOC-authorized
#:   monthly quotes via the National Interbank Funding Center).
#: - avg_price_cny10k: CPCA average passenger-car transaction price,
#:   CNY 10k (Cui Dongshu / CPCA price-band reports, final Jan-2026
#:   series: 15.1 / 16.2 / 16.5 / 17.3 / 18.3 / 18.4 / 17.0. A
#:   mid-2025 article quotes 2024 as 17.7 — a revision/vintage
#:   difference, noted, not used).
#: - nev_penetration_caam: CAAM total-caliber NEV share of total
#:   vehicle sales (2023: 31.6%, 2024: 40.9%, 2025: 47.9%).
ANNUAL_PANEL: list[dict[str, Any]] = [
    {
        "year": 2019,
        "retail_10k": 2069.0,
        "income_cny": 30733,
        "lpr_1y_yearend_pct": 4.15,
        "avg_price_cny10k": 15.1,
        "nev_penetration_caam": None,
    },
    {
        "year": 2020,
        "retail_10k": 1929.0,
        "income_cny": 32189,
        "lpr_1y_yearend_pct": 3.85,
        "avg_price_cny10k": 16.2,
        "nev_penetration_caam": None,
    },
    {
        "year": 2021,
        "retail_10k": 2016.0,
        "income_cny": 35128,
        "lpr_1y_yearend_pct": 3.80,
        "avg_price_cny10k": 16.5,
        "nev_penetration_caam": None,
    },
    {
        "year": 2022,
        "retail_10k": 2055.0,
        "income_cny": 36883,
        "lpr_1y_yearend_pct": 3.65,
        "avg_price_cny10k": 17.3,
        "nev_penetration_caam": None,
    },
    {
        "year": 2023,
        "retail_10k": 2170.3,
        "income_cny": 39218,
        "lpr_1y_yearend_pct": 3.45,
        "avg_price_cny10k": 18.3,
        "nev_penetration_caam": 0.316,
    },
    {
        "year": 2024,
        "retail_10k": 2289.4,
        "income_cny": 41314,
        "lpr_1y_yearend_pct": 3.10,
        "avg_price_cny10k": 18.4,
        "nev_penetration_caam": 0.409,
    },
    {
        "year": 2025,
        "retail_10k": 2374.4,
        "income_cny": 43377,
        "lpr_1y_yearend_pct": 3.00,
        "avg_price_cny10k": 17.0,
        "nev_penetration_caam": 0.479,
    },
]

#: 2025 monthly CAAM total-caliber NEV penetration anchors (cross-check
#: for the drift trend). July 48.7% (China Securities Journal, CAAM
#: Jul-2025 release); October 51.6% (Shanghai Securities News, CAAM
#: Oct-2025 release — first month the total-caliber monthly rate
#: passed 50%); December 52.3% (synthesis A1). July->December is a
#: seasonal upswing (year-end rush), so this cross-check is biased
#: upward and is used as a bound, not as the estimate.
NEV_MONTHLY_ANCHORS_2025: dict[str, float] = {
    "2025-07": 0.487,
    "2025-10": 0.516,
    "2025-12": 0.523,
}

#: Minimum trend R^2 for adopting the NEV drift, and the maximum
#: distance (rate points/month) allowed between the trend value and
#: either cross-check.
NEV_TREND_MIN_R2 = 0.9
NEV_CROSSCHECK_TOLERANCE = 0.002


def _growth_rates(levels: list[float]) -> list[float]:
    """Year-on-year fractional growth rates of a level series."""

    return [levels[i] / levels[i - 1] - 1.0 for i in range(1, len(levels))]


def _ols_trend(xs: list[float], ys: list[float]) -> dict[str, float]:
    """OLS line through (xs, ys): slope, intercept, R^2."""

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx if sxx > 0 else 0.0
    intercept = mean_y - slope * mean_x
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"slope": slope, "intercept": intercept, "r2": r2}


def _mean_baseline_loo_rmse(target: list[float]) -> float:
    """LOO RMSE of "predict the leave-one-out mean" (the mean gate).

    Each observation is predicted by the mean of the others, so the
    number is an honest out-of-sample baseline for any fit on the
    same target: a fit that cannot beat it adds no predictive value.
    """

    n = len(target)
    squared: list[float] = []
    for i in range(n):
        others = [target[j] for j in range(n) if j != i]
        mean_others = sum(others) / len(others)
        squared.append((target[i] - mean_others) ** 2)
    return math.sqrt(sum(squared) / n)


def _income_annual_factor(g: float) -> float:
    """Annual retail log-effect per unit income sensitivity.

    With annual income growth ``g``, the income index in month ``t``
    is ``(1 + g/12)**t``; the retail driver adds
    ``income_sensitivity * (index - 1)`` to monthly log-growth each
    month. Summing over 12 months and dividing by ``g`` gives the
    factor converting the annual income elasticity ``beta`` (d retail
    growth / d income growth) to the monthly coefficient
    ``beta / factor``. ~6.6 at g = 5%.
    """

    return sum((1.0 + g / 12.0) ** t - 1.0 for t in range(1, 13)) / g


def _lpr_annual_factor() -> float:
    """Annual retail effect per unit LPR sensitivity, per pp of LPR.

    A persistent 1pp LPR cut moves ``lpr_proxy`` (LPR / 3.85%) by
    ``-1/3.85``; the driver adds ``lpr_sensitivity * 0.2597`` to
    monthly growth for 12 months.
    """

    return 12.0 / LPR_PROXY_BASELINE_PCT


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def calibrate_transmission_coefficients(
    *,
    ridge_strength: float = DEFAULT_RIDGE_STRENGTH,
    bootstrap_draws: int = DEFAULT_BOOTSTRAP_DRAWS,
    seed: int = DEFAULT_CALIBRATION_SEED,
) -> dict[str, Any]:
    """Fit the transmission calibration from the decision-time panel.

    Returns a JSON-shaped report: per-coefficient records with the
    prior, the adopted value, the adoption status and reason, the
    fit numbers, both gates, and the sources. Deterministic given
    the arguments (seeded bootstrap); pure (no I/O).
    """

    if not math.isfinite(ridge_strength) or ridge_strength < 0:
        raise ValueError(f"ridge_strength must be finite and >= 0; got {ridge_strength}.")
    panel = ANNUAL_PANEL
    years = [row["year"] for row in panel]
    if max(years) > 2025:
        raise ValueError("Transmission panel must end at the 2025-12-31 cutoff.")
    growth_years = years[1:]
    retail_g = _growth_rates([float(row["retail_10k"]) for row in panel])
    income_g = _growth_rates([float(row["income_cny"]) for row in panel])
    d_lpr = [
        float(panel[i]["lpr_1y_yearend_pct"]) - float(panel[i - 1]["lpr_1y_yearend_pct"])
        for i in range(1, len(panel))
    ]
    price_g = _growth_rates([float(row["avg_price_cny10k"]) for row in panel])

    coefficients: dict[str, Any] = {}

    # --- NEV penetration drift: OLS trend on annual CAAM rates -------
    nev_rows = [row for row in panel if row["nev_penetration_caam"] is not None]
    nev_years = [row["year"] for row in nev_rows]
    nev_rates_pp = [float(row["nev_penetration_caam"]) * 100.0 for row in nev_rows]
    trend = _ols_trend([float(year - nev_years[0]) for year in nev_years], nev_rates_pp)
    drift_trend = trend["slope"] / 100.0 / 12.0
    drift_2025_only = (nev_rates_pp[-1] - nev_rates_pp[-2]) / 100.0 / 12.0
    anchor_months = sorted(NEV_MONTHLY_ANCHORS_2025)
    anchor_first = NEV_MONTHLY_ANCHORS_2025[anchor_months[0]]
    anchor_last = NEV_MONTHLY_ANCHORS_2025[anchor_months[-1]]
    # July -> December is 5 months.
    drift_monthly_anchors = (anchor_last - anchor_first) / 5.0
    # Logistic cross-check: logit slope per segment, instantaneous
    # drift k * p * (1 - p) at the current penetration.
    logits = [_logit(p) for p in [float(r["nev_penetration_caam"]) for r in nev_rows]]
    logit_slopes = [
        (logits[i] - logits[i - 1]) / (nev_years[i] - nev_years[i - 1])
        for i in range(1, len(logits))
    ]
    p_now = float(nev_rows[-1]["nev_penetration_caam"])
    logistic_drifts = [slope * p_now * (1.0 - p_now) / 12.0 for slope in logit_slopes]
    drift_adopted = round(drift_trend, 4)
    drift_checks_ok = (
        trend["r2"] >= NEV_TREND_MIN_R2
        and abs(drift_2025_only - drift_trend) <= NEV_CROSSCHECK_TOLERANCE
        and abs(drift_monthly_anchors - drift_trend) <= NEV_CROSSCHECK_TOLERANCE
    )
    coefficients["nev_penetration_monthly_drift"] = {
        "coefficient": "nev_penetration_monthly_drift",
        "prior": PLACEHOLDERS["nev_penetration_monthly_drift"],
        "adopted_value": drift_adopted
        if drift_checks_ok
        else PLACEHOLDERS["nev_penetration_monthly_drift"],
        "status": "adopted" if drift_checks_ok else "kept_prior",
        "reason": (
            "ols_trend_r2_ge_0.9_and_crosschecks_within_0.002"
            if drift_checks_ok
            else "trend_or_crosscheck_failed"
        ),
        "method": (
            "OLS trend on CAAM total-caliber annual NEV penetration "
            f"{nev_years[0]}-{nev_years[-1]} "
            f"({', '.join(f'{v:.1f}%' for v in nev_rates_pp)}); "
            "slope in pp/year / 12 = drift per month"
        ),
        "window": f"{nev_years[0]}-{nev_years[-1]}",
        "n_annual_points": len(nev_rows),
        "trend_slope_pp_per_year": trend["slope"],
        "trend_r2": trend["r2"],
        "trend_drift_per_month": drift_trend,
        "drift_2025_only_per_month": drift_2025_only,
        "drift_monthly_anchors_per_month": drift_monthly_anchors,
        "logistic_drifts_per_month": logistic_drifts,
        "sources": [
            (
                "CAAM total-caliber NEV penetration (synthesis B1/A1): "
                "31.6% (2023), 40.9% (2024), 47.9% (2025)"
            ),
            (
                "CAAM monthly anchors 2025: Jul 48.7% (China Securities "
                "Journal), Oct 51.6% (Shanghai Securities News), Dec 52.3% "
                "(synthesis A1)"
            ),
        ],
        "notes": (
            "The placeholder 0.002/mo implies +2.4pp/year; the observed "
            "2023-2025 trend is +8.15pp/year. Constant drift overstates "
            "late-horizon penetration as the S-curve saturates — the "
            "logistic cross-check gives "
            f"{min(logistic_drifts):.4f}/mo from the most recent "
            f"(2024-2025) segment and {max(logistic_drifts):.4f}/mo from "
            "the 2023-2024 segment (the S-curve is decelerating, so the "
            "recent segment is the forward-looking one); the adopted "
            "0.0068 sits between the 2025-only linear drift (0.0058) "
            "and the monthly-anchor slope (0.0072, seasonally biased "
            "upward). The 1.0 cap bounds the path."
        ),
    }

    # --- Income growth rate: ridge location fit ----------------------
    income_growth_fitted = ridge_location_fit(
        income_g, PLACEHOLDERS["income_growth_rate_annual"], ridge_strength
    )
    income_growth_loo = leave_one_out_rmse(
        [[1.0] for _ in income_g],
        income_g,
        [PLACEHOLDERS["income_growth_rate_annual"]],
        ridge_strength,
        clip_nonnegative=False,
    )
    income_growth_prior_rmse = prior_only_rmse(
        [[1.0] for _ in income_g],
        income_g,
        [PLACEHOLDERS["income_growth_rate_annual"]],
    )
    income_gate = income_growth_loo is not None and income_growth_loo <= income_growth_prior_rmse
    coefficients["income_growth_rate_annual"] = {
        "coefficient": "income_growth_rate_annual",
        "prior": PLACEHOLDERS["income_growth_rate_annual"],
        "adopted_value": round(income_growth_fitted, 4)
        if income_gate
        else PLACEHOLDERS["income_growth_rate_annual"],
        "status": "adopted" if income_gate else "kept_prior",
        "reason": "ridge_location_fit_prior_gate" if income_gate else "prior_gate_failed",
        "method": (
            "Ridge-shrunk location fit (lambda = ridge_strength) of "
            "annual nominal per-capita disposable-income growth toward "
            "the 0.05 NBS-2025 anchor prior"
        ),
        "window": f"{growth_years[0]}-{growth_years[-1]}",
        "n": len(income_g),
        "observed_growth_rates": income_g,
        "observed_mean": sum(income_g) / len(income_g),
        "fitted_value": income_growth_fitted,
        "loo_rmse": income_growth_loo,
        "prior_only_rmse": income_growth_prior_rmse,
        "prior_gate_passed": income_gate,
        "sources": [
            (
                "NBS per-capita disposable income, national residents "
                "(Statistical Communiques): CNY 30,733 (2019) / 32,189 "
                "(2020) / 35,128 (2021) / 36,883 (2022) / 39,218 (2023) / "
                "41,314 (2024) / 43,377 (2025); nominal growth 4.7% / 9.1% / "
                "5.0% / 6.3% / 5.3% / 5.0%"
            ),
        ],
        "notes": (
            "Nominal growth is used (the template's income anchor is "
            "nominal +5.0% in 2025; real growth was also +5.0% that year "
            "as CPI was ~flat). The 2021 +9.1% is a COVID-rebound "
            "artifact; the ridge prior pulls the mean 5.92% back toward "
            "the 5.0% anchor. The prior gate passes NARROWLY (LOO "
            "1.74pp vs prior-only 1.78pp) — the value is a shrunk "
            "central estimate, not a precise one."
        ),
    }

    # --- Income / LPR / price sensitivities: joint ridge fit ---------
    # Percentage-point units: features ~5pp, so the default ridge
    # strength (5.0) is on the same scale as X'X (unlike fractional
    # units, where it would swamp the data entirely).
    target_pp = [value * 100.0 for value in retail_g]
    features_pp = [
        [income * 100.0, dlpr, price * 100.0]
        for income, dlpr, price in zip(income_g, d_lpr, price_g)
    ]
    income_factor = _income_annual_factor(
        coefficients["income_growth_rate_annual"]["adopted_value"]
    )
    lpr_factor = _lpr_annual_factor()
    price_factor = 12.0
    priors_beta = [
        PLACEHOLDERS["income_sensitivity"] * _income_annual_factor(0.05),
        -PLACEHOLDERS["lpr_sensitivity"] * lpr_factor,
        -PLACEHOLDERS["price_sensitivity"] * price_factor,
    ]
    joint = fit_centered_ridge_to_prior(
        features_pp,
        target_pp,
        priors_beta,
        ridge_strength,
        clip_nonnegative=False,
    )
    joint_loo = leave_one_out_rmse(
        features_pp,
        target_pp,
        priors_beta,
        ridge_strength,
        clip_nonnegative=False,
        center_target=True,
    )
    joint_prior_rmse = prior_only_rmse(features_pp, target_pp, priors_beta)
    joint_mean_rmse = _mean_baseline_loo_rmse(target_pp)
    joint_intervals = bootstrap_coefficient_intervals(
        features_pp,
        target_pp,
        priors_beta,
        ridge_strength,
        draws=bootstrap_draws,
        seed=seed,
        level=0.95,
        clip_nonnegative=False,
        center_target=True,
    )
    prior_gate = joint_loo is not None and joint_loo <= joint_prior_rmse
    mean_gate = joint_loo is not None and joint_loo <= joint_mean_rmse
    adopted_joint = prior_gate and mean_gate
    joint_slopes = joint["coefficients"]
    mapped = [
        joint_slopes[0] / income_factor,
        -joint_slopes[1] / lpr_factor,
        -joint_slopes[2] / price_factor,
    ]
    # Bivariate OLS diagnostics, with and without the 2020 COVID year.
    drivers = {
        "income_sensitivity": [row[0] for row in features_pp],
        "lpr_sensitivity": [row[1] for row in features_pp],
        "price_sensitivity": [row[2] for row in features_pp],
    }
    bivariate: dict[str, Any] = {}
    for key, xs in drivers.items():
        full = _ols_trend(xs, target_pp)
        excl = _ols_trend(xs[1:], target_pp[1:])
        bivariate[key] = {
            "ols_slope_all_years": full["slope"],
            "ols_r2_all_years": full["r2"],
            "ols_slope_excl_2020": excl["slope"],
            "ols_r2_excl_2020": excl["r2"],
        }
    joint_record_common: dict[str, Any] = {
        "method": (
            "Joint centered ridge-to-prior fit of annual retail growth "
            "(pp) on income growth (pp), year-end 1y-LPR change (pp), "
            "and average-price growth (pp), 2020-2025, n=6; priors are "
            "the placeholder-implied regression slopes; intercept is "
            "unpenalized (centered fit)"
        ),
        "window": f"{growth_years[0]}-{growth_years[-1]}",
        "n": len(target_pp),
        "joint_intercept_pp": joint["intercept"],
        "joint_loo_rmse_pp": joint_loo,
        "joint_prior_only_rmse_pp": joint_prior_rmse,
        "joint_mean_baseline_loo_rmse_pp": joint_mean_rmse,
        "prior_gate_passed": prior_gate,
        "mean_gate_passed": mean_gate,
        "ridge_strength": ridge_strength,
        "bootstrap_draws": bootstrap_draws,
        "seed": seed,
        "sources": [
            (
                "CPCA narrow passenger-car retail (see panel notes): "
                "2,069 / 1,929 / 2,016 / 2,055 / 2,170.3 / 2,289.4 / "
                "2,374.4 (10k, 2019-2025)"
            ),
            ("NBS per-capita disposable income (see income-growth record)"),
            (
                "1y LPR year-end (PBOC): 4.15% / 3.85% / 3.80% / 3.65% / "
                "3.45% / 3.10% / 3.00% (2019-2025)"
            ),
            (
                "CPCA average transaction price (Cui Dongshu): CNY 15.1 / "
                "16.2 / 16.5 / 17.3 / 18.3 / 18.4 / 17.0 (10k, 2019-2025)"
            ),
        ],
    }
    elasticity_specs = [
        {
            "coefficient": "income_sensitivity",
            "prior": PLACEHOLDERS["income_sensitivity"],
            "slope_index": 0,
            "mapped": mapped[0],
            "mapping": (
                f"income_sensitivity = beta_income / "
                f"{income_factor:.2f} (annual factor at adopted "
                f"income growth "
                f"{coefficients['income_growth_rate_annual']['adopted_value']:.3f})"
            ),
            "notes": (
                "Slope unstable across windows (bivariate OLS "
                f"{bivariate['income_sensitivity']['ols_slope_all_years']:.2f} "
                "with 2020, "
                f"{bivariate['income_sensitivity']['ols_slope_excl_2020']:.2f} "
                "without): 2020 lockdowns cut retail while income still "
                "grew, and 2021-2025 retail growth is dominated by "
                "subsidies and NEV mix, not income. The joint 95% CI "
                f"[{joint_intervals[0]['low']:.2f}, "
                f"{joint_intervals[0]['high']:.2f}] spans zero, and the "
                "joint fit cannot beat the mean baseline, so no point "
                "estimate is adopted."
            ),
        },
        {
            "coefficient": "lpr_sensitivity",
            "prior": PLACEHOLDERS["lpr_sensitivity"],
            "slope_index": 1,
            "mapped": mapped[1],
            "mapping": (
                f"lpr_sensitivity = -beta_lpr / {lpr_factor:.4f} "
                f"(12 / {LPR_PROXY_BASELINE_PCT} baseline)"
            ),
            "notes": (
                "No stability: bivariate OLS slope is "
                f"{bivariate['lpr_sensitivity']['ols_slope_all_years']:.2f} "
                "(wrong-signed: the largest cut coincided with the "
                "COVID collapse) with 2020 but "
                f"{bivariate['lpr_sensitivity']['ols_slope_excl_2020']:.2f} "
                "without it — an implausibly large -6pp retail response "
                "per pp of cut, which is 2024's subsidy-driven growth "
                "loading onto the LPR cut. All LPR moves in-window are "
                "cuts, so identification rests on cut-size variation "
                "alone. The joint 95% CI "
                f"[{joint_intervals[1]['low']:.2f}, "
                f"{joint_intervals[1]['high']:.2f}] is right-signed but "
                "the joint fit cannot beat the mean baseline, so no "
                "point estimate is adopted."
            ),
        },
        {
            "coefficient": "price_sensitivity",
            "prior": PLACEHOLDERS["price_sensitivity"],
            "slope_index": 2,
            "mapped": mapped[2],
            "mapping": "price_sensitivity = -beta_price / 12.0",
            "notes": (
                "The data DOES bound this one: the joint-fit 95% CI for "
                "beta_price is "
                f"[{joint_intervals[2]['low']:.2f}, "
                f"{joint_intervals[2]['high']:.2f}], i.e. "
                "price_sensitivity in "
                f"[0, {max(0.0, -joint_intervals[2]['low'] / 12.0):.3f}] "
                "— the 0.20 placeholder sits above the bound. But the "
                "joint fit cannot beat the mean baseline, so no point "
                "estimate is adopted; the placeholder is retained and "
                "flagged as an upper-end sensitivity input. Average "
                "transaction price is mix-driven (NEV share, premium "
                "collapse), not a clean price level — a quarterly panel "
                "with a mix-adjusted price index is the follow-up."
            ),
        },
    ]
    for spec in elasticity_specs:
        idx = spec["slope_index"]
        interval = joint_intervals[idx]
        record: dict[str, Any] = {
            "coefficient": spec["coefficient"],
            "prior": spec["prior"],
            "adopted_value": (round(spec["mapped"], 4) if adopted_joint else spec["prior"]),
            "status": "adopted" if adopted_joint else "kept_prior",
            "reason": ("joint_fit_both_gates" if adopted_joint else "quality_gate_mean_baseline"),
            "mapping": spec["mapping"],
            "joint_slope_pp_per_pp": joint_slopes[idx],
            "joint_slope_bootstrap_95pct": {
                "low": interval["low"],
                "high": interval["high"],
                "estimate": interval["estimate"],
            },
            "mapped_fitted_value": spec["mapped"],
            "bivariate_diagnostics": bivariate[spec["coefficient"]],
            "sources": joint_record_common["sources"],
            "notes": spec["notes"],
        }
        record.update(
            {key: value for key, value in joint_record_common.items() if key not in record}
        )
        coefficients[spec["coefficient"]] = record

    # --- Not estimable from the verified annual data ------------------
    coefficients["confidence_sensitivity"] = {
        "coefficient": "confidence_sensitivity",
        "prior": PLACEHOLDERS["confidence_sensitivity"],
        "adopted_value": PLACEHOLDERS["confidence_sensitivity"],
        "status": "kept_prior",
        "reason": "unidentified_no_verifiable_series",
        "method": "not fitted — no usable series",
        "window": None,
        "n": 0,
        "sources": [
            (
                "PBOC quarterly城镇储户问卷调查 (consumption willingness, "
                "'more consumption' share): scattered verified points "
                "only — 2021Q2 25.1%, 2023Q1 23.2%, 2024Q4 24.9% "
                "(synthesis B4 cites 24.6% for 2024Q4; 0.3pp vintage "
                "difference). No full quarterly series verifiable from "
                "public snippets; the series moves in a narrow 23-25% "
                "band."
            ),
        ],
        "notes": (
            "The synthesis (B4/A9) already flags 'no unified public "
            "series' for confidence. Follow-up: collect the full "
            "quarterly PBOC willingness series from the quarterly "
            "survey reports and fit a quarterly panel (retail growth "
            "on willingness changes) — the annual panel cannot "
            "identify a quarterly-moving proxy."
        ),
    }
    coefficients["material_passthrough"] = {
        "coefficient": "material_passthrough",
        "prior": PLACEHOLDERS["material_passthrough"],
        "adopted_value": PLACEHOLDERS["material_passthrough"],
        "status": "kept_prior",
        "reason": "unidentified_one_clean_observation_wrong_sign",
        "method": "not fitted — one clean annual pair only",
        "window": "2023-2024",
        "n": 1,
        "sources": [
            (
                "Mysteel battery-grade lithium carbonate annual average: "
                "2023 ~CNY 25.4/ton10k (derived: 2024 avg 9.03, -64.51% "
                "vs 2023), 2024 CNY 9.03-9.09/ton10k; 2022 peak ~56 "
                "(Nov 2022); 2021 start 5.7 / end 28.5. No verified "
                "annual average for 2021/2022/2025."
            ),
            ("CPCA average transaction price 2023 CNY 18.3/10k, 2024 CNY 18.4/10k (+0.5%)."),
        ],
        "notes": (
            "The one clean pair is wrong-signed for passthrough: "
            "lithium -64.5% while the average transaction price ROSE "
            "0.5% — mix shift (NEV share, premium collapse) dominates "
            "the annual average price. The template's "
            "material_cost_index is a lithium + steel/aluminum "
            "COMPOSITE whose weights are undefined, so even a "
            "lithium-only slope would not map to the coefficient. "
            "Follow-up: monthly Mysteel lithium + steel/aluminum "
            "series, composite weights, monthly price regression."
        ),
    }
    coefficients["margin_material_sensitivity"] = {
        "coefficient": "margin_material_sensitivity",
        "prior": PLACEHOLDERS["margin_material_sensitivity"],
        "adopted_value": PLACEHOLDERS["margin_material_sensitivity"],
        "status": "kept_prior",
        "reason": "unidentified_wrong_sign_episode",
        "method": "not fitted — mechanism confounded",
        "window": "2023-2025",
        "n": 3,
        "sources": [
            (
                "Desay SV overall gross margin (listed benchmark, "
                "exchange filings): 20.0% / 19.9% / 19.1% (2023-2025)."
            ),
            (
                "Mysteel lithium carbonate: collapsed 2023-2024 (see "
                "material_passthrough record) — unpassed material "
                "pressure was NEGATIVE over the episode."
            ),
        ],
        "notes": (
            "Margins FELL 0.9pp while material costs collapsed, i.e. "
            "while the model's margin driver would EXPAND margins. "
            "The decline was driven by the price war / annual-cut "
            "channel, which the margin driver does not model — so "
            "this episode cannot identify the material-to-margin "
            "coefficient (wrong sign, confounded). Follow-up: add "
            "the annual-cut channel to the margin driver first, "
            "then calibrate on a margin-vs-material panel."
        ),
    }

    adopted_values = {
        cid: coefficients[cid]["adopted_value"] for cid in TRANSMISSION_COEFFICIENT_IDS
    }
    return {
        "decision_time": DECISION_TIME,
        "data_cutoff": DATA_CUTOFF,
        "ridge_strength": ridge_strength,
        "seed": seed,
        "bootstrap_draws": bootstrap_draws,
        "n_growth_observations": len(growth_years),
        "growth_years": growth_years,
        "coefficients": coefficients,
        "adopted_values": adopted_values,
        "adopted": [
            cid for cid in TRANSMISSION_COEFFICIENT_IDS if coefficients[cid]["status"] == "adopted"
        ],
        "kept_prior": [
            cid
            for cid in TRANSMISSION_COEFFICIENT_IDS
            if coefficients[cid]["status"] == "kept_prior"
        ],
    }


#: The calibration report, computed once at import (deterministic,
#: seeded, pure — no I/O). The builtin automotive template reads its
#: values from here, so the template and the fit cannot drift apart.
CALIBRATION_REPORT: dict[str, Any] = calibrate_transmission_coefficients()

#: Template values for the eight transmission coefficients: the
#: adopted (fitted) value where the gates passed, the prior
#: placeholder where they did not. Kept-prior entries equal the old
#: placeholders exactly — no behavior change, only provenance.
ADOPTED_VALUES: dict[str, float] = dict(CALIBRATION_REPORT["adopted_values"])


__all__ = [
    "ADOPTED_VALUES",
    "ANNUAL_PANEL",
    "CALIBRATION_REPORT",
    "DATA_CUTOFF",
    "DECISION_TIME",
    "LPR_PROXY_BASELINE_PCT",
    "NEV_MONTHLY_ANCHORS_2025",
    "PLACEHOLDERS",
    "TRANSMISSION_COEFFICIENT_IDS",
    "calibrate_transmission_coefficients",
]
