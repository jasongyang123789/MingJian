import { ApiError, api } from './client'
import type {
  AdvisoryBoardRequest,
  BootstrapRequest,
  BootstrapResult,
  CalibrationFitRead,
  DecisionGatesRead,
  DecompositionTree,
  DeterminismRead,
  ExpectedShortfallRequest,
  ExpectedShortfallResult,
  FirewallRead,
  GateEvaluation,
  GateEvaluationRequest,
  GateRegistration,
  GateRegistrationRequest,
  MeceProposalRead,
  MeceProposeRequest,
  MeceRunRead,
  MeceValidationResult,
  MonteCarloRequest,
  MonteCarloResult,
  PolicyFitRequest,
  ReplayResult,
  RobustnessRead,
  RuleWeightFitRequest,
  SkillDeliberationListRead,
  SkillDeliberationRecord,
  StrategyTeamRequest,
  ThresholdSearchRequest,
  ThresholdSearchResult,
  TornadoRequest,
  TornadoResult,
  VariableRunRead,
  VariableSet,
  VariableTemplateCreate,
  VariableTemplateRead,
  VariableTemplateUpdate,
  VariableValidationResult,
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

export function parseApiError(error: unknown): ApiErrorInfo {
  if (error instanceof ApiError) {
    const parsed = readDetailBody(error.message)
    const detail =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? (parsed as { detail: unknown }).detail
        : parsed
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      const record = detail as Record<string, unknown>
      const code = typeof record.code === 'string' ? record.code : null
      const message = typeof record.message === 'string' ? record.message : error.message
      return { status: error.status, code, message }
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
// No delete client: template deletion returns 204 with no body, and the
// shared `api` transport always parses a JSON body. No Sprint 7 view
// deletes templates; adding a 204-safe path belongs to a template
// editing sprint, not to this read-focused cockpit.
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
  getForRun: (runId: string) =>
    api.get<VariableRunRead>(`/runs/${encodeURIComponent(runId)}/variables`),
}

// ==================== Sprint 3 — 分布层 + 确定性 ====================
export const distributionsApi = {
  runMonteCarlo: (runId: string, payload: MonteCarloRequest) =>
    api.post<MonteCarloResult>(`/runs/${encodeURIComponent(runId)}/monte-carlo`, payload),
  getMonteCarlo: (runId: string) =>
    api.get<MonteCarloResult>(`/runs/${encodeURIComponent(runId)}/monte-carlo`),
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
