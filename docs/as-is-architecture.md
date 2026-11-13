# As-is architecture map — MingJian (PlanAgent) baseline

- Upstream: https://github.com/dashitongzhi/MingJian.git, branch `master`,
  commit `999ef36c05df7603f44e2ba96160a35aa59004e7` (2026-08-11).
- Mapped: 2026-11-13, Sprint 0. Every claim below cites a file that was read.
- Stack: Python 3.12, FastAPI + SQLAlchemy 2.0 async + Pydantic v2
  (`pyproject.toml`); React 19 + Vite + TypeScript frontend in `frontend-v2/`;
  PostgreSQL + pgvector, Redis Streams, MinIO in Docker Compose
  (`docker-compose.yml`); SQLite + in-memory bus supported for local dev
  (`.env.example`, `src/planagent/db.py`, `src/planagent/events/bus.py`).

## 1. Module / service map

```
frontend-v2/                 React 19 SPA (Vite). Pages: Dashboard, Evidence,
                             Simulation, Debate, Predictions, Monitoring,
                             Reports, Sources, Workbench, Agents, AiAssistant,
                             Settings (frontend-v2/src/App.tsx, src/pages/).
                             API client: frontend-v2/src/api/client.ts.

src/planagent/
  main.py                    FastAPI app factory create_app(); lifespan wires
                             database, event bus, rule registry, OpenAI service,
                             auth, notification, export services. Routers are
                             mounted twice: bare and under /api; MCP routes
                             only when settings.mcp_enabled.
  config/                    Pydantic-settings, env prefix PLANAGENT_
                             (config/base.py). Sub-models: auth, database,
                             minio, redis, openai (config/__init__.py).
  db.py                      Async SQLAlchemy engine; SQLite gets NullPool,
                             Postgres gets a sized pool. init_models() only
                             does create_all; schema changes go through
                             Alembic (migrations/versions/, 29 revisions).
  domain/
    models.py                ~50 SQLAlchemy models (see §5).
    api.py                   Pydantic request/response schemas (1369 lines).
    enums.py                 Status enums + EventTopic (raw.ingested,
                             evidence.created, claim.review_requested,
                             knowledge.extracted, simulation.completed,
                             scenario.completed, report.generated,
                             debate.triggered/completed/..., jarvis.*).
  api/routes/                17 route modules aggregated in api/routes/__init__.py:
                             analysis, agents, debate_votes, debate_replay,
                             debate_interrupt, decisions, evidence, simulation,
                             admin, monitoring, prediction, sources, auth,
                             export, notifications, stats, watch + ws.py
                             (websocket). CommunityAccessMiddleware gates
                             community/remote access (api/access.py).
  services/
    pipeline.py              Evidence pipeline: ingest runs -> raw items ->
                             normalization -> evidence -> claims -> review.
    simulation/              Simulation kernel (see §3).
    simulation_branching.py  MetricPolicy thresholds per domain (hardcoded
                             alert/critical values, e.g. corporate cash
                             alert 50 / critical 25).
    simulation_military.py   Military outcome resolution / operational picture.
    debate/                  Debate council (see §4).
    agent_registry.py        9 built-in agents (advocate/challenger/
                             arbitrator + 6 perspective roles).
    sources/                 Source connectors + registry.
    providers/               LLM provider adapters.
    openai_client.py         OpenAI-compatible client used by API + workers.
    prediction.py / backtest.py   Prediction series, versions, backtests
                             (737 / 235 lines).
    recommendations.py       Recommendation versions (decision timeline).
    watch_*.py, community_monitoring.py, change_detection.py
                             Monitoring / watch rules / refresh.
    export.py, reporting.py, debate_html_report.py, pdf_rendering.py,
    chart_generation.py      Reports, exports, PDF/charts (weasyprint,
                             matplotlib).
    auth.py, login_throttle.py, notification.py, jarvis.py, assistant*.py,
    workbench.py, decision_feedback.py, evidence_weighting.py,
    calibration via engine + workers/calibration.py
  simulation/                Domain-pack kernel: specs.py (StateFieldSpec,
                             ActionSpec, ActorTemplate...), rules.py (YAML
                             rule registry, RuleSpec.matches() = keyword
                             substring), domain_packs/corporate/pack.py
                             (15 state fields, 8 actions) and
                             domain_packs/military/pack.py. Packs self-register
                             via registry.discover() (simulation/__init__.py).
  events/
    bus.py                   EventBus protocol; InMemoryEventBus and
                             RedisStreamEventBus; build_event_bus() picks
                             Redis only when the redis backend is configured.
    topology.py              StreamTopologySpec; stream:<topic> naming,
                             per-topic DLQ streams, worker descriptions.
  workers/                   10 worker classes (see §6), driven by worker_cli.py
                             (`python -m planagent.worker_cli <name> --loop`).
  mcp/                       MCP server (server.py, protocol.py, config.py),
                             mounted only when enabled.
  templates/, ui/            Report templates / legacy UI helpers.
rules/                       YAML rule registries: rules/corporate/
                             default_rules.yaml, rules/military/
                             default_rules.yaml. Loaded by get_rule_registry()
                             (simulation/rules.py); settings.rules_dir
                             defaults to Path("rules") (config/base.py).
scripts/, config/, docs/, examples/
                             Ops scripts, sample configs, docs, and three
                             runnable example packs (agent_startup,
                             investment_analysis, military_logistics) with
                             curl instructions in each README.md.
```

