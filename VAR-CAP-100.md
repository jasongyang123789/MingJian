# Variable cap 30 → 100 + promotion of two literal rates (Track A)

Branch: `strategy-engine/var-cap-100`, from `ccc3490` (tip of
`strategy-engine/sprint20-cockpit-seminar`, fix batch 2 merged).
Worktree: `~/workspace/mingjian-varcap` (own `.venv` + editable install;
`planagent.__file__` verified inside the worktree before any test ran).

Decision: Ho's 2026-11-17 ruling 5 — raise the variable cap from 30 to 100
(the Sprint 2 design pin) and promote the two literal rates the Phase 2
auto pack kept as literals to template variables. No `BACKLOG.md` change
(per track instructions). No merge, no push.

## 1. What changed

### 1.1 Cap: 30 → 100

- `src/planagent/services/variables/models.py`: `MAX_VARIABLES = 30` →
  `100`, with a comment recording the decision. Module and `VariableSet`
  docstrings updated from 1-30 to 1-100. The reference attribution is
  preserved honestly: the agilhaykal reference pins the cap at 30; the
  raise is Ho's decision, and the docstring says so.
- `src/planagent/services/variables/validator.py`: docstring only. Both
  enforcement gates (variable-set level, template level) already read
  `MAX_VARIABLES`, so the refusal paths and their messages render the new
  cap with no logic change. The `too_many_variables` issue kind is
  unchanged.
- `frontend-v2/src/components/cockpit/TemplateEditor.tsx`: the variable
  table heading "最多 30 个" → "最多 100 个". Verified by grep that no
  frontend enforcement logic exists (no length check anywhere in
  `frontend-v2/src`); the backend validator is the single enforcement
  point and this label is its only mirror.

### 1.2 Promoted rates (Phase 2 auto pack)

`src/planagent/simulation/domain_packs/automotive/template_spec.py`,
template 30 → 32 variables:

- `income_growth_rate_annual`: unit `rate/year`, fixed `0.05`,
  evidence_ref `NBS via synthesis B4` (per-capita disposable income
  nominal +5.0% in 2025 — the same anchor as `income_index`). Placed
  directly after `income_index`.
- `nev_penetration_monthly_drift`: unit `rate points/month`, fixed
  `0.002`, evidence_ref `assumption:pending-calibration` (synthesis C5:
  placeholder drift; no public monthly penetration-drift series exists).
  Placed directly after `nev_penetration`.

Both entries follow the Sprint 2 variable-table rules (unit +
`evidence_ref` mandatory, both asserted by the existing per-variable
loop test). Both are fixed-distribution, so they double as C4 scenario
lever handles per the file's header convention, and so promotion
preserves the exact Phase 2 numerics.

Driver swaps (expression trees only; descriptions updated to match):

- Income driver: `divide(0.05, 12)` →
  `divide({"ref": "income_growth_rate_annual"}, 12)`.
- Penetration driver: `add({"ref": "nev_penetration"}, 0.002)` →
  `add({"ref": "nev_penetration"}, {"ref": "nev_penetration_monthly_drift"})`.

The Phase 2 NOTE block about the 30-variable limit now records the
promotion instead. Mechanism: tick drivers evaluate over the run's
sampled + initial derived values overlaid with current state
(`evaluate_tick_drivers`), so a variable ref resolves exactly like the
existing `material_passthrough` precedent in the price driver. The two
rates are formula parameters, not state fields — like the 7 sensitivity
coefficients, they do not match pack state fields and are not applied to
the initial state.

### 1.3 Deliberately NOT changed

- `PHASE2-AUTO-PACK.md` §2.1: a historical record. It correctly states
  the cap raise was deferred as a design decision in Phase 2; this track
  is that decision's execution, recorded here rather than by rewriting
  the Phase 2 record.
- `BACKLOG.md`: untouched per track instructions.
- Other pack literals (price-driver speed 0.5, pull-forward decay 0.98,
  inventory/chip responses, generation-transition step 0.05): out of
  scope — only the two named rates were promoted.
- `MAX_FORMULAS` (40): untouched.

## 2. Tests changed / added

- `tests/unit/test_variable_validator.py`:
  - `test_empty_and_oversized_sets`: boundary moved to 100 accepted /
    101 refused, plus an exact-message assertion for the set-level
    refusal.
  - `test_validate_template_state_fields_and_policies` (template
    boundary): 100 accepted / 101 refused, plus an assertion that the
    template-level message appears among the issues (the set-level
    issue precedes it in the list).
  - Module docstring updated to 1-100.
