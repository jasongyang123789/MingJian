import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import SeminarDetail from './SeminarDetail'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const CONFIG = {
  pipeline: 'strategy_team',
  mode: 'standard',
  max_rounds: 3,
  quiet_rounds: 2,
  snapshot_policy: 'latest_per_model',
  max_concurrency: 3,
  output_language: 'English',
  include_premortem: true,
  failure_date: 'one year from now',
  decision_question: '',
  options: [],
  context_lines: [],
  chair_participates: false,
  chair_mode: 'model',
  max_stage_calls: 200,
  max_tokens: 1000000,
  max_retries: 2,
  retry_backoff_seconds: 1,
  near_duplicate_threshold: 0.8,
}

const VERDICT = {
  recommendation: 'Phase the rollout.',
  ranked_alternatives: ['Phased rollout', 'Full launch'],
  confidence: 'high',
  key_evidence: ['Runway covers 14 months.'],
  load_bearing_assumptions: ['Churn stays under 5%.'],
  kill_criteria: ['Churn exceeds 8%.'],
  dissent_held: ['The bull case ignores pricing pressure.'],
  rounds_summary: 'Moved from full launch to phased after round 2.',
  board_snapshot_seq: 3,
}

const STAGE = {
  stage: 'final_verdict',
  template_id: 'seminar.final_verdict',
  template_version: '1',
  contract_version: '1',
  output: {},
  model: 'model-a',
  usage: { total_tokens: 15 },
  duration_ms: 800,
  attempts: 1,
}

function detailFixture(chairMode: 'model' | 'agent') {
  return {
    seminar_id: 'sem-1',
    run_id: 'run-1',
    topic: 'Should we launch in Q3?',
    status: 'collecting',
    case_snapshot_hash: 'sha256:abcdef0123456789',
    roster: [
      {
        model_id: 'model-a',
        endpoint: { target: 'primary' },
        temperature: 0.3,
        timeout_seconds: 180,
        max_rounds: null,
        role: 'participant',
      },
      {
        model_id: 'model-b',
        endpoint: { target: 'primary' },
        temperature: 0.3,
        timeout_seconds: 180,
        max_rounds: null,
        role: 'participant',
      },
    ],
    config: { ...CONFIG, chair_mode: chairMode },
    chair_model: {
      model_id: chairMode === 'agent' ? 'glint-agent' : 'chair',
      endpoint: { target: 'primary' },
      temperature: 0.3,
      timeout_seconds: 180,
    },
    per_model: [
      { model_id: 'model-a', status: 'final', rounds: 2, has_final: true, latest_board_seq: 3 },
      { model_id: 'model-b', status: 'final', rounds: 2, has_final: true, latest_board_seq: 4 },
    ],
    board_publications: 4,
    board_latest_seq: 4,
    finals_count: 2,
    reports: [
      {
        version: 1,
        partial: false,
        production_path: 'chair',
        cluster_production: 'llm',
        report_hash: 'sha256:rep1',
        chair_model_id: 'chair',
      },
      {
        version: 2,
        partial: false,
        production_path: 'chair',
        cluster_production: 'llm',
        report_hash: 'sha256:rep2',
        chair_model_id: 'chair',
      },
    ],
    budgets: {
      max_stage_calls: 200,
      stage_calls_used: 50,
      stage_calls_remaining: 150,
      max_tokens: 1000000,
      tokens_used: 360,
      tokens_remaining: 999640,
    },
    diagnosis: {
      error_counts: { contract: 1 },
      total_tokens: 360,
      total_prompt_tokens: 200,
      total_completion_tokens: 160,
      total_duration_ms: 12500,
      stage_calls: 50,
      stage_call_attempts: 52,
      retries: 2,
      fallbacks: 1,
      queue_waits: 0,
    },
  }
}

const BOARD = [
  {
    id: 'b1',
    seminar_id: 'sem-1',
    seq: 1,
    model_id: 'model-a',
    round_no: 1,
    digest: {
      model_id: 'model-a',
      round_no: 1,
      recommendation: 'Launch now.',
      confidence: 'medium',
      key_arguments: ['Demand is proven.'],
      kill_criteria: [],
      changes: [],
      reflection_missing: false,
      board_snapshot_seq: 0,
    },
  },
]

