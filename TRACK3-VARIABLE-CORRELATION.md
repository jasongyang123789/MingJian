# Track 3 — Variable correlation

Branch: `fix/variable-correlation` (from `83bb09f`). Tip: `b912204`.
Do NOT merge — report only.

## What changed

Monte Carlo sampled variables independently; linkage was only indirect
via the formula graph. Variables can now be correlated explicitly.

### Spec format

`VariableSet.correlations` (and `VariableTemplate` / Create / Update):
a list of `VariableCorrelation` — `{variable_a, variable_b,
correlation}` — unordered pairs, `correlation` in [-1, 1], the target
Pearson correlation. Stored run bindings carry it in the `variables`
fragment (old bindings without the field parse as independent — default
`[]`). Stored templates persist it in a new `correlations` JSON column
(migration `0044_variable_template_correlations`).

### Sampler mechanism

Gaussian copula, stdlib-only (no numpy), in
`src/planagent/services/variables/correlation.py` +
`src/planagent/services/distributions/sampler.py`:

- Correlated variables share one draw of correlated standard normals
  (Cholesky factor of the correlation matrix, one `rng.gauss` draw per
  variable, up front, in set order), mapped through Phi to uniforms,
  then through each marginal's inverse CDF (normal via
  `NormalDist.inv_cdf`, triangular closed-form, beta-PERT via a
  regularised-incomplete-beta bisection, Bernoulli via threshold).
- Marginals are preserved; the achieved Pearson correlation is
  *approximately* the specified rho: exact for normal marginals,
  slightly attenuated for bounded/skewed marginals and Bernoulli —
  the copula fixes rank dependence, Pearson follows from the marginals.
- Uncorrelated variables in a correlated set still draw independently;
  levers still replace drawn values after the draw is consumed, so
  paired baseline/strategy arms share the correlated stream.
- MC trials need no change: each trial run resolves its bindings with
  its derived sub-seed, so correlations apply per trial, paired across
  arms.

### Validation (gate, not sampler failure)

`validate_correlations` rejects: unknown variable ids, self-pairs,
duplicate pairs (unordered), |rho| > 1, pairs involving a `fixed`
variable (zero variance — correlation undefined), and matrices that
are not positive semidefinite (e.g. +0.9 / +0.9 / -0.9). Sets with no
spec gain no extra check record, so validation output serializes
exactly as before. `merge_variable_sets` merges pairs by unordered
key, override wins.

## Verification

- New `tests/unit/test_variable_correlation.py`: 26 tests — spec
  validation (all rejection kinds + PSD), achieved correlation
  (normal rho 0.8 → measured 0.7986; rho -0.6 → -0.6062; rho 1.0 →
  identical draws; triangular rho 0.8 → 0.7939, in bounds; beta-PERT
  rho 0.7 → 0.671, in bounds; 3-variable mixed spec; uncorrelated
  variable in a correlated set stays independent), determinism/replay
  (same seed byte-identical over 50 draws; different seed differs),
  lever pairing under correlation, default-independent contract
  (golden draws pinned; unspecified pair |r| < 0.06 over 2000 draws),
  bindings flow through `resolve_run_values`, old bindings parse as
  independent, merge behaviour, variable-less-template rejection.
- Acme baseline P50 pinned by a new test in
  `tests/test_distributions_api.py`: BOUND_SET, seed 7, tick 2, MC
  trials 5 / seed 42 / metric `cash` → baseline P50 **99.8143**
  (unchanged).
- Targeted files: 64 passed
  (`test_variable_correlation` + `test_sampler` +
  `test_variable_validator` + `test_distributions_api`).
- Full suite: **2122 passed, 0 failed** in 664.14s (single-process,
  TMPDIR on /dev/shm, under `full-run-lock.sh`). First run was 2120
  passed / 2 failed in 715.56s — the two golden byte-stability tests, because the
  serialized `VariableSet` now carries `"correlations": []`; fixed by
  regenerating the two golden expected fixtures (one added line each,
  same precedent as Sprint 4's `formulas: []`), then re-running the
  full suite green. (The first full-suite attempt never ran: a runtime
  restart killed the lock-waiter while queued behind other tracks'
  suites; the re-run acquired the lock immediately with /dev/shm
  fully free.)
- `ruff check` + `ruff format --check` clean on all changed files;
  `mypy` clean on the three changed source files. Note:
  `src/planagent/domain/models.py` already carries 35 pre-existing
  ruff findings on base `83bb09f` (verified against the main
  worktree); this track's one-line change there adds none.

## Limits

- Achieved Pearson correlation is approximate for non-normal
  marginals (see measured values above); a user who needs an exact
  Pearson value on a triangular/beta-PERT pair cannot get it from a
  copula — the spec documents this as rank dependence.
- `fixed` variables cannot be correlated (rejected at the gate);
  Bernoulli pairs work but Pearson is attenuated by the threshold.
- No frontend sync: the cockpit template authoring UI does not yet
  offer a correlations editor (types in `engineTypes.ts` /
  `templateDraft.ts` untouched) — correlations are settable via API /
  bindings JSON only.
- No per-tick correlation: the spec applies to the once-per-run
  sample; tick-driver formulas still re-evaluate deterministically
  over the sampled values.
