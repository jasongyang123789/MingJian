# Proposal gates (template v2) — report (2026-11-18)

Task: Ho ordered 2026-11-18 10:41 that the direction-proposal
contract/template be optimized so LLM proposals carry concrete
thresholds and gates. The option-C live run the same morning
(`~/workspace/verification/option-c-live-2026-11-18/REPORT.md`,
verdict (d)) showed rationales with no numeric thresholds or
concrete gates — because the v1 contract had no fields for them.
The shortcoming was the template's shape, not the model's: all four
v1 rationales quoted real stored numbers and invented no advantage,
but the contract gave the model nowhere to put a threshold.

Worktree: `~/workspace/mingjian-proposal-gates`, branch
`strategy-engine/proposal-gates`, base 55a3e9a. BACKLOG.md
untouched. No merge, no push. The live observation evidence lives
in `~/workspace/verification/proposal-gates-live-2026-11-18/`.

## 1. Design decisions

### D1 — Gate schema (minimal, groundable)

New `DirectionGate` model in
`src/planagent/services/narratives/proposals.py`:

| Field | Type | Rule |
|---|---|---|
| `variable_id` | `str` (stripped, 1–120) | Must be bound on the anchor run; validated by the service (D4) |
| `comparison` | `">=" \| "<=" \| ">" \| "<" \| "=="` | Literal; anything else is a contract failure |
| `threshold` | `float` | Finite only; strings, booleans, NaN, and infinities refused (same discipline as the option-B override values — Pydantic accepts non-finite floats by default, so the before-validator is load-bearing) |
| `basis` | `str` (stripped, 1–500) | Names the stored number the threshold derives from; shape-validated only (D3) |

`DirectionProposal` gains `gates: list[DirectionGate]`
(`min_length=1, max_length=4`). Extra keys remain forbidden
everywhere in the contract.

### D2 — Gates are required (at least one per proposal)

A proposal without a concrete threshold is not a complete proposal
under v2 — that is the gap being closed. Making gates optional
would let the shortcoming persist silently whenever the model
omitted them. A gateless proposal set is a contract failure (502,
retryable), the same treatment as any other malformed output.
Alternative considered (optional gates, prompt-advisory only):
rejected for exactly that reason.

### D3 — Basis is free text; derivation is judged, not parsed

The prompt instructs the model to derive every threshold from a
number shown in the context and to quote that number in `basis`
along with its source (run, arm, summary statistic). The backend
validates only the basis shape (non-empty, capped). Whether a basis
actually cites a real stored number is NOT validated
programmatically at write time: any keyword/number matching would
be brittle and gameable, and the human reviewer sees the basis in
the review queue (D8) and judges it. The live observation (§5)
checks basis grounding programmatically where checkable (number
extraction against the stored summaries) plus by reading.

Alternative considered (structured basis `{run_id, arm,
statistic, value}` with exact stored-value matching): rejected.
Float-copy fragility — a model rounding 98.6386 to 98.64 would
refuse an otherwise valid set — and it would over-restrict gates
to ensemble statistics when future prompt contexts may show more
stored numbers.

### D4 — Refusal split (shape vs reference, same as v1)

- Shape violations — non-finite threshold, bad comparison,
  missing/empty basis, empty gates list, extra keys — fail the
  Pydantic contract before grounding: 502
  `direction_propose_contract_failed`, zero writes.
- A gate naming an unbound variable fails grounding validation in
  `_validate_proposals`: 400
  `direction_proposal_unknown_gate_variable` (the route's status
  map defaults unlisted direction codes to 400, so no route change
  was needed), zero writes, whole-batch atomicity — a valid
  proposal in the same set is refused with the bad one, mirroring
  the existing unknown-branch/unknown-variable discipline.

### D5 — Template version "1" → "2"

`PROPOSAL_TEMPLATE_VERSION` is now `"2"`, recorded in every stored
`proposal_record` and in the propose response, per the Sprint 15
convention of recording template id + version with stored output.
No skills-registry change: the proposals template lives outside
the registry (module docstring), and the 17-template pin is
untouched. No contract-normalization change: the Sprint 15
normalization lives in the skills `_Contract` base class, and the
proposals path validates the port payload directly with
`DirectionProposals.model_validate` — no normalization layer
intercepts it, so there is nothing to teach the new fields to.

### D6 — No migration; v1 records read fine

`proposal_record` is an untyped `dict[str, Any]` column and no
backend code reads gates back out of it: propose() only writes
them, the API only serves the dict through. Old records without a
`gates` key are served unchanged (covered by
`test_v1_proposal_record_without_gates_reads_fine`). The frontend
treats a missing `gates` key as an empty list and renders it
honestly (D8).

### D7 — Accept path unchanged

Accept re-validates source run + MECE branches only; it does not
re-validate `key_variables` either. Gates are review material,
not execution inputs — the direction executes via source run,
arm, and branches. Gate-variable staleness is handled the same
way as key-variable staleness (not re-validated on accept). This
is a deliberate scope boundary, not an oversight.

### D8 — Prompt context names the ensemble metric