const ROUNDS = [
  {
    id: 'r1',
    seminar_id: 'sem-1',
    model_id: 'model-a',
    round_no: 1,
    board_snapshot_seq: 0,
    stages: [STAGE],
    reflection: null,
    reflection_stage: null,
    status: 'completed',
    error: null,
  },
]

const FINALS = [
  {
    id: 'f1',
    seminar_id: 'sem-1',
    model_id: 'model-a',
    verdict: VERDICT,
    stage: STAGE,
    board_snapshot_seq: 3,
    status: 'final',
  },
]

const AUDIT = [
  {
    id: 'e1',
    seminar_id: 'sem-1',
    seq: 1,
    model_id: 'model-a',
    stage: 'mckinsey.intake_classify',
    kind: 'retry',
    detail: { attempt: 1, next_attempt: 2, backoff_seconds: 1, error_kind: 'timeout' },
    round_no: 1,
    stage_call_id: 'call-1',
    created_at: '2026-11-16T07:00:00Z',
  },
]

function reportDocument(version: number, recommendation: string) {
  return {
    header: {
      seminar_id: 'sem-1',
      run_id: 'run-1',
      topic: 'Should we launch in Q3?',
      version,
      partial: false,
      chair_model_id: 'chair',
      chair_mode: 'model',
      chair_participates: false,
      production_path: 'chair',
      cluster_production: 'llm',
      report_hash: `sha256:rep${version}`,
      finals_used: 2,
      roster_size: 2,
      absent_models: [],
    },
    unified_recommendation: { text: recommendation, basis: 'chair_judgment', provenance: 'deliberated' },
    agreement: {
      chair_level: 'moderate',
      chair_provenance: 'deliberated',
      computed: { n_models: 2, pairs_total: 1, pairs_agreeing: 1, rate: 1 },
      computed_provenance: 'computed',
      note: 'Side by side.',
    },
    canonical_claims: { claims: [], merge_map: {}, provenance: 'deliberated', production: 'llm' },
    disagreements: { items: [], count: 0, provenance: 'computed', note: 'None.' },
    alternatives: {
      borda: { method: 'borda', n_models: 2, totals: { A: 3 }, ranked: ['A'] },
      borda_provenance: 'computed',
      chair_ranked: ['A'],
      aggregation_rule: 'rule',
      chair_provenance: 'deliberated',
    },
    key_evidence: { items: [], provenance: 'deliberated' },
    kill_criteria: { items: [], provenance: 'deliberated' },
    minority_report: { text: '', provenance: 'deliberated', verbatim: true },
    rounds_evolution: [],
    open_questions: { items: [], provenance: 'deliberated' },
    chair_notes: { text: '', provenance: 'deliberated' },
    chair_synthesis: null,
    computed_metrics: {
      recommendation_agreement: { n_models: 2, pairs_total: 1, pairs_agreeing: 1, rate: 1 },
      confidence_distribution: { low: 0, medium: 1, high: 1 },
      borda: { method: 'borda', n_models: 2, totals: { A: 3 }, ranked: ['A'] },
      dedup: {
        original_items: 2,
        canonical_claims: 0,
        exact_duplicate_groups: 0,
        semantic_merge_groups: 0,
        cluster_production: 'llm',
      },
      disagreement_count: 0,
      rounds: { per_model: {}, total_rounds: 4 },
      finals_used: 2,
      roster_size: 2,
      absent_models: [],
    },
    audit_appendix: {
      case_snapshot_hash: 'sha256:abc',
      cluster_stage: null,
      synthesis_stage: null,
      verdict_stages: [],
      round_stage_counts: {},
      board_seq_range: [1, 4],
      board_publications: 4,
      model_configs: [],
      chair_config: {},
      token_usage: 'Not recorded.',
    },
  }
}

