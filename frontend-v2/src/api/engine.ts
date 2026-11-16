import { ApiError, api } from './client'
import type {
  AdvisoryBoardRequest,
  BootstrapRequest,
  BootstrapResult,
  CalibrationFitRead,
  DecideRequest,
  DecisionGatesRead,
  DecisionNarrativeListRead,
  DecisionNarrativeRead,
  DecompositionTree,
  DerivationRead,
  DeterminismRead,
  DirectionMappingCreate,
  DirectionMappingListRead,
  DirectionMappingRead,
  DirectionMappingUpdate,
  ExpectedShortfallRequest,
  ExpectedShortfallResult,
  FirewallRead,
  GateEvaluation,
  GateEvaluationRequest,
  GateRegistration,
  GateRegistrationRequest,
  LoopIterationRead,
  LoopEvaluationRead,
  LoopObservationCreate,
  LoopObservationRead,
  LoopTimelineRead,
  MeceProposalRead,
  MeceProposeRequest,
  MeceRunRead,
  MeceValidationResult,
  MonitoringCycleResult,
  MonteCarloRequest,
  NarrativeGenerateRequest,
  NarrativePolishRead,
  MonteCarloResult,
  MonteCarloTrialValues,
  PolicyFitRequest,
  ReplayResult,
  ResimulateRequest,
  RobustnessRead,
  RuleWeightFitRequest,
  SkillDeliberationListRead,
  SkillDeliberationRecord,
  StartIterationRequest,
  StrategyLoopCreate,
  StrategyLoopRead,
  StrategyTeamRequest,
  ThresholdSearchRequest,
  ThresholdSearchResult,
  TornadoRequest,
  TornadoResult,
  TriggerRegistration,
  TriggerRegistrationRequest,
  VariableRunRead,
  VariableSet,
  VariableTemplateCreate,
  VariableTemplateRead,
  VariableTemplateUpdate,
  VariableValidationResult,
  AutomotiveSplitStructureRead,
  AutomotiveTrajectoryRead,
  ExpectationCatalogEntry,
  PromptReportRead,
  SalesLayerRead,
  SalesLayerRequest,
  AdvanceRead,
  AuditEventRead,
  BoardRowRead,
  ChairBriefRead,
  ChairSynthesisRequest,
  FinalRowRead,
  FinalizeRead,
  ReportDetailRead,
  RoundRowRead,
  SeminarCreateRead,
  SeminarCreateRequest,
  SeminarDetailRead,
  SeminarReportSummary,
  SeminarSummaryRead,
  SynthesizeRead,
  SynthesizeRequest,
} from './engineTypes'

// ==================== 错误解析 ====================
//
// FastAPI wraps every error detail as `{"detail": ...}`. The Sprint 1–6
// endpoints use structured details (`{"code", "message"}`) for 400/502/
// 503 and plain strings for 404. `ApiError.message` is
// `API <status>: <body>`, so the code is recovered by parsing the body
// after the first ": ". The 503/502 distinction is a product
// requirement: 503 means "no LLM configured", 502 means "the LLM
// returned malformed output" — the cockpit must never conflate them.

export interface ApiErrorInfo {
  status: number | null
  code: string | null
  message: string
}

function readDetailBody(message: string): unknown {
  const marker = message.indexOf(': ')
  const body = marker >= 0 ? message.slice(marker + 2) : message
  try {
    return JSON.parse(body) as unknown
  } catch {
    return body
  }
}

/** The FastAPI `detail` payload of an ApiError, or the raw body when unshaped. */
function readErrorDetail(error: unknown): unknown {
  if (!(error instanceof ApiError)) return null
  const parsed = readDetailBody(error.message)
  if (parsed && typeof parsed === 'object' && 'detail' in parsed) {
    return (parsed as { detail: unknown }).detail
  }
  return parsed
}

export function parseApiError(error: unknown): ApiErrorInfo {
  if (error instanceof ApiError) {
    const detail = readErrorDetail(error)
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const record = detail as Record<string, unknown>
      const code = typeof record.code === 'string' ? record.code : null
      const message = typeof record.message === 'string' ? record.message : error.message
      return { status: error.status, code, message }
    }
    if (Array.isArray(detail)) {
      // FastAPI 422 shape errors: [{loc, msg, ...}] — join them readably
      // instead of dumping the raw body.
      const parts = detail.map((entry) => {
        if (entry && typeof entry === 'object') {
          const record = entry as Record<string, unknown>
          const loc = Array.isArray(record.loc) ? record.loc.join('.') : ''
          const msg = typeof record.msg === 'string' ? record.msg : JSON.stringify(entry)
          return loc ? `${loc}: ${msg}` : msg
        }
        return String(entry)
      })
      if (parts.length > 0) {
        return { status: error.status, code: null, message: parts.join('; ') }
      }
    }
    if (typeof detail === 'string' && detail.length > 0) {
      return { status: error.status, code: null, message: detail }
    }
    return { status: error.status, code: null, message: error.message }
  }
  return {
    status: null,
    code: null,
    message: error instanceof Error ? error.message : String(error),
  }
}