- `tests/test_automotive_pack.py`:
  - `test_template_spec_counts_and_driver_flags`: 32 variables; the
    unbound (non-state-field) set grows from 7 to 9 with the two
    promoted rates; comment updated.
  - `test_builtin_automotive_template_validates`: 32 variables.
  - NEW `test_promoted_rate_variables_resolve_in_drivers`: asserts the
    two variables' units, fixed distributions (0.05 / 0.002), and
    evidence refs; asserts the two driver expression trees reference the
    new ids (and only the expected refs); samples the full template with
    `sample_variable_set` (seed 7) and asserts both sampled values;
    evaluates both drivers with `evaluate_tick_drivers` and asserts the
    outputs equal the old literal behavior exactly.
  - Module docstring counts corrected (24/8/5 was stale since Phase 2;
    now 32/16/13).

No live LLM anywhere in this track; all tests are fixture/deterministic.

## 3. Evidence (measured; every number from a named run)

All pytest runs use `env -u NO_PROXY -u no_proxy .venv/bin/python
-m pytest` in the worktree, per the track protocol.

### 3.1 Cap boundary + template tests (subsets, green)

- `tests/unit/test_variable_validator.py` +
  `tests/test_automotive_pack.py` + `tests/unit/test_formulas.py` +
  `tests/unit/test_sampler.py`: **57 passed**.
  - `test_empty_and_oversized_sets`: a 100-variable set is accepted; a
    101-variable set is refused with the exact message "A variable set
    holds at most 100 variables; got 101."
  - `test_validate_template_state_fields_and_policies`: a 100-variable
    template is accepted; a 101-variable template is refused with
    `too_many_variables` and the message "A template holds at most 100
    variables; got 101." among the issues.
  - `test_template_spec_counts_and_driver_flags`: 32 variables; the
    unbound (non-state-field) set is 9 ids including the two promoted
    rates.
  - `test_builtin_automotive_template_validates`: 32 variables; the
    builtin template validates.
  - NEW `test_promoted_rate_variables_resolve_in_drivers`: asserts the
    two variables' units (`rate/year`, `rate points/month`), fixed
    distributions (0.05, 0.002), and evidence refs (`NBS via synthesis
    B4`, `assumption:pending-calibration`); asserts the two driver
    expression trees reference exactly `{income_index,
    income_growth_rate_annual}` and `{nev_penetration,
    nev_penetration_monthly_drift}`; samples the full template with
    `sample_variable_set` (seed 7) and asserts both sampled values;
    evaluates both drivers with `evaluate_tick_drivers` and asserts the
    outputs `{"income_index": 1.0042, "nev_penetration": 0.481}` —
    identical to the old literal behavior.
- `tests/test_automotive_api.py`: **13 passed** (99s).
- `tests/unit/test_seminar_locks.py` in isolation: **10 passed** (run
  to prove that file's full-suite failures were environmental; see
  §3.3).

### 3.2 E2E smoke

- `.venv/bin/python docs/sprint0/smoke_e2e.py` → **SMOKE: PASS**
  (exit 0). `docs/sprint0/smoke-evidence.json` was reverted afterward
  and is not part of the commit.

### 3.3 Full suite (the gate — NOT green; environmental, classified)

- Baseline at `ccc3490` (per `FIX-BATCH-2.md`): 1840 passed / 0
  failed. This branch adds exactly 1 test, so 1841 are collected
  (verified by `--collect-only`: 1205 in `tests/unit/` + 629 in
  `tests/test_*.py` + 7 in `tests/stress_test.py`).
- Attempt 3 (preflight-gated, full-suite lock protocol,
  `TMPDIR=/dev/shm/pytest-tmp-varcap`, 670.16s): **268 failed / 1573
  passed / 1841**. Log:
  `~/workspace/verification/varcap-full-suite-rerun.log` (93,017
  lines). Classification of all 267 failure sections: **262 ×
  `sqlite3.OperationalError: disk I/O error`** (most failing at
  `CREATE TABLE auth_users` — DB setup itself failed) + **5 ×
  `PermissionError: [Errno 1] Operation not permitted`** (all
  `test_yaml_scale_by*` in `tests/test_rule_effect_scaling.py`).
  **0 `AssertionError` lines** exist in the entire log, and no failure
  section mentions the cap, `MAX_VARIABLES`, or
  `too_many_variables`. **0 failures** in
  `tests/unit/test_variable_validator.py`,
  `tests/test_automotive_pack.py`, `tests/test_automotive_api.py`,
  `tests/unit/test_formulas.py`, or `tests/unit/test_sampler.py`. The
  18 failures whose names touch variables/formulas/templates
  (`test_variable_templates_api.py` 12, `test_robustness_api.py` 5,
  `test_distributions_api.py` 1) are all inside the disk-I/O sections.
  Failures span 29 files, all DB-backed API/service tests, and cluster
  in a contiguous mid-run band of the progress output — consistent
  with a denial window reopening mid-run (see §4).
