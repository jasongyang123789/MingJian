# Calibration v3 — transmission elasticity calibration

- **Branch:** `fix/calibration-v3` (from `83bb09f`, tip of `fix/backtest-improvements`)
- **Tip:** `1efceff` (report) on `d585224` (code)
- **Status:** report first — NOT merged, NOT pushed. No hub work.
- **Decision time:** 2026-01-01; **data cutoff:** 2025-12-31 (hindsight firewall).

## What changed

New module `src/planagent/services/calibration/transmission.py` — the
calibration system now fits the automotive transmission coefficients
from embedded decision-time public series (no I/O, deterministic,
seeded bootstrap), reusing the Sprint 5/10 ridge-to-prior estimator,
bootstrap intervals, and LOO gates. The builtin automotive template
reads `ADOPTED_VALUES` from this module: the calibrated values ARE
the template values, not a side table.

### Adopted (2 of 8)

| Coefficient | Before | After | Method | Sources |
|---|---|---|---|---|
| `nev_penetration_monthly_drift` | 0.002 | **0.0068**/mo | OLS trend on CAAM total-caliber annual NEV penetration 2023–2025 (31.6% → 40.9% → 47.9%), slope +8.15pp/yr, R²=0.993; cross-checks 2025-only 0.0058, 2025 Jul–Dec monthly anchors 0.0072, logistic recent segment 0.0059 | CAAM via synthesis B1/A1; CAAM Jul/Oct 2025 releases (China Securities Journal / Shanghai Securities News) |
| `income_growth_rate_annual` | 0.05 | **0.055**/yr | Ridge location fit (λ=5) toward the 0.05 prior on NBS nominal per-capita disposable-income growth 2020–2025 (mean 5.92%, fitted 5.50%) | NBS Statistical Communiques 2019–2025 (CNY 30,733 → 43,377) |

The old drift implied +2.4pp/year against an observed +8.15pp/year
trend — the placeholder was ~3.4× too slow. The old income growth
was the single-year 2025 value; the calibrated value is the shrunk
2020–2025 mean. (The income-growth prior gate passes narrowly:
LOO 1.74pp vs prior-only 1.78pp — the report says so.)

Also defined, because the LPR mapping needs it: `lpr_proxy` = 1y LPR
/ 3.85% (2020–2021 modal 1y LPR, the pre-easing level). The pack
previously left the baseline undefined.

### Kept as labeled placeholders (6 of 8) — with the failed attempt recorded

The joint centered ridge-to-prior fit of annual retail growth on
income growth, year-end 1y-LPR change, and average-price growth
(2020–2025, n=6, pp units) passes the codebase's prior gate
(LOO 7.64pp vs prior-only 11.88pp) but FAILS the mean gate
(LOO 7.64pp vs leave-one-out mean baseline 5.14pp). A fit that cannot
beat "predict the mean" is noise, so no point estimate is adopted:

| Coefficient | Placeholder | What the fit would have given | Why it stays |
|---|---|---|---|
| `income_sensitivity` | 0.05 | 0.153 (β=1.01) | Slope unstable across windows (bivariate OLS 1.18 with 2020, 0.27 without); joint 95% CI [-0.12, 2.25] spans zero |
| `lpr_sensitivity` | 0.10 | 0.112 (β=-0.35) | Bivariate OLS flips sign across windows (+13.08 with 2020, -5.97 without); all in-window moves are cuts |
| `price_sensitivity` | 0.20 | 0.039 (β=-0.46) | Joint 95% CI bounds it at [0, 0.159] — the 0.20 placeholder sits ABOVE the bound; retained only as an upper-end sensitivity input |
| `confidence_sensitivity` | 0.05 | — (not fitted) | No verifiable quarterly PBOC willingness series (scattered points only: 2021Q2 25.1%, 2023Q1 23.2%, 2024Q4 24.9%); narrow 23–25% band |
| `material_passthrough` | 0.30 | — (not fitted) | One clean annual pair only (2023→2024: lithium -64.5%, avg price +0.5%) — wrong sign, mix-shift dominated; composite weights undefined |
| `margin_material_sensitivity` | 0.02 | — (not fitted) | Wrong-sign episode: Desay margins fell 20% → 19.1% (2023–25) while lithium collapsed (unpassed pressure negative); margin driver lacks the annual-cut channel |