const BRIEF = {
  seminar_id: 'sem-1',
  brief_version: 1,
  brief_hash: 'sha256:briefhash',
  topic: 'Should we launch in Q3?',
  status: 'collecting',
  chair_mode: 'agent',
  chair_model_id: 'glint-agent',
  prepass: {
    items: [
      {
        item_id: 'I1',
        model_id: 'model-a',
        round_no: 2,
        field: 'key_evidence',
        text: 'Demand grows.',
        normalized_text: 'demand grows',
      },
    ],
    exact_groups: [['I1']],
    exact_duplicate_groups: 0,
    near_duplicate_groups: [],
    near_duplicate_group_count: 0,
    near_duplicate_threshold: 0.8,
    item_count: 1,
  },
  deterministic_clusters: {
    claims: [
      {
        claim: 'Demand grows.',
        sources: [
          {
            item_id: 'I1',
            model_id: 'model-a',
            round_no: 2,
            field: 'key_evidence',
            stance: 'support',
            original_text: 'Demand grows.',
          },
        ],
        merge_map: ['I1'],
      },
    ],
    disagreements: [],
    merge_map: { I1: 0 },
    prepass: {},
    production: 'deterministic_prepass',
  },
  disagreements: [],
  computed_metrics: reportDocument(1, 'x').computed_metrics,
  verdicts: [{ model_id: 'model-a', verdict: VERDICT, stage: STAGE, board_snapshot_seq: 3 }],
  participation_note: 'The agent chair did not participate.',
  absent_models: [],
  finals_used: 1,
  roster_size: 2,
  partial: true,
  submit_endpoint: 'POST /seminars/sem-1/chair-synthesis',
}

type CapturedRequest = { url: string; method: string; body: unknown }

let requests: CapturedRequest[]
let chairMode: 'model' | 'agent'
let advanceStatus = 200
let submissionStatus = 201