`ProposalFamilyRun` gains `metric`, threaded from the
already-validated ensemble fragments in `_proposal_family_runs`
(`_assemble_candidates` validates them first), and the prompt
renders "baseline P50 of cash 98.6386" instead of the bare "P50
98.6386". Without the metric name, a gate basis cannot cite the
stored number it derives from without guessing what the summary
measures. Fragments without a metric render the v1 shape.

### D9 — Review queue displays gates

`parseProposalRecord` gains `gates` (well-shaped entries only;
malformed entries dropped, matching the `parseOverrideRecord`
precedent). The "待评审提案" queue renders each gate as
`variable comparison threshold` plus its basis, so a reviewer
judges the gate without opening anything else. A record with no
parseable gates (v1 records) renders an honest "决策门槛：无" line
rather than hiding the absence. The stored list is unchanged: it
does not render proposal records.

## 2. Files changed

Backend:

- `src/planagent/services/narratives/proposals.py` — `DirectionGate`,
  `gates` field, version bump, system-prompt gate instructions,
  `ProposalFamilyRun.metric`, prompt rendering. Module docstring
  updated: the "live quality UNVERIFIED" line was stale since the
  option-C live run.
- `src/planagent/services/narratives/service.py` — gate-variable
  grounding check, gates pinned in `proposal_record`, metric
  threading in `_proposal_family_runs`, propose() docstring.
- `src/planagent/services/narratives/__init__.py` — export
  `DirectionGate`.

Frontend:

- `frontend-v2/src/components/cockpit/directionMappingDisplay.ts` —
  gate parsing in `parseProposalRecord`.
- `frontend-v2/src/pages/Directions.tsx` — gate display + honest
  no-gates line in the review queue.

Tests:

- `tests/unit/test_direction_proposals.py` — 9 new tests (gate
  contract, prompt metric/gates rendering, system-prompt gate
  rules).
- `tests/test_direction_proposals_api.py` — 4 new tests (unknown
  gate variable, non-finite threshold, malformed/empty gates,
  v1-record backward compat); fixture helper gains a default
  gate; template-version assertions "1" → "2"; happy-path test
  asserts stored gates + the metric name in the prompt.
- `frontend-v2/src/components/cockpit/directionMappingDisplay.test.ts` —
  3 new gate tests; existing record tests updated for the `gates`
  field.
- `frontend-v2/src/pages/Directions.test.tsx` — 2 new tests (gate
  display, v1 honest line).

## 3. Verification counts

All backend runs used a `/dev/shm` TMPDIR with the serialized-run
discipline; the editable install was verified to point inside the
worktree before any test ran.

| Suite | Result |
|---|---|
| `tests/unit/test_direction_proposals.py` | 26 passed (17 existing + 9 new) |
| `tests/test_direction_proposals_api.py` | 30 passed (26 existing + 4 new) |
| Neighbors: `test_narratives_api`, `test_direction_derivation_api`, `test_direction_overrides_api`, `test_direction_overrides_unit`, `test_direction_override_reforks_api`, `test_direction_overrides_hardening` | 122 passed |
| Frontend: `Directions.test.tsx` + `directionMappingDisplay.test.ts` | 66 passed |
| Frontend full suite | 324 passed (32 files), lint 0, build 0 |
| Sprint 0 smoke | PASS (evidence reverted) |
| Ruff check + format on touched files | Clean, except `service.py` format deviations that are pre-existing at base (verified by stashing: base file also fails `ruff format --check`; the flagged regions are hardening/override code, untouched here) |

Red/green proof (core refusal test): with the gate-variable check
in `_validate_proposals` temporarily removed,
`test_propose_refuses_unknown_gate_variable_and_writes_nothing`
FAILED (1 failed, 7.44s); with the check restored it passes, and
the full API file passes 30/30.

## 4. What the new tests pin

- Gate contract: all five comparisons accepted; int thresholds
  coerce to float; variable/basis whitespace stripped; inf/-inf/
  NaN, string, and bool thresholds refused; bad comparison, blank
  basis, blank variable, and extra keys refused; empty gates list,
  missing gates key, and >4 gates refused.
- API grounding: unknown gate variable → 400 with the named code,
  zero writes, valid sibling proposal refused too (batch
  atomicity); non-finite threshold → 502 contract failure, zero
  writes; malformed gate and empty gates → 502, zero writes.
- Backward compat: a directly inserted v1 record (no `gates` key,
  `template_version` "1") is served unchanged by the mappings
  endpoint.
- Frontend: gate parsing drops malformed entries and keeps order;
  non-array `gates` reads as empty; v1 record reads as empty gates;
  the queue renders gate lines with bases and the honest no-gates
  line for v1 records.

## 5. Live observation (one run, kakouai gpt-6.1-sol)

Method: the two-phase method from the option-C live run, reused
exactly — phase 1 builds the anchor, branch child, and both
ensembles with NO LLM configured (monte-carlo 0.8s each); phase 2
restarts on the SAME DB with the real LLM for the single propose
call. Same anchor shape as the v1 observation (5 bound variables,
4-branch tree, fork_step 3 cash override, 20-trial ensembles,
metric cash, seed 7), so the two observations are comparable.
Driver: `run_live_propose.py` in the evidence dir. Fresh hsurr
surrogate, env-only, never logged; the surrogate-shape sweep over
all artifacts is clean. Wentoken not used (402).