/**
 * Recover the structured validation result carried by a 400
 * `variable_validation_failed` error (`detail.validation`), so the
 * template editor can show the backend's issues inline. Returns null
 * for any other error shape — callers fall back to `parseApiError`.
 */
export function parseValidationResult(error: unknown): VariableValidationResult | null {
  const detail = readErrorDetail(error)
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null
  const validation = (detail as Record<string, unknown>).validation
  if (!validation || typeof validation !== 'object' || Array.isArray(validation)) return null
  const record = validation as Record<string, unknown>
  if (typeof record.is_valid !== 'boolean' || !Array.isArray(record.issues)) return null
  return validation as VariableValidationResult
}

/** True when the failure is the honest "no LLM configured" state. */
export function isLlmUnavailable(error: unknown): boolean {
  const info = parseApiError(error)
  return info.status === 503 && info.code === 'skill_llm_unavailable'
}

/** True when the failure is malformed LLM output (contract failure). */
export function isLlmContractFailure(error: unknown): boolean {
  const info = parseApiError(error)
  return info.status === 502 && info.code === 'skill_contract_failed'
}

// ==================== 缺失片段 ====================
//
// The fragment GETs (MECE, variables, ensemble, robustness) return 404
// when a run simply has no such fragment yet — that is an expected
// "not computed" state, not an error. `nullOn404` converts exactly
// that case to `null` so views can render an empty state; every other
// failure still throws.

export async function nullOn404<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

// ==================== Sprint 1 — MECE ====================
export const meceApi = {
  validate: (tree: DecompositionTree) =>
    api.post<MeceValidationResult>('/mece/validate', tree),
  getForRun: (runId: string) =>
    api.get<MeceRunRead>(`/runs/${encodeURIComponent(runId)}/mece`),
}

// ==================== Sprint 2 — 变量表 ====================
//
// Template deletion returns 204 with no body; it goes through the
// 204-safe `api.deleteNoContent` path (Sprint 12), never through the
// JSON-parsing `api.delete`. The backend refuses built-in templates
// with 400 and unknown ids with 404 — both surface via parseApiError.
export const variablesApi = {
  validate: (variableSet: VariableSet) =>
    api.post<VariableValidationResult>('/variables/validate', variableSet),
  listTemplates: (domainId?: string) =>
    api.get<VariableTemplateRead[]>(
      domainId ? `/variable-templates?domain_id=${encodeURIComponent(domainId)}` : '/variable-templates',
    ),
  getTemplate: (templateId: string) =>
    api.get<VariableTemplateRead>(`/variable-templates/${encodeURIComponent(templateId)}`),
  createTemplate: (payload: VariableTemplateCreate) =>
    api.post<VariableTemplateRead>('/variable-templates', payload),
  updateTemplate: (templateId: string, payload: VariableTemplateUpdate) =>
    api.put<VariableTemplateRead>(`/variable-templates/${encodeURIComponent(templateId)}`, payload),
  deleteTemplate: (templateId: string) =>
    api.deleteNoContent(`/variable-templates/${encodeURIComponent(templateId)}`),
  getForRun: (runId: string) =>
    api.get<VariableRunRead>(`/runs/${encodeURIComponent(runId)}/variables`),
}

// ==================== Sprint 3 — 分布层 + 确定性 ====================
export const distributionsApi = {
  runMonteCarlo: (runId: string, payload: MonteCarloRequest) =>
    api.post<MonteCarloResult>(`/runs/${encodeURIComponent(runId)}/monte-carlo`, payload),
  getMonteCarlo: (runId: string) =>
    api.get<MonteCarloResult>(`/runs/${encodeURIComponent(runId)}/monte-carlo`),
  getTrialValues: (runId: string) =>
    api.get<MonteCarloTrialValues>(`/runs/${encodeURIComponent(runId)}/monte-carlo/trial-values`),
  replay: (runId: string) =>
    api.post<ReplayResult>(`/runs/${encodeURIComponent(runId)}/replay`),
  getDeterminism: (runId: string) =>
    api.get<DeterminismRead>(`/runs/${encodeURIComponent(runId)}/determinism`),
}