## 2. Request + record flow (evidence → simulation → debate → decision → monitoring)

1. **Ingest.** `POST /ingest/runs` (routes in `api/routes/evidence.py` /
   `sources.py`; payload shape in `examples/*/evidence_ingest.json`) creates
   an `IngestRun` + `RawSourceItem` rows (`domain/models.py`). Inline mode
   (default `PLANAGENT_INLINE_INGEST_DEFAULT=true`, `.env.example`) runs the
   pipeline in-process; otherwise the ingest worker consumes
   `raw.ingested` from the bus.
2. **Normalize / evidence / claims.** `services/pipeline.py` turns raw items
   into `NormalizedItem` → `EvidenceItem` → `Claim` rows, with `ReviewItem`
   gating (`ReviewItemStatus`). Knowledge worker extracts signals/trends;
   graph worker maintains `KnowledgeGraphNode`/`Edge`.
3. **Simulate.** `POST /simulation/runs` (`api/routes/simulation.py:73`)
   creates a `SimulationRun`; execution writes `StateSnapshotRecord` per
   tick, `DecisionRecordRecord` per tick, `ExternalShockRecord` per claim
   shock, and `DecisionOption`/`Hypothesis` rows at the end (see §3).
4. **Debate.** `POST /debates/trigger` (`api/routes/simulation.py:459`)
   starts a `DebateSessionRecord`; rounds and verdicts persist as
   `DebateRoundRecord` / `DebateVerdictRecord`, with votes, interrupts and
   replay (`api/routes/debate_*.py`, `services/debate/`). See §4.
5. **Decide.** `services/recommendations.py` versions recommendations
   (`RecommendationVersion`); `UserDecision` records the human's choice;
   `DecisionOption` rows hold generated options with confidence.
6. **Monitor / learn.** `WatchRule` + watch workers re-ingest sources,
   `change_detection.py` diffs, `CalibrationRecord` / `RuleAccuracy` /
   `PredictionCalibrationContext` feed calibration; the calibration worker
   (`workers/calibration.py`) updates rule weights from accuracy.

Cross-cutting: every stage publishes/consumes `EventTopic` events on the bus
(`events/bus.py`, `events/topology.py`); failures land in `DeadLetterEvent`
(`domain/models.py:421`).

## 3. Simulation tick flow

Entry: `SimulationEngineMixin.run_simulation()` → `_execute_run()`
(`services/simulation/engine.py:36,185`).

Per run (single world-line, no branching inside a run):