Criteria (stated before judging): (a) contract validity; (b)
grounding — branches, variables, source runs, gate variables
bound, thresholds finite, comparisons valid — verified
programmatically; (c) gates populated — every stored proposal
carries 1–4 gates; (d) gates grounded in real numbers — every
gate's basis quotes a number matching a stored ensemble summary
number (P50/p_loss shown in the prompt), checked programmatically
with a 1% tolerance for rounding, and the attribution (run, arm,
statistic) verified by reading; (e) diversity; (f)
refusal/truncation behavior.

### Verdicts

**(a) Contract: PASS.** One request, HTTP 200 in 15.12s. 2/2
outcomes `stored`; `template_id` `narrative.direction_proposals`
v2; `proposal_hash` present and identical across both stored
records; every stored mapping has origin=`llm_proposal`,
status=`proposed`, and a complete `proposal_record` including
`gates`.

**(b) Grounding: PASS (programmatic).** `grounding_check.json`:
`all_grounded: true`. Every named branch is one of the 4 leaves;
every key variable is one of the 5 bound ids; every source run is
one of the 2 family runs; both gate variables are bound; both
comparisons are valid literals; both thresholds are finite.

**(c) Gates populated: PASS.** 2/2 stored proposals carry exactly
1 gate each — within the 1–4 contract range. The model returned
2 proposals (of the allowed 1–4), fewer than the v1 run's 4; that
is the model's choice, not a failure.

**(d) Gates grounded in real numbers: PASS.** Both gates quote
exact stored P50 values with correct run/arm/statistic
attribution, verified against `anchor.json`:

| Proposal | Gate | Basis (quoted) | Stored number |
|---|---|---|---|
| Cash-Gated Launch | `cash >= 80.0` | "stored ensemble cash P50 of 80.0 k$ from run 626ee8de…, strategy arm" | Child run strategy P50 = 80.0 (flat, from the fork_step cash override) |
| Preserve Core Operations | `cash >= 98.6386` | "stored ensemble cash P50 of 98.6386 k$ from run 6c73d9d4…, baseline arm" | Anchor baseline P50 = 98.6386 |

Both thresholds equal the quoted stored number — the model used
the stored P50 directly as a minimum-cash condition rather than
deriving a distinct cutoff (e.g. a haircut). That satisfies the
prompt's derivation instruction, but the gates are conservative
restatements of stored values, not computed cutoffs; a chair
judging them should know the threshold carries no safety margin
beyond the quoted statistic. The programmatic number check has
one known noise source: run ids embedded in the basis text
contribute digit fragments to the extracted-number list (e.g.
"P50" contributes 50). The verdict rests on the exact P50 matches
plus reading the basis text, not on the match flag alone — the
matched values 80.0 and 98.6386 are the quoted P50s, confirmed by
eye against both the basis strings and `anchor.json`.

The rationales keep the v1 run's evidence discipline: both note
the ensembles show no arm differentiation and invent no advantage
(e.g. "This run reports identical baseline and strategy cash P50
and loss probability, so it does not establish a financial
advantage for launching").

**(e) Diversity: PASS.** Two distinct postures (a cash-gated
launch vs retaining the baseline), different branch sets, different
variable sets, both arms used (strategy + baseline).

**(f) Refusal/truncation: NONE OBSERVED.** Exactly one propose
request in `server-phase2.log` (POST → 200); no retries; zero
error/traceback/exception lines in either phase log. Finish
reasons are not exposed by the propose API, so none are claimed.
The refusal path was NOT exercised live (both proposals passed
grounding); refusal behavior remains fixture-covered only.

## 6. What was NOT verified

- Single run, one model (gpt-6.1-sol), one provider (kakouai).
  No panel diversity, no determinism claim — a re-run would
  likely produce different proposals and gates.
- No live observation of the refusal path, of guidance-parameter
  behavior, or of contract/truncation failure handling.
- Ensemble construction ran with LLM-assisted action selection
  OFF (phase 1, no LLM configured); the propose observation
  itself ran with the real LLM on. An end-to-end LLM-configured
  construction was not run (see the ~40-minute ensemble cost in
  the option-C report — still open, out of scope here).
- No cockpit UI involvement in the live run; the gate display is
  covered by mocked-fetch frontend tests only. No real-browser
  check (no browser automation on this VM).
- Whether live models comply with the required-gates contract
  across providers/models: one observation on one model cannot
  establish that. A model returning a gateless set gets a 502
  and the user retries — that failure mode is unobserved.
- Postgres behavior of the new code paths (gates are JSON in an
  existing column; no DDL changed) and behavior under concurrent
  propose calls (same untested position race as v1).
- Whether thresholds that merely restate a stored P50 (as both
  live gates did) are useful gates in practice: a product
  judgment for the chair, not something this run settles.