// ==================== Sprint 4 — 稳健性 + 决策门 ====================
export const robustnessApi = {
  expectedShortfall: (runId: string, payload: ExpectedShortfallRequest) =>
    api.post<ExpectedShortfallResult>(
      `/runs/${encodeURIComponent(runId)}/robustness/expected-shortfall`,
      payload,
    ),
  tornado: (runId: string, payload: TornadoRequest) =>
    api.post<TornadoResult>(`/runs/${encodeURIComponent(runId)}/robustness/tornado`, payload),
  thresholdSearch: (runId: string, payload: ThresholdSearchRequest) =>
    api.post<ThresholdSearchResult>(
      `/runs/${encodeURIComponent(runId)}/robustness/threshold-search`,
      payload,
    ),
  bootstrap: (runId: string, payload: BootstrapRequest) =>
    api.post<BootstrapResult>(`/runs/${encodeURIComponent(runId)}/robustness/bootstrap`, payload),
  getAll: (runId: string) =>
    api.get<RobustnessRead>(`/runs/${encodeURIComponent(runId)}/robustness`),
  registerGates: (runId: string, payload: GateRegistrationRequest) =>
    api.post<GateRegistration>(`/runs/${encodeURIComponent(runId)}/decision-gates`, payload),
  getGates: (runId: string) =>
    api.get<DecisionGatesRead>(`/runs/${encodeURIComponent(runId)}/decision-gates`),
  evaluateGates: (runId: string, payload: GateEvaluationRequest) =>
    api.post<GateEvaluation>(`/runs/${encodeURIComponent(runId)}/decision-gates/evaluate`, payload),
}

// ==================== Sprint 5 — 校准 + 防火墙 ====================
export const calibrationApi = {
  getFirewall: (runId: string) =>
    api.get<FirewallRead>(`/runs/${encodeURIComponent(runId)}/firewall`),
  fitPolicy: (payload: PolicyFitRequest) =>
    api.post<CalibrationFitRead>('/calibration/policy-fit', payload),
  fitRuleWeights: (payload: RuleWeightFitRequest) =>
    api.post<CalibrationFitRead>('/calibration/rule-weight-fit', payload),
  listFits: (params?: { kind?: string; domain_id?: string; limit?: number; offset?: number }) => {
    const search = new URLSearchParams()
    if (params?.kind) search.set('kind', params.kind)
    if (params?.domain_id) search.set('domain_id', params.domain_id)
    if (params?.limit !== undefined) search.set('limit', String(params.limit))
    if (params?.offset !== undefined) search.set('offset', String(params.offset))
    const query = search.toString()
    return api.get<CalibrationFitRead[]>(`/calibration/fits${query ? `?${query}` : ''}`)
  },
  getFit: (fitId: string) =>
    api.get<CalibrationFitRead>(`/calibration/fits/${encodeURIComponent(fitId)}`),
  applyRuleWeights: (fitId: string) =>
    api.post<CalibrationFitRead>(`/calibration/fits/${encodeURIComponent(fitId)}/apply-rule-weights`),
}