1. Resolve the domain pack (`registry.get(run.domain_id)`), build the initial
   state from pack defaults, then overlay `run.configuration["initial_state"]`
   (flat floats, `engine.py:185-196`).
2. Fetch relevant claims (`_fetch_relevant_claims`, scoped by subject) and
   domain rules; build a calibration context (`_build_calibration_context`).
3. Write tick-0 `StateSnapshotRecord`.
4. For `tick in 1..run.tick_count`:
   - Cycle claims round-robin: `claims[(tick-1) % len(claims)]`
     (`engine.py:217`). If a claim is active, record an external shock and
     apply fixed numeric state deltas via `_apply_external_shock`
     (`services/simulation/impact.py:266`) — keyword-substring matching
     against the claim statement (`simulation/rules.py: RuleSpec.matches`).
   - Select an action with the 3-level selector `_select_action`
     (`impact.py:362`):
     1. **rule_engine** — rank action candidates from rules + state
        alignment; if best `total_score >= _DECISION_MIN_SCORE`, use it.
     2. **llm_assisted** — `_llm_decide_action` (LLM call with timeout,
        result must be inside the action library; otherwise ignored).
     3. **fallback_random** — weighted deterministic fallback effect
        (`_fallback_effect`).
     - Every selection records `decision_method` (`rule_engine` /
       `llm_assisted` / `fallback_random`, `impact.py:23-30`).
   - Military runs additionally resolve enemy response
     (`_military.resolve_military_action_outcome`,
     `services/simulation_military.py`) and build an operational picture.
   - Apply effects to state; write `DecisionRecordRecord` + per-tick
     `StateSnapshotRecord`.
5. After the loop: `_generate_decision_options` (top-3 actions → options
   with risk text + assumption sentences + a rough confidence formula),
   `_apply_calibrated_confidence`, mark run COMPLETED, publish
   `simulation.completed`.

Scenario branching is a separate layer: `POST /scenario/runs/{id}`
(`api/routes/simulation.py:101`) and `services/simulation/scenarios.py`
create branch runs from a parent run; `ScenarioBranchRecord` persists them;
`GET /runs/{id}/scenario-compare` compares branches. Branches are whole
re-runs, not in-run forks.

**Verified gaps (read, not assumed):**
- `SimulationRun.seed` is stored (`domain/models.py:492`) and copied from
  the payload (`engine.py:126,157`), but no `random.*` usage exists in
  `services/simulation/` or `simulation/` — the seed is not wired to any
  RNG in the simulation code, so same-input re-runs are deterministic only
  insofar as the LLM level is not hit (LLM level is skipped when no key /
  on error, falling through to level 3).
- No Monte Carlo / distribution code: one run = one trajectory; there is no
  sampling over initial states, drivers, or shocks, and no p10/p50/p90
  aggregation anywhere in `services/simulation/`.
- No MECE layer: no issue-tree / mutual-exclusion / exhaustiveness code.
- State fields, thresholds (`simulation_branching.py:_STATE_POLICIES`),
  and action libraries are hardcoded per domain pack; the only user
  overrides are `configuration.initial_state` floats.

## 4. Debate flow

- Trigger: `POST /debates/trigger` → `services/debate/workflow.py`
  (command/observation contracts in `services/debate/contracts.py`).
- Panel: 9 built-in roles (`services/debate/roles.py:BUILT_IN_DEBATE_ROLES`):
  advocate, challenger, arbitrator, intel_analyst, geo_expert, econ_analyst,
  military_strategist, tech_foresight, social_impact. Agent definitions +
  prompts live in `services/agent_registry.py`; custom agents load from
  config (`services/debate/engines.py:load_custom_debate_agents`).
- Execution adapters: `LLMDebateAdapter` (`services/debate/llm.py`) for
  model-backed rounds; `HeuristicDebateAdapter`
  (`services/debate/engines.py`) builds deterministic full-panel rounds
  without any model provider.