The kept placeholders keep their `assumption:pending-calibration`
label; their `evidence_ref` now cites the v3 attempt and the
report. The full per-coefficient record (slopes, intercepts,
bootstrap CIs, both gates, bivariate diagnostics, sources, notes)
is `CALIBRATION_REPORT` in the module.

### Model-unit mappings (documented in the module)

- income: `income_sensitivity = β_income / 6.61` (exact annual
  factor at g=5.5%: Σ((1+g/12)^t − 1)/g over 12 months).
- price: `price_sensitivity = −β_price / 12`.
- LPR: `lpr_sensitivity = −β_lpr / (12/3.85)`.

## Verification

- Targeted: `tests/test_calibration_transmission.py` +
  `test_automotive_pack.py` + `test_automotive_phase2_api.py` —
  **38 passed**.
- Proof the calibrated values are USED (not just stored):
  - Driver level: 12 ticks of the real `evaluate_tick_drivers`
    from pack defaults give `income_index` 1.0564
    (=(1+0.055/12)^12) and `nev_penetration` 0.5606
    (=0.479+12×0.0068) exactly.
  - Mapping level: with confidence/LPR/price at baseline and no
    pull-forward drag, 12 ticks of the real income + retail drivers
    reproduce the predicted annual log-effect
    (0.05 × 6.61 × 0.055) within 2% — the mapping factor is verified
    against the driver code, not just derived.
  - API level: the Phase 2 trajectory test asserts the 6-tick
    penetration endpoint `0.479 + 6×0.0068` through the real engine.
- Full suite: **2106 passed, 0 failed, in 649.80s** (single-process,
  `pytest -q`, run 2026-11-19 09:08–09:19 UTC under
  `full-run-lock.sh`, TMPDIR `/dev/shm/pytest-tmp-calibration-v3`,
  ≥750M gate passed, peak TMPDIR 1.7M). Count: 2095 base tests on
  83bb09f + 11 new tests in `tests/test_calibration_transmission.py`
  (collect-only verified). Note on the wait: the post-restart
  stampede of parallel track suites meant the first attempt was
  killed by a runtime restart after ~35 min queued, the second
  timed out after 3600s, and the third (`--wait 7200`) acquired
  the lock and ran green — no code change was needed at any point.

## What remains limited

- **Quarterly panel is the real fix for income/LPR/price.** The
  annual panel (n=6) cannot identify them: every year 2020–2025
  carries a distortion (COVID, subsidies, mix shift). A quarterly
  panel (n≈24: CPCA quarterly retail, NBS quarterly income,
  quarterly-average LPR, mix-adjusted price) is the documented
  follow-up; the module's estimators and gates are ready for it.
- **Income-growth gate is narrow** (see above); the value is a
  shrunk central estimate, not a precise one.
- **Constant NEV drift overstates late-horizon penetration** as the
  S-curve saturates (logistic recent segment: 0.0059/mo). The 1.0
  cap bounds the path; a logistic drift (drift as a function of
  level) is a follow-up, not in this track.
- **Formula literals not calibrated:** pull-forward decay/drag,
  inventory/production responses, price partial-adjustment speed,
  generation ramp remain assumption literals (out of scope — the
  template variables were the track's scope).
- **2026 data not used** by design (hindsight firewall for a
  2026-01-01 decision). Recalibrate when the decision time moves.
- **No new API endpoint.** Transmission coefficients are fit from
  external historical series, not from run outcomes (fitting them
  to run outcomes would be circular); the existing policy/rule
  fit endpoints are the wrong shape for this. A read endpoint
  exposing `CALIBRATION_REPORT` is a possible follow-up.
- **Ruff:** base already carries 12 ISC004 findings in these
  directories; my files are clean (`ruff check` passes on all
  touched files; new files also `ruff format`-clean).