// ==================== Sprint 9 — 活战略循环 ====================
//
// Every loop action is explicit: the UI never auto-evaluates,
// auto-re-simulates, or auto-decides. Errors are the backend's
// structured 400 codes (loop_invalid_state, loop_cutoff_must_advance,
// ...) surfaced via parseApiError; a refused re-simulation surfaces
// the same gate codes as a refused hand-created run.
export const loopsApi = {
  createLoop: (payload: StrategyLoopCreate) =>
    api.post<StrategyLoopRead>('/loops', payload),
  listLoops: (params?: { limit?: number; offset?: number }) => {
    const search = new URLSearchParams()
    if (params?.limit !== undefined) search.set('limit', String(params.limit))
    if (params?.offset !== undefined) search.set('offset', String(params.offset))
    const query = search.toString()
    return api.get<StrategyLoopRead[]>(`/loops${query ? `?${query}` : ''}`)
  },
  getLoop: (loopId: string) =>
    api.get<StrategyLoopRead>(`/loops/${encodeURIComponent(loopId)}`),
  getTimeline: (loopId: string) =>
    api.get<LoopTimelineRead>(`/loops/${encodeURIComponent(loopId)}/timeline`),
  recordObservation: (loopId: string, payload: LoopObservationCreate) =>
    api.post<LoopObservationRead>(`/loops/${encodeURIComponent(loopId)}/observations`, payload),
  registerTriggers: (loopId: string, payload: TriggerRegistrationRequest) =>
    api.post<TriggerRegistration>(`/loops/${encodeURIComponent(loopId)}/triggers`, payload),
  startIteration: (loopId: string, payload: StartIterationRequest) =>
    api.post<LoopIterationRead>(`/loops/${encodeURIComponent(loopId)}/iterations`, payload),
  getIteration: (loopId: string, iterationId: string) =>
    api.get<LoopIterationRead>(
      `/loops/${encodeURIComponent(loopId)}/iterations/${encodeURIComponent(iterationId)}`,
    ),
  evaluateIteration: (loopId: string, iterationId: string) =>
    api.post<LoopIterationRead>(
      `/loops/${encodeURIComponent(loopId)}/iterations/${encodeURIComponent(iterationId)}/evaluate`,
    ),
  resimulateIteration: (loopId: string, iterationId: string, payload: Partial<ResimulateRequest>) =>
    api.post<LoopIterationRead>(
      `/loops/${encodeURIComponent(loopId)}/iterations/${encodeURIComponent(iterationId)}/resimulate`,
      payload,
    ),
  compareIteration: (loopId: string, iterationId: string) =>
    api.post<LoopIterationRead>(
      `/loops/${encodeURIComponent(loopId)}/iterations/${encodeURIComponent(iterationId)}/compare`,
    ),
  decideIteration: (loopId: string, iterationId: string, payload: DecideRequest) =>
    api.post<LoopIterationRead>(
      `/loops/${encodeURIComponent(loopId)}/iterations/${encodeURIComponent(iterationId)}/decide`,
      payload,
    ),
  listEvaluations: (loopId: string, params?: { limit?: number; offset?: number }) => {
    const search = new URLSearchParams()
    if (params?.limit !== undefined) search.set('limit', String(params.limit))
    if (params?.offset !== undefined) search.set('offset', String(params.offset))
    const query = search.toString()
    return api.get<LoopEvaluationRead[]>(
      `/loops/${encodeURIComponent(loopId)}/evaluations${query ? `?${query}` : ''}`,
    )
  },
  runMonitoringCycle: () => api.post<MonitoringCycleResult>('/loops/monitoring/evaluate'),
}

// ==================== Sprint 6 — 技能 deliberation ====================
export const skillsApi = {
  runStrategyTeam: (runId: string, payload: StrategyTeamRequest) =>
    api.post<SkillDeliberationRecord>(
      `/runs/${encodeURIComponent(runId)}/skills/strategy-team`,
      payload,
    ),
  runAdvisoryBoard: (runId: string, payload: AdvisoryBoardRequest) =>
    api.post<SkillDeliberationRecord>(
      `/runs/${encodeURIComponent(runId)}/skills/advisory-board`,
      payload,
    ),
  listDeliberations: (runId: string) =>
    api.get<SkillDeliberationListRead>(`/runs/${encodeURIComponent(runId)}/skills/deliberations`),
  proposeMece: (payload: MeceProposeRequest) =>
    api.post<MeceProposalRead>('/mece/propose', payload),
}


// ==================== Sprint 13 — 决策方向简报 ====================
export const narrativesApi = {
  generate: (runId: string, payload: NarrativeGenerateRequest) =>
    api.post<DecisionNarrativeRead>(
      `/runs/${encodeURIComponent(runId)}/narratives`,
      payload,
    ),
  list: (runId: string) =>
    api.get<DecisionNarrativeListRead>(`/runs/${encodeURIComponent(runId)}/narratives`),
  get: (runId: string, narrativeId: string) =>
    api.get<DecisionNarrativeRead>(
      `/runs/${encodeURIComponent(runId)}/narratives/${encodeURIComponent(narrativeId)}`,
    ),
  polish: (runId: string, narrativeId: string) =>
    api.post<NarrativePolishRead>(
      `/runs/${encodeURIComponent(runId)}/narratives/${encodeURIComponent(narrativeId)}/polish`,
    ),
}