- Quality: adjudication, claim/branch assessment, quality rules, revisions,
  reliability scores, structured dissent
  (`services/debate/adjudication.py`, `claim_assessment.py`,
  `branch_assessment.py`, `quality.py`, `_quality_rules.py`, `revisions.py`,
  `run_assessment.py`, `triggers.py`).
- Persistence: `DebateSessionRecord` / `DebateRoundRecord` /
  `DebateVerdictRecord` / `DebateVote` / `DebateInterruptRecord` /
  `DebateReliabilityScore` / `DebateStructuredDissent`
  (`domain/models.py:677-863`); replay via `services/debate_replay.py` and
  `api/routes/debate_replay.py`; interrupts via `debate_interrupt.py`.
- Output: verdict + decisive evidence + winning arguments + minority
  opinion; HTML report via `services/debate_html_report.py`.

## 5. Data-model summary

`src/planagent/domain/models.py` (1473 lines, `Base` at line 45). Groups:

| Group | Tables |
|---|---|
| Auth | `AuthUser`, `AuthRefreshToken`, `AuthRevokedToken` |
| Ingest / evidence | `IngestRun`, `RawSourceItem`, `SourceSnapshot`, `SourceHealth`, `NormalizedItem`, `EvidenceItem`, `Claim`, `ReviewItem`, `Signal`, `EventRecord`, `Trend`, `SourceCursorState`, `SourceChangeRecord`, `SourceTrustScore` |
| Knowledge graph | `KnowledgeGraphNode`, `KnowledgeGraphEdge`, `AnalysisCacheRecord` |
| Simulation | `SimulationRun` (domain_id, actor_template, tick_count, seed, configuration JSON), `StateSnapshotRecord`, `DecisionRecordRecord`, `GeoAssetRecord`, `ExternalShockRecord`, `ScenarioBranchRecord`, `ScenarioReplayPackageRecord`, `CompanyProfile`, `ForceProfile` |
| Debate | `DebateSessionRecord`, `DebateRoundRecord`, `DebateVerdictRecord`, `DebateVote`, `DebateInterruptRecord`, `DebateReliabilityScore`, `DebateStructuredDissent` |
| Decisions / strategy | `StrategicSession`, `UserDecision`, `StrategicBriefRecord`, `StrategicRunSnapshot`, `RecommendationVersion`, `DecisionOption`, `Hypothesis`, `GeneratedReport`, `EventArchive`, `DeadLetterEvent` |
| Monitoring / calibration | `WatchRule`, `CalibrationRecord`, `RuleAccuracy`, `PredictionCalibrationContext`, `JarvisRunRecord` |
| Prediction | `PredictionSeries`, `PredictionVersion`, `PredictionBacktestRecord`, `PredictionEvidenceLink`, `PredictionRevisionJob` |

Schema evolution: Alembic, 29 revisions in `migrations/versions/`
(`0001_phase1_bootstrap` … `0019_prediction_backtest_records`, incl.
`0011_decision_method`, `0012_decision_options_hypotheses`,
`0013_calibration_records`, `0014_knowledge_graph`). `db.py:init_models()`
only runs `create_all`; production deploys run `alembic upgrade head`.

## 6. Worker topology

One CLI, 10 worker classes (`src/planagent/worker_cli.py:build_worker`,
`src/planagent/workers/`):

| Compose service | CLI name | Class | Notes |
|---|---|---|---|
| worker-ingest | ingest-worker | `workers/ingest.py` | consumes raw.ingested |
| worker-knowledge | knowledge-worker | `workers/knowledge.py` | extraction → signals/trends |
| worker-graph | graph-worker | `workers/graph.py` | knowledge graph |
| worker-review | review-worker | `workers/review.py` | claim review |
| worker-simulation | simulation-worker | `workers/simulation.py` | queued simulation runs |
| worker-report | report-worker | `workers/report.py` | report generation |
| worker-watch | watch-ingest-worker | `workers/watch_ingest.py` | watch-rule ingest |
| worker-strategic | strategic-watch-worker | `workers/strategic_watch.py` | strategic refresh |
| worker-prediction | prediction-revision-worker | `workers/prediction_revision.py` | prediction revisions |
| worker-calibration | calibration-worker | `workers/calibration.py` | rule-accuracy reflux |