function installFetch() {
  requests = []
  advanceStatus = 200
  submissionStatus = 201
  vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    let body: unknown = null
    if (typeof init?.body === 'string') {
      try {
        body = JSON.parse(init.body) as unknown
      } catch {
        body = init.body
      }
    }
    requests.push({ url, method, body })
    if (url === '/api/seminars/sem-1' && method === 'GET') {
      return jsonResponse(detailFixture(chairMode))
    }
    if (url === '/api/seminars/sem-1/board') return jsonResponse(BOARD)
    if (url === '/api/seminars/sem-1/rounds') return jsonResponse(ROUNDS)
    if (url === '/api/seminars/sem-1/finals') return jsonResponse(FINALS)
    if (url.startsWith('/api/seminars/sem-1/audit')) return jsonResponse(AUDIT)
    if (url === '/api/seminars/sem-1/reports/1') {
      return jsonResponse({
        report_id: 'rep-1',
        version: 1,
        partial: false,
        chair_model_id: 'chair',
        report_hash: 'sha256:rep1',
        document: reportDocument(1, 'Recommendation v1.'),
      })
    }
    if (url === '/api/seminars/sem-1/reports/2') {
      return jsonResponse({
        report_id: 'rep-2',
        version: 2,
        partial: false,
        chair_model_id: 'chair',
        report_hash: 'sha256:rep2',
        document: reportDocument(2, 'Recommendation v2.'),
      })
    }
    if (url === '/api/seminars/sem-1/advance' && method === 'POST') {
      if (advanceStatus !== 200) {
        return jsonResponse(
          { detail: { code: 'seminar_not_collecting', message: 'seminar is not collecting' } },
          advanceStatus,
        )
      }
      return jsonResponse({
        seminar_id: 'sem-1',
        wave_no: 2,
        per_model: [{ model_id: 'model-a', round_no: 2, status: 'completed', board_snapshot_seq: 3 }],
        status: 'collecting',
      })
    }
    if (url === '/api/seminars/sem-1/finalize' && method === 'POST') {
      return jsonResponse({
        seminar_id: 'sem-1',
        finals: [{ model_id: 'model-a', status: 'final', error: null }],
        status: 'finalized',
      })
    }
    if (url === '/api/seminars/sem-1/synthesize' && method === 'POST') {
      if (chairMode === 'agent') return jsonResponse(BRIEF, 200)
      return jsonResponse(
        {
          report_id: 'rep-3',
          version: 3,
          partial: false,
          agreement_level: 'moderate',
          production_path: 'chair',
          cluster_production: 'llm',
          fallback_reason: null,
          report_hash: 'sha256:rep3',
          chair_model_id: 'chair',
          status: 'reported',
        },
        201,
      )
    }
    if (url === '/api/seminars/sem-1/chair-synthesis' && method === 'POST') {
      if (submissionStatus !== 201) {
        return jsonResponse(
          {
            detail: {
              code: 'chair_submission_coverage_failed',
              message: 'item I9 is uncovered',
            },
          },
          submissionStatus,
        )
      }
      return jsonResponse(
        {
          report_id: 'rep-4',
          version: 4,
          partial: false,
          agreement_level: 'moderate',
          production_path: 'agent_chair',
          cluster_production: 'agent_chair',
          fallback_reason: null,
          report_hash: 'sha256:rep4',
          chair_model_id: 'glint-agent',
          status: 'reported',
        },
        201,
      )
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/cockpit/seminars/sem-1']}>
      <Routes>
        <Route path="/cockpit/seminars/:id" element={<SeminarDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SeminarDetail', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows the header, roster progress, budgets, and diagnosis', async () => {
    chairMode = 'model'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    expect(screen.getByText('model-a')).toBeTruthy()
    expect(screen.getByText(/已用 50 \/ 上限 200/)).toBeTruthy()
    expect(screen.getByText(/失败 contract：1 次/)).toBeTruthy()
    await waitFor(() => expect(screen.getByText(/Launch now\./)).toBeTruthy())
    expect(screen.getByText(/建议：Phase the rollout\./)).toBeTruthy()
    expect(screen.getByText(/尝试 1 → 2/)).toBeTruthy()
  })

  it('advances a wave and shows the result inline', async () => {
    chairMode = 'model'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '推进一波' }))
    await waitFor(() => expect(screen.getByText(/第 2 波完成/)).toBeTruthy())
    expect(requests.some((req) => req.url.endsWith('/advance') && req.method === 'POST')).toBe(true)
  })

  it('finalizes and shows per-model final statuses', async () => {
    chairMode = 'model'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '定稿（终裁）' }))
    await waitFor(() => expect(screen.getByText(/定稿完成/)).toBeTruthy())
    expect(screen.getByText(/model-a final/)).toBeTruthy()
  })

  it('shows action errors inline without a phantom state', async () => {
    chairMode = 'model'
    installFetch()
    advanceStatus = 400
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '推进一波' }))
    await waitFor(() => expect(screen.getByText(/seminar_not_collecting/)).toBeTruthy())
    expect(screen.queryByText(/波完成/)).toBeNull()
  })

  it('synthesizes in model mode and sends the toggle values', async () => {
    chairMode = 'model'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.click(screen.getByLabelText(/allow_partial/))
    fireEvent.click(screen.getByRole('button', { name: '合成报告' }))
    await waitFor(() => expect(screen.getByText(/已写入报告 v3/)).toBeTruthy())
    const post = requests.find((req) => req.url.endsWith('/synthesize'))
    expect(post?.body).toEqual({ allow_partial: true, deterministic_fallback: false })
  })

  it('switches report versions in the reader', async () => {
    chairMode = 'model'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Recommendation v2.')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: /v1/ }))
    await waitFor(() => expect(screen.getByText('Recommendation v1.')).toBeTruthy())
  })

  it('applies audit filters as query parameters', async () => {
    chairMode = 'model'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText(/尝试 1 → 2/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('事件种类'), { target: { value: 'retry' } })
    fireEvent.change(screen.getByLabelText('审计筛选模型 id'), { target: { value: 'model-a' } })
    fireEvent.click(screen.getByRole('button', { name: '应用筛选' }))
    await waitFor(() =>
      expect(
        requests.some(
          (req) => req.url === '/api/seminars/sem-1/audit?kind=retry&model_id=model-a',
        ),
      ).toBe(true),
    )
  })

  it('shows the brief and submission form after an agent-mode synthesize', async () => {
    chairMode = 'agent'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    expect(screen.getByText('还没有主控简报')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '合成（产出主控简报）' }))
    await waitFor(() => expect(screen.getByText(/已产出主控简报 v1/)).toBeTruthy())
    expect(screen.getByText(/主控提交（回答简报 v1）/)).toBeTruthy()
    expect(screen.getByLabelText('聚类载荷 JSON')).toBeTruthy()
    expect(screen.getByLabelText('综合载荷 JSON')).toBeTruthy()
  })

  it('rejects malformed JSON in the submission form without calling the server', async () => {
    chairMode = 'agent'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '合成（产出主控简报）' }))
    await waitFor(() => expect(screen.getByText(/主控提交（回答简报 v1）/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('聚类载荷 JSON'), { target: { value: '{oops' } })
    fireEvent.change(screen.getByLabelText('综合载荷 JSON'), { target: { value: '{}' } })
    fireEvent.click(screen.getByRole('button', { name: '提交主控综合' }))
    await waitFor(() => expect(screen.getByText(/聚类载荷 JSON 解析失败/)).toBeTruthy())
    expect(requests.filter((req) => req.url.endsWith('/chair-synthesis'))).toHaveLength(0)
  })

  it('blocks submission while synthesis placeholders remain', async () => {
    chairMode = 'agent'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '合成（产出主控简报）' }))
    await waitFor(() => expect(screen.getByText(/主控提交（回答简报 v1）/)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '填入综合模板' }))
    expect(screen.getByText(/仍含占位符/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '提交主控综合' })).toHaveProperty('disabled', true)
  })

  it('submits valid chair payloads and shows the new report version', async () => {
    chairMode = 'agent'
    installFetch()
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '合成（产出主控简报）' }))
    await waitFor(() => expect(screen.getByText(/主控提交（回答简报 v1）/)).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '填入确定性聚类作为起点' }))
    fireEvent.change(screen.getByLabelText('综合载荷 JSON'), {
      target: {
        value: JSON.stringify({
          unified_recommendation: 'Phase it.',
          recommendation_basis: 'chair_judgment',
          agreement_level: 'moderate',
          alternatives_ranked: ['Phased'],
          aggregation_rule: 'rule',
          key_evidence: [],
          kill_criteria: [],
          minority_report: '',
          open_questions: [],
          chair_notes: '',
        }),
      },
    })
    fireEvent.click(screen.getByRole('button', { name: '提交主控综合' }))
    await waitFor(() => expect(screen.getByText(/已写入报告 v4/)).toBeTruthy())
    const post = requests.find((req) => req.url.endsWith('/chair-synthesis'))
    const body = post?.body as Record<string, unknown>
    expect(body.brief_version).toBe(1)
    const clusters = body.clusters as {
      claims: Array<{ sources: Array<{ item_id: string }> }>
    }
    expect(clusters.claims[0].sources[0].item_id).toBe('I1')
  })

  it('shows server coverage errors verbatim on a rejected submission', async () => {
    chairMode = 'agent'
    installFetch()
    submissionStatus = 400
    renderDetail()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: '合成（产出主控简报）' }))
    await waitFor(() => expect(screen.getByText(/主控提交（回答简报 v1）/)).toBeTruthy())
    fireEvent.change(screen.getByLabelText('聚类载荷 JSON'), { target: { value: '{"claims": []}' } })
    fireEvent.change(screen.getByLabelText('综合载荷 JSON'), { target: { value: '{}' } })
    fireEvent.click(screen.getByRole('button', { name: '提交主控综合' }))
    await waitFor(() => expect(screen.getByText(/chair_submission_coverage_failed/)).toBeTruthy())
    expect(screen.queryByText(/已写入报告 v4/)).toBeNull()
  })
})
