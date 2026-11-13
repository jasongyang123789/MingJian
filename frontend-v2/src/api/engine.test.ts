import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from './client'
import {
  calibrationApi,
  distributionsApi,
  isLlmContractFailure,
  isLlmUnavailable,
  meceApi,
  nullOn404,
  parseApiError,
  robustnessApi,
  skillsApi,
  variablesApi,
} from './engine'
import type { DecompositionTree, VariableSet } from './engineTypes'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockFetch(response: Response) {
  const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(response)
  return fetchMock
}

function lastCall(fetchMock: ReturnType<typeof mockFetch>) {
  const call = fetchMock.mock.calls.at(-1)
  if (!call) throw new Error('fetch was not called')
  const [input, init] = call
  return { url: String(input), init }
}

const TREE: DecompositionTree = {
  topic: 'Launch?',
  root: { name: 'Launch', scope: ['demand'], children: [{ name: 'Demand', scope: ['demand'], children: [] }] },
}

const VARIABLE_SET: VariableSet = {
  name: 'case',
  variables: [
    {
      id: 'cash',
      unit: 'k',
      distribution: { type: 'fixed', value: 100, mean: null, std: null, min: null, mode: null, max: null, p: null },
      evidence_ref: 'estimate: founder',
      description: '',
      scope_tags: [],
    },
  ],
  formulas: [],
  internal: {},
}