Workers share: settings, event bus, rule registry, OpenAI service
(`worker_cli.py`). Base class `workers/base.py:Worker` with
`WorkerDescription` (topics, consumer group). Each compose worker runs
`python -m planagent.worker_cli <name> --loop` from the same image as the
API (`docker-compose.yml`). In local dev, inline execution
(`inline_ingest_default` / `inline_simulation_default`,
`config/base.py:55-56`) bypasses workers entirely.

Event bus: Redis Streams in compose (`RedisStreamEventBus`,
`events/bus.py:203`, streams `stream:<topic>`, DLQ `stream:<topic>.dlq`,
consumer groups per worker); in-memory bus otherwise
(`InMemoryEventBus`, `events/bus.py:103`).

## 7. Config / env surface

- Loader: pydantic-settings, `.env` file, prefix `PLANAGENT_`, nested
  delimiter `_` (`config/base.py:14-21`). Full key list with comments:
  `.env.example` (source of truth for operators).
- Notable keys: `PLANAGENT_ENV`, `PLANAGENT_BIND_HOST` (loopback-only
  unless `PLANAGENT_REMOTE_ACCESS_ENABLED=true` + 32-byte
  `PLANAGENT_AUTH_SECRET_KEY`, enforced by a model validator in
  `config/base.py`), `PLANAGENT_DATABASE_URL` (SQLite default
  `sqlite+aiosqlite:///./planagent.db`; Postgres example commented),
  `PLANAGENT_REDIS_URL` / `PLANAGENT_EVENT_BUS_BACKEND`,
  `PLANAGENT_MINIO_*` (endpoint, keys, bucket `planagent-snapshots`),
  `PLANAGENT_INLINE_INGEST_DEFAULT` / `PLANAGENT_INLINE_SIMULATION_DEFAULT`,
  `PLANAGENT_OPENAI_*` (base key + per-purpose primary/extraction/report/
  x-search + per-debate-role keys), `PLANAGENT_ANTHROPIC_*`,
  `PLANAGENT_OPENAI_TIMEOUT_SECONDS`, `PLANAGENT_CORS_ORIGINS`,
  worker lease/retry keys, `PLANAGENT_MCP_*` (default disabled).
- Docker entry: `Dockerfile` (python:3.12-slim + weasyprint system libs,
  `pip install -e .`, uvicorn on 8000). `setup.sh` generates `.env`
  secrets and brings up compose; it requires Docker + an OpenAI key
  prompt at install time.
- CI (`.github/workflows/ci.yml`): backend job installs with
  `uv pip install -e '.[dev]' --system`, runs `ruff check`, `ruff format
  --check`, `mypy src/planagent/`, `python -m pytest -q`; frontend job
  runs `npm ci`, `npm run lint`, `npm test` (vitest), type check.

## 8. Where Sprint 1+ work lands (pointers, not design)

- MECE layer: new module under `services/` + new API routes; natural
  upstream of `POST /simulation/runs` (gate before run creation).
- Variable tables: replace hardcoded pack defaults
  (`simulation/domain_packs/*/pack.py`) and thresholds
  (`services/simulation_branching.py:_STATE_POLICIES`) with stored,
  editable templates; `SimulationRun.configuration` already carries
  `initial_state` overrides — extend that pattern.
- Distribution layer: wrap `_execute_run` (`services/simulation/engine.py`)
  in a sampling runner; aggregate `StateSnapshotRecord` /
  `DecisionRecordRecord` across runs; seed must be wired to an RNG first
  (see §3 gap).
- Robustness / calibration: extend `_generate_decision_options` and the
  calibration worker; `CalibrationRecord` / `RuleAccuracy` tables exist.
