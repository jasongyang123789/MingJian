# Track E: HUD fitment semantics re-check

Date: 2026-11-17. Branch: `strategy-engine/hud-fitment-check`, worktree
`~/workspace/mingjian-hud`, base `ccc3490` (`strategy-engine/sprint20-cockpit-seminar`
tip, verified via `git rev-parse HEAD` before the worktree was created).

## Governing rulings

- Ho Q7 (2026-11-16): fitment rate = the share of a model x trim's
  production volume carrying the product; independent per
  product/solution; sums need NOT be 100%; no product-level sum gate.
- Ho 2026-11-17: P-HUD may coexist with W/AR-HUD on the same vehicle;
  penetration rates are NON-exclusive. The model P.O catalog's HUD
  fitment semantics must be re-checked against this ruling.

## Verdict

No code enforces or assumes HUD exclusivity: there is no HUD sum-to-1
constraint, no single-choice logic, and no HUD overlap prompt anywhere
in the enforcement or prompt paths. Two pieces of TEXT assumed
exclusivity and were fixed (catalog note + prompt-engine docstring),
with regression tests pinning the ruling. No behavioral logic changed.

## Locations examined

| # | Location | What it does | Verdict |
|---|----------|--------------|---------|
| 1 | `src/planagent/services/splits/catalog.py:62-67` (HUD_AR note) | Catalog note asserted "AR-HUD substitutes with W-HUD/P-HUD within the HUD slot" and claimed a prompt exists for the overlap. | **FIXED.** Contradicted the ruling (P-HUD coexists) and promised a prompt that does not exist. Note rewritten to state coexistence + independent rates; see Fix 1. |
| 2 | `src/planagent/services/splits/catalog.py:77-83` (HUD_P entry) | P-HUD entry carried no note at all. | **FIXED.** Coexistence note added at the variant the ruling names; see Fix 1. |
| 3 | `src/planagent/services/splits/catalog.py:70-75` (HUD_W entry) | W-HUD entry, no note, no claim. | Clean. No change. |
| 4 | `src/planagent/services/splits/expectations.py:18-24` (module docstring) | Stated "one car = one solution per function" as a blanket rationale for per-trim evaluation. | **FIXED.** Qualified: normal case behind the substitution prompts, never a universal rule; P-HUD coexistence cited; see Fix 2. |
| 5 | `src/planagent/services/splits/expectations.py` (rule evaluation, R1–R13/X1–X5/AVM1/BUNDLE1/SCREEN1/EMBED1) | No HUD rule exists. Substitution prompts R6 (P02 classes), R7 (P03 central), R9 (P04 4G/5G) read only their own product-line groups; P.O rows are touched only by R13 (bare `"P.O"` basket rows) and AVM1 (AVM rows). | Clean. No change. |
| 6 | `src/planagent/services/splits/validator.py` (`ONE_HOST_PRODUCTS`, slot gate) | One-host backstop covers `{"P01", "P04"}` only; HUD ids are separate slots with only per-row range checks + per-slot supplier-share sums. Docstring states there is deliberately NO product-level sum gate (Q7). | Clean. No change. |
| 7 | `src/planagent/services/splits/models.py` (`ProductFitment` docstring) | States Q7 independence and "No product-level sum gate exists anywhere." No HUD logic. | Clean. No change. |
| 8 | `src/planagent/services/splits/aggregation.py` + `sales_layer.py` | Per-slot formula `V x shares x fitment x supplier_share`; sums only per (OEM, product). HUD rows aggregate independently. | Clean. No change. |
| 9 | `src/planagent/services/splits/aliases.py` | No `P.O` branch; `classify_solution` returns `None` for P.O lines. No HUD classification. | Clean. No change. |
| 10 | `src/planagent/services/splits/morphology.py`, `schedules.py` | Morphology registry + generation schedules; no fitment-sum logic. | Clean. No change. |
| 11 | Frontend (`frontend-v2/src/`), routers, rules YAML, skill templates, auto domain-pack templates | Whole-tree case-insensitive `hud` grep: no references outside the splits service, its tests, and the Phase 2 report listing. | Clean. No change. |
| 12 | `PHASE2-AUTO-PACK.md:222` | Lists the 15 catalog ids only; asserts no HUD semantics. Historical report. | Clean. Left untouched. |