describe('engine API clients', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('posts MECE validation to /mece/validate with the tree body', async () => {
    const fetchMock = mockFetch(jsonResponse({ is_mece: true, checks: [], issues: [], scope_tag_count: 1, branch_count: 2 }))
    const result = await meceApi.validate(TREE)
    expect(result.is_mece).toBe(true)
    const { url, init } = lastCall(fetchMock)
    expect(url).toBe('/api/mece/validate')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual(TREE)
  })

  it('fetches the stored MECE fragment for a run', async () => {
    const fetchMock = mockFetch(jsonResponse({ run_id: 'r1', decomposition: TREE, validation: { is_mece: true, checks: [], issues: [], scope_tag_count: 1, branch_count: 2 } }))
    await meceApi.getForRun('r1')
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/mece')
  })

  it('validates variable sets and lists templates with an optional domain filter', async () => {
    const fetchMock = mockFetch(jsonResponse({ is_valid: true, variable_count: 1, checks: [], issues: [] }))
    await variablesApi.validate(VARIABLE_SET)
    expect(lastCall(fetchMock).url).toBe('/api/variables/validate')

    mockFetch(jsonResponse([]))
    await variablesApi.listTemplates('corporate')
    expect(lastCall(fetchMock).url).toBe('/api/variable-templates?domain_id=corporate')

    mockFetch(jsonResponse([]))
    await variablesApi.listTemplates()
    expect(lastCall(fetchMock).url).toBe('/api/variable-templates')
  })

  it('creates and updates variable templates', async () => {
    const fetchMock = mockFetch(jsonResponse({ id: 't1' }))
    await variablesApi.createTemplate({ name: 'T', domain_id: 'corporate', description: '', state_fields: [], policies: {}, variables: [], formulas: [], internal: {} })
    expect(lastCall(fetchMock).url).toBe('/api/variable-templates')
    expect(lastCall(fetchMock).init?.method).toBe('POST')

    mockFetch(jsonResponse({ id: 't1' }))
    await variablesApi.updateTemplate('t1', { name: 'T2' })
    const updated = lastCall(fetchMock)
    expect(updated.url).toBe('/api/variable-templates/t1')
    expect(updated.init?.method).toBe('PUT')
  })

  it('runs and reads Monte Carlo ensembles, replay, and determinism', async () => {
    const fetchMock = mockFetch(jsonResponse({ ensemble_id: 'e1' }))
    await distributionsApi.runMonteCarlo('r1', { trials: 50, seed: 42, metric: 'cash', loss_threshold: 0, strategy_levers: {} })
    const ran = lastCall(fetchMock)
    expect(ran.url).toBe('/api/runs/r1/monte-carlo')
    expect(ran.init?.method).toBe('POST')
    expect(JSON.parse(String(ran.init?.body)).seed).toBe(42)

    mockFetch(jsonResponse({ ensemble_id: 'e1' }))
    await distributionsApi.getMonteCarlo('r1')
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/monte-carlo')

    mockFetch(jsonResponse({ match: true }))
    await distributionsApi.replay('r1')
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/replay')

    mockFetch(jsonResponse({ run_id: 'r1' }))
    await distributionsApi.getDeterminism('r1')
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/determinism')
  })

  it('posts the four robustness analyses and reads the stored bundle', async () => {
    const fetchMock = mockFetch(jsonResponse({ run_id: 'r1' }))
    await robustnessApi.expectedShortfall('r1', { alpha: 0.05, tail: 'lower' })
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/robustness/expected-shortfall')

    mockFetch(jsonResponse({ run_id: 'r1' }))
    await robustnessApi.tornado('r1', { low_quantile: 0.1, high_quantile: 0.9, seed: null, variables: null })
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/robustness/tornado')

    mockFetch(jsonResponse({ run_id: 'r1' }))
    await robustnessApi.thresholdSearch('r1', { variable: 'cash', mode: 'p_loss', target: 0.3, direction: 'increasing', bounds: null, trials_per_evaluation: 20, max_iterations: 8, tolerance: 0.001, seed: null, loss_threshold: null })
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/robustness/threshold-search')

    mockFetch(jsonResponse({ run_id: 'r1' }))
    await robustnessApi.bootstrap('r1', { statistics: ['mean'], draws: 1000, seed: null, level: 0.9 })
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/robustness/bootstrap')

    mockFetch(jsonResponse({ run_id: 'r1' }))
    await robustnessApi.getAll('r1')
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/robustness')
  })

  it('registers, reads, and evaluates decision gates', async () => {
    const gate = { name: 'g', metric: 'p50' as const, operator: '>=' as const, threshold: 0, arm: 'baseline' as const, alpha: 0.05 }
    const fetchMock = mockFetch(jsonResponse({ id: 'reg1' }))
    await robustnessApi.registerGates('r1', { gates: [gate], supersedes: null })
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/decision-gates')

    mockFetch(jsonResponse({ run_id: 'r1', registrations: [], evaluations: [] }))
    await robustnessApi.getGates('r1')
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/decision-gates')

    mockFetch(jsonResponse({ id: 'ev1' }))
    await robustnessApi.evaluateGates('r1', { registration_id: null })
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/decision-gates/evaluate')
  })

  it('reads the firewall audit and calibration fits', async () => {
    const fetchMock = mockFetch(jsonResponse({ run_id: 'r1' }))
    await calibrationApi.getFirewall('r1')
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/firewall')

    mockFetch(jsonResponse([]))
    await calibrationApi.listFits({ kind: 'policy', domain_id: 'corporate', limit: 10, offset: 5 })
    expect(lastCall(fetchMock).url).toBe('/api/calibration/fits?kind=policy&domain_id=corporate&limit=10&offset=5')

    mockFetch(jsonResponse({ id: 'f1' }))
    await calibrationApi.getFit('f1')
    expect(lastCall(fetchMock).url).toBe('/api/calibration/fits/f1')

    mockFetch(jsonResponse({ id: 'f1' }))
    await calibrationApi.fitPolicy({ template_id: 't1', ridge_strength: 1, seed: 7, bootstrap_draws: 1000, level: 0.95, source_run_ids: null })
    expect(lastCall(fetchMock).url).toBe('/api/calibration/policy-fit')

    mockFetch(jsonResponse({ id: 'f1' }))
    await calibrationApi.fitRuleWeights({ domain_id: 'corporate', metric: 'cash', ridge_strength: 1, seed: 7, bootstrap_draws: 1000, level: 0.95, source_run_ids: null })
    expect(lastCall(fetchMock).url).toBe('/api/calibration/rule-weight-fit')

    mockFetch(jsonResponse({ id: 'f1' }))
    await calibrationApi.applyRuleWeights('f1')
    expect(lastCall(fetchMock).url).toBe('/api/calibration/fits/f1/apply-rule-weights')
  })

  it('runs both deliberation pipelines and lists stored deliberations', async () => {
    const fetchMock = mockFetch(jsonResponse({ id: 'd1' }))
    await skillsApi.runStrategyTeam('r1', { topic: 'Launch?', decision_question: '', context_lines: [], mode: 'standard', output_language: 'English', include_premortem: true, failure_date: 'one year from now' })
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/skills/strategy-team')

    mockFetch(jsonResponse({ id: 'd2' }))
    await skillsApi.runAdvisoryBoard('r1', { decision: 'Launch?', options: ['A'], context_lines: [], mode: 'standard', output_language: 'English' })
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/skills/advisory-board')

    mockFetch(jsonResponse({ run_id: 'r1', deliberations: [] }))
    await skillsApi.listDeliberations('r1')
    expect(lastCall(fetchMock).url).toBe('/api/runs/r1/skills/deliberations')

    mockFetch(jsonResponse({ proposal: TREE }))
    await skillsApi.proposeMece({ topic: 'Launch?', context_lines: [], suggested_dimensions: [], existing_tree: null, output_language: 'English' })
    expect(lastCall(fetchMock).url).toBe('/api/mece/propose')
  })

  it('propagates API errors with their status', async () => {
    mockFetch(jsonResponse({ detail: 'Simulation run r1 was not found.' }, 404))
    await expect(meceApi.getForRun('r1')).rejects.toMatchObject({ status: 404 })

    mockFetch(jsonResponse({ detail: { code: 'skills_requires_completed_run', message: 'Run is not completed.' } }, 400))
    await expect(
      skillsApi.runStrategyTeam('r1', { topic: 'T', decision_question: '', context_lines: [], mode: 'standard', output_language: 'English', include_premortem: true, failure_date: 'one year from now' }),
    ).rejects.toMatchObject({ status: 400 })
  })
})

