# Sprint 0 — Baseline report

Date: 2026-11-13. Branch: `strategy-engine/sprint0-baseline` (local only, never pushed).
Purpose: verified, reproducible baseline of the MingJian base before any
feature work. Companion doc: `docs/as-is-architecture.md`.

## 1. Upstream

- Remote: https://github.com/dashitongzhi/MingJian.git (from `git remote -v`
  on the research clone; default branch `master`).
- Baseline commit: `999ef36c05df7603f44e2ba96160a35aa59004e7`
  (2026-08-11 16:13:02 +0800), full 340-commit history cloned.
- License: Apache-2.0 (`LICENSE`, verified).
- No GitHub-side fork exists yet — that is a follow-up for Ho (no GitHub
  auth in this environment, no pushes made).

## 2. Environment

- OS: Linux VM (this machine). Python 3.12.3. Node v24.22.1 / npm 10.9.4.
- Virtualenv: `.venv/` (gitignored), installed with
  `python -m pip install -e '.[dev]'` (the CI command uses `uv`; `uv` is
  not installed here — pip equivalent, same requirement set).
- Docker: NOT available (see §3).

## 3. Stack status — Docker path BLOCKED, local path verified

Docker check (2026-11-13, this VM):

```
$ docker --version        -> docker: command not found
$ docker compose version  -> docker: command not found
$ ls /var/run/docker.sock -> No such file or directory
$ which podman nerdctl containerd -> (none found)
$ apt-cache policy docker.io -> (no candidate)
$ free: MemAvailable ~590 MB of 8 GB
```

No container runtime exists on this VM, and the 14-service Compose stack
(postgres + redis + minio + api + frontend + 10 workers) cannot fit in
the ~590 MB of free memory. Docker was NOT installed: installing a daemon
and pulling images is out of scope for this baseline and would risk the
shared VM. **The Docker Compose stack has therefore NOT been observed
running. Do not claim otherwise.**

Fallback used (documented local-dev path, `.env.example`):
SQLite (`sqlite+aiosqlite`) + in-memory event bus + inline ingest/simulation.
This is the configuration the repo's own test suite uses, and it is what
§4 and §5 verified.

## 4. Baseline tests

Command (CI, `.github/workflows/ci.yml`): `python -m pytest -q`
Full log: `docs/sprint0/test-baseline.log`

**Environment quirk (this VM only, fixed without code changes):** the
first run failed 2 of 736 tests with `httpx.InvalidURL: Invalid port`
raised while constructing `AsyncOpenAI` clients. Root cause is the VM's
`NO_PROXY`/`no_proxy` variables, which contain bracketed IPv6 literals
that httpx cannot parse when reading proxy config from the environment.
It is not a repo bug: no repo code sets those variables. The fix is
invocation-time only — run tests (and any local app process) with the
bypass lists unset: `env -u NO_PROXY -u no_proxy ...`. The first run's
log is preserved at `docs/sprint0/test-baseline-run1-proxy-env.log`;
the rerun below used the sanitized environment.

First run (stock VM env): 2 failed, 734 passed, 212.38s. Failures:
- `tests/test_phase1_api.py::test_openai_status_reports_target_level_inheritance`
- `tests/unit/test_interface_error_redaction.py::test_openai_connection_diagnostics_do_not_echo_exception_messages`

<!-- RERUN NUMBERS TO FILL IN -->
Rerun (sanitized env, `env -u NO_PROXY -u no_proxy python -m pytest -q`):
**736 passed, 0 failed, 0 skipped, 263.65s.** This is the recorded
baseline. Both previously-failing tests pass with the sanitized
environment, confirming the proxy-env diagnosis; no repo code was
changed to get here.

Frontend suite (`frontend-v2`, vitest) was NOT run: it needs `npm ci`
+ Node 22 (this VM has Node 24) and is a separate baseline; see §7.

## 5. End-to-end smoke (no LLM, no Docker)

Script: `docs/sprint0/smoke_e2e.py` (re-runnable). Evidence:
`docs/sprint0/smoke-evidence.json`. Flow mirrors
`examples/agent_startup/README.md`: ingest seed evidence → baseline
simulation (4 ticks) → decision trace / workbench / options.

<!-- SMOKE RESULT TO FILL IN -->
Result: **PASS** (exit 0, 2026-11-13). Local app via `TestClient`, scratch
SQLite DB, empty LLM keys, in-memory event bus
(`PLANAGENT_EVENT_BUS_BACKEND=memory` — required: the default Redis bus
fails here with connection refused, no Redis on this VM). Observed:

| Step | Result |
|---|---|
| `GET /health` | 200 `{"status": "ok"}` |
| `POST /ingest/runs` (example seed) | 201, run `e86bb25b-…`, `COMPLETED`, `INLINE`, 4 source types |
| `POST /simulation/runs` (baseline, 4 ticks) | 201, run `545b056c-…`, `COMPLETED`, `INLINE`, `evidence_count` 2, `shock_count` 4, `seed` 7 |
| `GET /runs/{id}/decision-trace` | 200, 4 records, all `decision_method: rule_engine` (no LLM key, rule level covered every tick; LLM/fallback levels not exercised) |
| `GET /runs/{id}/workbench` | 200, 16 top-level keys |
| `GET /runs/{id}/options` | 200, 1 option generated |

Full IDs and payloads: `docs/sprint0/smoke-evidence.json`. Re-run with
`.venv/bin/python docs/sprint0/smoke_e2e.py` (it sanitizes the proxy env
itself and uses a scratch DB at `/tmp/sprint0-smoke.db`).

LLM boundary: `POST /debates/trigger` was NOT exercised. The debate
workflow is backed by `LLMDebateAdapter`
(`src/planagent/services/debate/workflow.py`) and requires a real model
key; no key exists in this environment and none was invented. The
heuristic debate adapter (`services/debate/engines.py`) is only used by
branch/claim assessment, not by the trigger path. Debate, report
generation, and any LLM-assisted simulation level remain unverified
end-to-end until a key is provided.

## 6. Architecture map

`docs/as-is-architecture.md` — module/service map, request + record
flows, simulation tick flow, debate flow, worker topology, data-model
summary (~50 tables, 29 Alembic revisions), config/env surface. Every
claim cites a file path that was read.

Headline facts (verified by reading code):
- Simulation is a real hybrid numeric engine: deterministic state model
  + YAML rules + 3-level action selection (`rule_engine` → `llm_assisted`
  → `fallback_random`), `decision_method` recorded per tick
  (`src/planagent/services/simulation/engine.py`,
  `src/planagent/services/simulation/impact.py`).
- `SimulationRun.seed` is stored but NOT wired to any RNG: no `random.*`
  usage in `services/simulation/` or `simulation/`.
- No Monte Carlo / distributions, no MECE layer, no user variable tables:
  state fields and thresholds are hardcoded per domain pack
  (`simulation/domain_packs/*/pack.py`,
  `services/simulation_branching.py:_STATE_POLICIES`).
- 9-agent debate council, recommendation versioning, watch/monitoring,
  calibration reflux, MCP server, and a 13-page React frontend all exist.

## 7. Blockers

1. **Docker / full stack** — no container runtime on this VM (§3). Needs a
   machine with Docker + several GB free to verify Compose health.
2. **LLM API key** — no key in this environment. Blocks: debate trigger,
   LLM-assisted simulation level, report generation, extraction quality
   paths. A placeholder key was NOT used to fake these; empty keys were
   used so code paths degrade honestly to rule/fallback behavior.
3. **GitHub-side fork** — needs Ho's GitHub account; local branch only.

## 8. Sprint 1 entry points

1. MECE layer: new module under `src/planagent/services/` + routes; gate
   `POST /simulation/runs` (`src/planagent/api/routes/simulation.py:73`)
   on validator PASS. No existing MECE code to conflict with.
2. Variable tables: generalize `simulation/domain_packs/*/pack.py`
   defaults + `services/simulation_branching.py:_STATE_POLICIES` into
   stored, editable templates; `SimulationRun.configuration.initial_state`
   already carries per-run overrides — extend that pattern.
3. Seed/RNG wiring: thread `SimulationRun.seed` into a `random.Random`
   used by fallback selection and any future sampling, in
   `services/simulation/engine.py` / `impact.py`; add a golden-run test
   (same seed → byte-identical snapshots).
4. Distribution layer: sampling runner around `_execute_run`
   (`services/simulation/engine.py:185`); aggregate `StateSnapshotRecord`
   / `DecisionRecordRecord` across runs; graft scenario-lab
   ensemble statistics as a new module (donor, Apache-2.0).
5. Regression gates: keep `python -m pytest -q` green (baseline §4) and
   re-run `docs/sprint0/smoke_e2e.py` after each change.

## 9. Commands run (reproduction)

```bash
git clone https://github.com/dashitongzhi/MingJian.git mingjian-base
cd mingjian-base
git checkout -b strategy-engine/sprint0-baseline
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
# NOTE: this VM's NO_PROXY/no_proxy break httpx client construction;
# unset them for every local run (see section 4).
env -u NO_PROXY -u no_proxy .venv/bin/python -m pytest -q 2>&1 | tee docs/sprint0/test-baseline.log
.venv/bin/python docs/sprint0/smoke_e2e.py
```