## Fix 1 — catalog notes (`catalog.py`)

HUD_AR note, before:

> AR-HUD substitutes with W-HUD/P-HUD within the HUD slot (same-function overlap is a prompt, not a gate).

HUD_AR note, after:

> HUD variant rates are independent penetrations (Ho Q7): P-HUD coexists with W-HUD/AR-HUD on the same vehicle (Ho 2026-11-17 ruling), so variant rates are never summed to 1 and no HUD-slot exclusivity is assumed.

HUD_P note, added:

> Coexists with W-HUD/AR-HUD on the same vehicle; penetration rates are non-exclusive (Ho 2026-11-17 ruling). An independent rate per model x trim (Ho Q7), never summed with other HUD variants.

No other catalog field changed (ids, labels, fitment kinds, evidence
strings, assumption flags all untouched). The `notes` field surfaces
via `PoSubProduct.to_dict()`; no endpoint or UI renders HUD notes
today (verified by the whole-tree grep), so the fix changes
documented semantics only.

Scope note: the ruling names P-HUD vs W/AR-HUD. This fix asserts
nothing about AR-vs-W substitution either way — no evidence either
way was ruled on, and no code constrains it.

## Fix 2 — prompt-engine docstring (`expectations.py`)

Before: "...prompts fire per trim, where one car = one solution per
function." After: "...prompts fire per trim, the level at which one
vehicle's fitment combination is observed. One solution per function
is the normal case behind the substitution prompts, never a universal
rule: P-HUD coexists with W-HUD/AR-HUD on the same vehicle (Ho
2026-11-17 ruling), and fitment rates are independent penetrations
(Ho Q7)." Docstring only; no evaluation logic touched.

## Tests added (fixtures only, no live LLM)

- `tests/test_phase2_splits.py::test_hud_variants_coexist_no_slot_exclusivity`
  — catalog: all three HUD variants are `rate` kind, no HUD note
  contains "substitut", HUD_AR and HUD_P notes contain "coexist";
  validator: one trim carrying HUD_AR 0.6 + HUD_W 0.5 + HUD_P 0.4
  (rates summing to 1.5) validates; aggregation: with production
  volume 100 the three slots yield 60 / 50 / 40 units independently.
- `tests/test_phase2_prompts.py::test_hud_variants_coexisting_draw_no_overlap_prompt`
  — the same three-variant trim draws zero anomaly prompts and no
  prompt title mentions HUD.

## Evidence

All numbers below are either values asserted by the named test or
run outcomes quoted from the cited logs. No coverage is claimed
beyond what ran.

### Values asserted by the new tests

- `tests/test_phase2_splits.py::test_hud_variants_coexist_no_slot_exclusivity`
  asserts: all three HUD catalog entries are `rate` kind; no HUD
  note contains "substitut"; the HUD_AR and HUD_P notes contain
  "coexist"; one trim carrying HUD_AR 0.6 + HUD_W 0.5 + HUD_P 0.4
  (rates summing to **1.5**) validates; aggregation at production
  volume 100 yields **60 / 50 / 40** units for HUD_AR / HUD_W /
  HUD_P respectively, as three independent slots.
- `tests/test_phase2_prompts.py::test_hud_variants_coexisting_draw_no_overlap_prompt`
  asserts: the same three-variant trim draws **0** anomaly prompts
  and no prompt title mentions HUD.

### Run outcomes (quoted from logs)