- Attempt 1: 289 failed / 1552 passed — invalidated: `/dev/shm`
  filled to 100% (794M; this track 263M + hud 404M + optc 128M).
- Attempt 2: 425 failed / 1416 passed — invalidated: disk-backed
  `TMPDIR` deviation (worse: 403× disk I/O + 10× EPERM + 2
  consequential alembic `AssertionError` lines; attempt 3's 0
  `AssertionError` lines confirm those were consequential of DB setup
  failure, not code).
- Preflight history: the first gated cycle exhausted 20/20 probes
  (exit 4, lock released); the second cycle passed on check 53 after
  52 consecutive failures (~26 min of sustained denial). Each probe is
  mkdtemp + SQLite create/insert/commit/select under the run's TMPDIR.
- Failed-files re-run (the 29 affected files): BLOCKED. The `/dev/shm`
  space gate (≥400M free required) saw 0–4KB free across 10 checks and
  exited 5 with the lock released; stale sibling TMPDIRs (polish
  485M, optc 252M, retry 58M) were deliberately left untouched. It was
  not attempted a second time.

### 3.4 Frontend

- Baseline (pristine `ccc3490`, before the label change): **268
  passed / 1 failed (269)** — the failure is `src/pages/Charts.test.tsx
  > renders ensemble histograms and all robustness charts for a run`,
  a pre-existing load-sensitive flake, 23/23 in isolation.
- After the label change: **268 passed / 1 failed (269)** — the
  identical single failure (same test, 5613ms under CPU contention);
  `src/pages/Charts.test.tsx` in isolation: **23 passed (23)**.
- `npx tsc -b` exit 0; `npx eslint
  src/components/cockpit/TemplateEditor.tsx` exit 0; `npm run build`
  exit 0 (chunk-size warning pre-existing).

## 4. Limits / unverified

- **The full-suite gate did not go green.** No single-invocation green
  run exists for this branch. §3.3 classifies every failure as
  environmental with 0 assertion failures, but that classification is
  not a green gate: the suite must be re-run when the environment
  allows (~12 min of healthy window; command and log path in §3.3).
- Intermittent write denial (environmental, time-varying, also
  observed independently by Track F): `tempfile.gettempdir()` fails
  across all candidates and SQLite writes fail with disk I/O error /
  EPERM during denial windows, toggling on a minutes timescale; one
  sustained window lasted ~55 min (03:21–03:58 UTC 2026-11-17). Even a
  preflight pass does not guarantee a clean window for the whole run.
- Lock contention: a sibling (hud) wrapper removed the lock directory
  mid-run at ~03:52 UTC ("stale lock removed") while this track held
  it, and a polish-track chunk pytest was observed running
  concurrently at 04:07. Lock exclusivity was therefore not airtight
  during attempt 3; this track's EXIT trap released whatever lock
  directory existed at shell exit.
- Two pytest invocations exited 120 within ~1s with empty logs
  (unexplained; no repo hook enforces it; leading hypothesis is a
  denial window striking at startup). The gated attempt-3 command
  used `tee` + `PIPESTATUS` so a recurrence would leave evidence; it
  did not recur there.
- Attempt 2's disk-`TMPDIR` deviation is recorded in §3.3, not hidden.
- No Docker verification: no container runtime exists on this VM
  (unchanged from all prior sprints).
- Frontend full suite carries one pre-existing flaky failure
  (`Charts.test.tsx`, histogram rendering under load) that fails at
  pristine baseline `ccc3490` and passes 23/23 in isolation; it is
  unrelated to this track's label-only frontend change, and no
  frontend test asserts the changed label. No real-browser
  verification of the label change (string-only change; `tsc`,
  `eslint`, and production build all pass).
- The promoted penetration drift remains a placeholder magnitude
  (`assumption:pending-calibration`); calibration (v3) is still ahead.
  The income rate is the fixed NBS 2025 value, not a live series.
- Note: `tests/test_variable_templates_api.py` has 2 known failures
  when run in isolation (registry discovery order, pre-existing per
  the track brief); run it as part of a larger invocation, not alone.
  Its 12 failures in attempt 3 carry disk-I/O signatures.