describe('parseApiError', () => {
  it('recovers status + code + message from structured FastAPI details', () => {
    const unavailable = new ApiError(503, JSON.stringify({ detail: { code: 'skill_llm_unavailable', message: 'No LLM is configured for target primary.' } }))
    expect(parseApiError(unavailable)).toEqual({
      status: 503,
      code: 'skill_llm_unavailable',
      message: 'No LLM is configured for target primary.',
    })
    expect(isLlmUnavailable(unavailable)).toBe(true)
    expect(isLlmContractFailure(unavailable)).toBe(false)

    const contract = new ApiError(502, JSON.stringify({
      detail: { code: 'skill_contract_failed', message: 'bad output', template_id: 'mckinsey.synthesize', contract_version: '1' },
    }))
    expect(parseApiError(contract)).toEqual({
      status: 502,
      code: 'skill_contract_failed',
      message: 'bad output',
    })
    expect(isLlmContractFailure(contract)).toBe(true)
    expect(isLlmUnavailable(contract)).toBe(false)
  })

  it('handles plain-string details and non-JSON bodies', () => {
    const notFound = new ApiError(404, JSON.stringify({ detail: 'Simulation run r1 was not found.' }))
    expect(parseApiError(notFound)).toEqual({ status: 404, code: null, message: 'Simulation run r1 was not found.' })

    const plain = new ApiError(500, 'Internal Server Error')
    expect(parseApiError(plain).status).toBe(500)
    expect(parseApiError(plain).code).toBeNull()
  })

  it('handles plain errors and non-error values', () => {
    expect(parseApiError(new Error('boom'))).toEqual({ status: null, code: null, message: 'boom' })
    expect(parseApiError('nope')).toEqual({ status: null, code: null, message: 'nope' })
    expect(isLlmUnavailable(new Error('boom'))).toBe(false)
  })
})

describe('nullOn404', () => {
  it('converts a 404 into null and rethrows anything else', async () => {
    await expect(nullOn404(Promise.reject(new ApiError(404, 'missing')))).resolves.toBeNull()
    await expect(nullOn404(Promise.reject(new ApiError(503, 'unavailable')))).rejects.toMatchObject({ status: 503 })
    await expect(nullOn404(Promise.reject(new Error('boom')))).rejects.toThrow('boom')
    await expect(nullOn404(Promise.resolve(7))).resolves.toBe(7)
  })
})