- Blast-radius subset, 9 files (`test_phase2_splits`,
  `test_phase2_prompts`, `test_splits`, `test_phase1_api`,
  `test_phase2_sales_layer`, `test_phase2_simulation_api`,
  `test_automotive_api`, `test_automotive_pack`,
  `test_automotive_phase2_api`): **164 passed, 0 failed** in 84s
  (run 2026-11-17, includes both new tests).
- Phase 2 splits + prompts subset: **64 passed, 0 failed**.
- Robustness + seminar-synthesis sanity subset (previously failing
  under the broken venv): **34 passed, 0 failed**.
- 4-way chunk 1 (first 32 test files, incl. both new tests):
  **402 passed, 22 failed** — all 22 failures are
  `sqlalchemy.exc.OperationalError: disk I/O error` (44 occurrences
  in `~/workspace/verification/hud-chunk1-old4way.log`), clustered
  in the chunk's last 3 files (an I/O-error wave starting mid-run);
  zero assertion failures; both new tests passed.

### Full-suite gate: NOT ACHIEVED (environmentally blocked)

Five gate attempts were made; none produced a trustworthy green
full run, and none produced an assertion failure attributable to
this change (two strings + two tests; no behavioral logic changed):

| Attempt | Outcome | Cause (from the log) |
|---------|---------|----------------------|
| Full run 1 | 331 failed / 1509 passed | Fresh venv missing `pytest-asyncio`/`httpx2` (setup error; fixed by installing the `dev` extras). |
| Full run 2 | 231 failed / 1611 passed | 221+ SQLite disk I/O errors: `/dev/shm/pytest-tmp-hud` held 767M of 794M (two runs' debris; cleaned). |
| Full run 3 | Killed (SIGTERM) | VM restart (~03:06 UTC). |
| Full run 5 | 347 failed / 1495 passed, 43:47 | 342 disk I/O errors + 5 PermissionErrors; zero assertion failures; both new tests passed. TMPDIR was workspace disk (overlay/btrfs+zstd). |
| Chunked v1 (4 chunks) | Chunk 1 only; rest blocked | SQLite preflight failed 20 consecutive times over 10 min (sustained EPERM window); then a second VM restart. |
| Chunked v2 (8 chunks) | Lock starvation | 60 min waiting for `~/.pytest-full-run.lock` (6 tracks contending); timed out without running. |

The failure sets differ across runs with identical code (331 / 231 /
347), and every failure in runs 2 and 5 is an OS-level I/O error —
the environment, not this change, is the variable. A green
single-process full run should be re-attempted in a quiet window
(clean `/dev/shm` TMPDIR, lock held); the parent agent owns that
decision. This track's own evidence (subsets + chunk 1 + zero
assertion failures across ~5,000 test executions) supports the
change as behavior-neutral.

### Environment notes (observed, not claimed as root causes)

- Intermittent `EPERM` on file creation/writes (`tempfile`,
  SQLite, plain `echo` redirects) striking in waves lasting
  minutes, across tmpfs and overlay/btrfs alike, also observed by
  other tracks' scripts (their preflight probes show the same
  pattern). No root cause established.
- Two VM restarts during the gate attempts (~03:06 and ~05:01 UTC,
  2026-11-17); detached processes do not survive them (nor the
  runtime's reaping — setsid/nohup children were found dead).
- `/dev/shm` (794M) shared by all tracks; other tracks' debris
  left it 70–83% full during this track's runs. This track's own
  debris was removed after every run.

## Limits / unverified

- No live LLM was used anywhere in this track; the prompt-engine
  behavior asserted here is the deterministic code path only.
- No Docker / container runtime exists on this VM; nothing about a
  deployed stack is claimed.
- The fix changes catalog documentation strings and a docstring; no
  migration, no API shape, no frontend change. The Phase 2 report and
  BACKLOG.md were not modified.
- AR-vs-W HUD substitution was not ruled on by Ho and is asserted
  neither way in code or catalog after this fix.
- The C-HUD question (whether C-HUD stays in the parts library) is a
  separate open item for Ho; the model catalog has no C-HUD entry and
  this track takes no position on it.