// ==================== Sprint 14 — 方向推导 + 已存映射 ====================
export const directionsApi = {
  derive: (runId: string) =>
    api.post<DerivationRead>(`/runs/${encodeURIComponent(runId)}/directions/derive`),
  listMappings: (runId: string) =>
    api.get<DirectionMappingListRead>(
      `/runs/${encodeURIComponent(runId)}/directions/mappings`,
    ),
  createMapping: (runId: string, payload: DirectionMappingCreate) =>
    api.post<DirectionMappingRead>(
      `/runs/${encodeURIComponent(runId)}/directions/mappings`,
      payload,
    ),
  updateMapping: (runId: string, mappingId: string, payload: DirectionMappingUpdate) =>
    api.put<DirectionMappingRead>(
      `/runs/${encodeURIComponent(runId)}/directions/mappings/${encodeURIComponent(mappingId)}`,
      payload,
    ),
  deleteMapping: (runId: string, mappingId: string) =>
    api.deleteNoContent(
      `/runs/${encodeURIComponent(runId)}/directions/mappings/${encodeURIComponent(mappingId)}`,
    ),
}

// ==================== Phase 2 — 汽车包 ====================
export const automotiveApi = {
  getTrajectory: (runId: string) =>
    api.get<AutomotiveTrajectoryRead>(
      `/runs/${encodeURIComponent(runId)}/automotive/trajectory`,
    ),
  getSplitStructure: (runId: string) =>
    api.get<AutomotiveSplitStructureRead>(
      `/runs/${encodeURIComponent(runId)}/automotive/split-structure`,
    ),
  computeSalesLayer: (runId: string, payload: SalesLayerRequest) =>
    api.post<SalesLayerRead>(
      `/runs/${encodeURIComponent(runId)}/automotive/sales-layer`,
      payload,
    ),
  evaluatePrompts: (payload: { split_structure: unknown; dms_mandate_on?: boolean | null }) =>
    api.post<PromptReportRead>('/automotive/prompts/evaluate', payload),
  getExpectations: () => api.get<ExpectationCatalogEntry[]>('/automotive/expectations'),
}

// ==================== Sprint 20 — 多模型研讨 ====================
// Endpoint paths + shapes from src/planagent/api/routes/seminars.py
// (S16–S18). Synthesize answers one of two shapes: a report summary
// in model-chair mode (201), a stored chair brief in agent-chair
// mode (200) — callers tell them apart by `brief_version`.
export const seminarApi = {
  createSeminar: (runId: string, payload: SeminarCreateRequest) =>
    api.post<SeminarCreateRead>(`/runs/${encodeURIComponent(runId)}/seminars`, payload),
  listRunSeminars: (runId: string) =>
    api.get<SeminarSummaryRead[]>(`/runs/${encodeURIComponent(runId)}/seminars`),
  getDetail: (seminarId: string) =>
    api.get<SeminarDetailRead>(`/seminars/${encodeURIComponent(seminarId)}`),
  advance: (seminarId: string) =>
    api.post<AdvanceRead>(`/seminars/${encodeURIComponent(seminarId)}/advance`),
  finalize: (seminarId: string) =>
    api.post<FinalizeRead>(`/seminars/${encodeURIComponent(seminarId)}/finalize`),
  synthesize: (seminarId: string, payload: SynthesizeRequest) =>
    api.post<SynthesizeRead | ChairBriefRead>(
      `/seminars/${encodeURIComponent(seminarId)}/synthesize`,
      payload,
    ),
  submitChairSynthesis: (seminarId: string, payload: ChairSynthesisRequest) =>
    api.post<SynthesizeRead>(
      `/seminars/${encodeURIComponent(seminarId)}/chair-synthesis`,
      payload,
    ),
  listBoard: (seminarId: string) =>
    api.get<BoardRowRead[]>(`/seminars/${encodeURIComponent(seminarId)}/board`),
  listRounds: (seminarId: string) =>
    api.get<RoundRowRead[]>(`/seminars/${encodeURIComponent(seminarId)}/rounds`),
  listFinals: (seminarId: string) =>
    api.get<FinalRowRead[]>(`/seminars/${encodeURIComponent(seminarId)}/finals`),
  listReports: (seminarId: string) =>
    api.get<SeminarReportSummary[]>(`/seminars/${encodeURIComponent(seminarId)}/reports`),
  getReport: (seminarId: string, version: number) =>
    api.get<ReportDetailRead>(
      `/seminars/${encodeURIComponent(seminarId)}/reports/${version}`,
    ),
  listAudit: (seminarId: string, params?: { kind?: string; model_id?: string }) => {
    const search = new URLSearchParams()
    if (params?.kind) search.set('kind', params.kind)
    if (params?.model_id) search.set('model_id', params.model_id)
    const query = search.toString()
    return api.get<AuditEventRead[]>(
      `/seminars/${encodeURIComponent(seminarId)}/audit${query ? `?${query}` : ''}`,
    )
  },
}
