import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type {
  AuditEventRead,
  BoardRowRead,
  ChairBriefRead,
  FinalRowRead,
  RoundRowRead,
  SeminarDetailRead,
  SeminarReportDocument,
} from '../../api/engineTypes'
import {
  AuditLogView,
  BoardTimeline,
  BudgetsPanel,
  ChairBriefView,
  DiagnosisPanel,
  FinalsList,
  ReportDocumentView,
  RoundsComparison,
  RosterProgressTable,
} from './SeminarViews'

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
} as const

const DETAIL = {
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
  config: CONFIG,
  chair_model: {
    model_id: 'chair',
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
  reports: [],
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
} as unknown as SeminarDetailRead

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

describe('BudgetsPanel + DiagnosisPanel', () => {
  it('shows used/limits/remaining from the audit ledger', () => {
    render(<BudgetsPanel budgets={DETAIL.budgets} />)
    expect(screen.getByText(/已用 50 \/ 上限 200/)).toBeTruthy()
    expect(screen.getByText(/已用 360 \/ 上限 1000000/)).toBeTruthy()
  })

  it('shows error counts, tokens, and duration', () => {
    render(<DiagnosisPanel diagnosis={DETAIL.diagnosis} />)
    expect(screen.getByText(/失败 contract：1 次/)).toBeTruthy()
    expect(screen.getByText(/Token 合计 360/)).toBeTruthy()
    expect(screen.getByText(/总耗时 12.5 s/)).toBeTruthy()
  })
})

describe('RosterProgressTable', () => {
  it('shows per-model progress and endpoint summaries', () => {
    render(<RosterProgressTable detail={DETAIL} />)
    expect(screen.getByText('model-a')).toBeTruthy()
    expect(screen.getByText('model-b')).toBeTruthy()
    expect(screen.getAllByText(/target: primary/).length).toBe(2)
    expect(screen.getByText(/终裁 2 \/ 2/)).toBeTruthy()
    expect(screen.getByText(/board 发布 4 条/)).toBeTruthy()
  })
})

describe('BoardTimeline', () => {
  const rows = [
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
        kill_criteria: ['Churn exceeds 8%.'],
        changes: [],
        reflection_missing: false,
        board_snapshot_seq: 0,
      },
    },
    {
      id: 'b2',
      seminar_id: 'sem-1',
      seq: 2,
      model_id: 'model-b',
      round_no: 1,
      digest: {
        model_id: 'model-b',
        round_no: 1,
        recommendation: 'Wait a quarter.',
        confidence: 'low',
        key_arguments: [],
        kill_criteria: [],
        changes: [],
        reflection_missing: true,
        board_snapshot_seq: 1,
      },
    },
  ] as unknown as BoardRowRead[]

  it('renders digests as seq-ordered quotations with model + round labels', () => {
    render(<BoardTimeline rows={rows} />)
    expect(screen.getByText('Launch now.')).toBeTruthy()
    expect(screen.getByText('Wait a quarter.')).toBeTruthy()
    expect(screen.getByText('seq 1')).toBeTruthy()
    expect(screen.getByText('seq 2')).toBeTruthy()
    expect(screen.getByText(/反思缺失/)).toBeTruthy()
    expect(screen.getByText('Demand is proven.')).toBeTruthy()
  })

  it('shows an honest empty state', () => {
    render(<BoardTimeline rows={[]} />)
    expect(screen.getByText(/board 上还没有发布/)).toBeTruthy()
  })
})

describe('RoundsComparison', () => {
  const rows = [
    {
      id: 'r1',
      seminar_id: 'sem-1',
      model_id: 'model-a',
      round_no: 1,
      board_snapshot_seq: 0,
      stages: [
        { ...STAGE, stage: 'intake', template_id: 'mckinsey.intake_classify' },
        { ...STAGE, stage: 'diagnose', template_id: 'mckinsey.diagnose' },
      ],
      reflection: {
        critique: [{ weak_point: 'Thin evidence', reason: 'Only one source.' }],
        responses: [{ model_id: 'model-b', stance: 'oppose', reason: 'Timing risk.' }],
        changes: [],
        confidence: 'medium',
        confidence_basis: 'Two signals agree.',
        open_questions: ['What if churn spikes?'],
      },
      reflection_stage: STAGE,
      status: 'completed',
      error: null,
    },
    {
      id: 'r2',
      seminar_id: 'sem-1',
      model_id: 'model-b',
      round_no: 1,
      board_snapshot_seq: 0,
      stages: [],
      reflection: null,
      reflection_stage: null,
      status: 'failed',
      error: { kind: 'timeout', stage: 'mckinsey.diagnose', message: 'upstream timeout' },
    },
  ] as unknown as RoundRowRead[]

  it('groups rounds per model with reflection and failure detail', () => {
    render(<RoundsComparison rows={rows} />)
    expect(screen.getByText('model-a')).toBeTruthy()
    expect(screen.getByText(/2 个分析阶段/)).toBeTruthy()
    expect(screen.getByText(/弱点：Thin evidence/)).toBeTruthy()
    expect(screen.getByText(/回应 model-b（oppose）/)).toBeTruthy()
    expect(screen.getByText(/失败（timeout @ mckinsey.diagnose）：upstream timeout/)).toBeTruthy()
  })
})

describe('FinalsList', () => {
  it('renders verdicts verbatim', () => {
    const rows = [
      {
        id: 'f1',
        seminar_id: 'sem-1',
        model_id: 'model-a',
        verdict: VERDICT,
        stage: STAGE,
        board_snapshot_seq: 3,
        status: 'final',
      },
    ] as unknown as FinalRowRead[]
    render(<FinalsList rows={rows} />)
    expect(screen.getByText(/建议：Phase the rollout\./)).toBeTruthy()
    expect(screen.getByText('Runway covers 14 months.')).toBeTruthy()
    expect(screen.getByText('The bull case ignores pricing pressure.')).toBeTruthy()
  })
})

const DOCUMENT = {
  header: {
    seminar_id: 'sem-1',
    run_id: 'run-1',
    topic: 'Should we launch in Q3?',
    version: 1,
    partial: false,
    chair_model_id: 'chair',
    chair_mode: 'model',
    chair_participates: false,
    production_path: 'chair',
    cluster_production: 'llm',
    report_hash: 'sha256:reporthash',
    finals_used: 2,
    roster_size: 2,
    absent_models: [],
  },
  unified_recommendation: {
    text: 'Phase the rollout.',
    basis: 'chair_judgment',
    provenance: 'deliberated',
  },
  agreement: {
    chair_level: 'low',
    chair_provenance: 'deliberated',
    computed: { n_models: 2, pairs_total: 1, pairs_agreeing: 0, rate: 0 },
    computed_provenance: 'computed',
    note: 'Side by side.',
  },
  canonical_claims: {
    claims: [
      {
        claim: 'Demand grows steadily.',
        sources: [
          {
            item_id: 'I1',
            model_id: 'model-a',
            round_no: 2,
            field: 'key_evidence',
            stance: 'support',
            original_text: 'Demand grows.',
          },
          {
            item_id: 'I2',
            model_id: 'model-b',
            round_no: 2,
            field: 'key_evidence',
            stance: 'oppose',
            original_text: 'Demand is flat.',
          },
        ],
        merge_map: ['I1', 'I2'],
      },
    ],
    merge_map: { I1: 0, I2: 0 },
    provenance: 'deliberated',
    production: 'llm',
  },
  disagreements: {
    items: [
      {
        claim_index: 0,
        claim: 'Demand grows steadily.',
        stances: ['oppose', 'support'],
        positions: [
          {
            stance: 'oppose',
            sources: [
              { model_id: 'model-b', round_no: 2, field: 'key_evidence', original_text: 'Demand is flat.' },
            ],
          },
          {
            stance: 'support',
            sources: [
              { model_id: 'model-a', round_no: 2, field: 'key_evidence', original_text: 'Demand grows.' },
            ],
          },
        ],
      },
    ],
    count: 1,
    provenance: 'computed',
    note: 'Derived in code.',
  },
  alternatives: {
    borda: {
      method: 'borda',
      n_models: 2,
      totals: { 'Full launch': 3, 'Phased rollout': 3 },
      ranked: ['Full launch', 'Phased rollout'],
    },
    borda_provenance: 'computed',
    chair_ranked: ['Phased rollout', 'Full launch'],
    aggregation_rule: 'Chair judgment over the tie.',
    chair_provenance: 'deliberated',
  },
  key_evidence: {
    items: [{ text: 'Runway covers 14 months.', source_models: ['model-a'] }],
    provenance: 'deliberated',
  },
  kill_criteria: {
    items: [{ text: 'Churn exceeds 8%.', source_models: ['model-a', 'model-b'] }],
    provenance: 'deliberated',
  },
  minority_report: { text: 'The bull case was dropped.', provenance: 'deliberated', verbatim: true },
  rounds_evolution: [
    { model_id: 'model-a', rounds_summary: 'Moved to phased.', board_snapshot_seq: 3, verbatim: true },
  ],
  open_questions: { items: ['What if churn spikes?'], provenance: 'deliberated' },
  chair_notes: { text: 'Watch churn.', provenance: 'deliberated' },
  chair_synthesis: null,
  computed_metrics: {
    recommendation_agreement: { n_models: 2, pairs_total: 1, pairs_agreeing: 0, rate: 0 },
    confidence_distribution: { low: 0, medium: 1, high: 1 },
    borda: {
      method: 'borda',
      n_models: 2,
      totals: { 'Full launch': 3, 'Phased rollout': 3 },
      ranked: ['Full launch', 'Phased rollout'],
    },
    dedup: {
      original_items: 2,
      canonical_claims: 1,
      exact_duplicate_groups: 0,
      semantic_merge_groups: 1,
      cluster_production: 'llm',
    },
    disagreement_count: 1,
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
    round_stage_counts: { 'model-a': 22 },
    board_seq_range: [1, 4],
    board_publications: 4,
    model_configs: [],
    chair_config: {},
    token_usage: 'Not recorded.',
  },
} as unknown as SeminarReportDocument

describe('ReportDocumentView', () => {
  it('shows the recommendation, Borda totals, and provenance badges', () => {
    render(<ReportDocumentView document={DOCUMENT} />)
    expect(screen.getByText('Phase the rollout.')).toBeTruthy()
    expect(screen.getByText(/Full launch：Borda 3 分/)).toBeTruthy()
    expect(screen.getAllByText('商议引用').length).toBeGreaterThan(0)
    expect(screen.getAllByText('计算').length).toBeGreaterThan(0)
    expect(screen.getByText(/merge_map/)).toBeTruthy()
    expect(screen.getByText(/I1→0/)).toBeTruthy()
  })

  it('shows disagreements prominently with both sides quoted', () => {
    render(<ReportDocumentView document={DOCUMENT} />)
    expect(screen.getByText(/从不被平均掉/)).toBeTruthy()
    expect(screen.getByText(/立场：oppose \/ support/)).toBeTruthy()
    expect(screen.getAllByText(/Demand is flat\./)).toHaveLength(2)
    expect(screen.getAllByText(/Demand grows\./)).toHaveLength(2)
  })

  it('shows the minority report verbatim and the fallback reason when present', () => {
    const withFallback = {
      ...DOCUMENT,
      header: { ...DOCUMENT.header, fallback_reason: 'chair stage failed (timeout)' },
    }
    render(<ReportDocumentView document={withFallback} />)
    expect(screen.getByText('The bull case was dropped.')).toBeTruthy()
    expect(screen.getByText(/兜底原因：chair stage failed/)).toBeTruthy()
  })
})

describe('AuditLogView', () => {
  const events = [
    {
      id: 'e1',
      seminar_id: 'sem-1',
      seq: 1,
      model_id: 'model-a',
      stage: 'mckinsey.intake_classify',
      kind: 'stage_call_finished',
      detail: { attempt: 1, duration_ms: 1200, outcome: 'ok', usage: { total_tokens: 15 } },
      round_no: 1,
      stage_call_id: 'call-1',
      created_at: '2026-11-16T07:00:00Z',
    },
    {
      id: 'e2',
      seminar_id: 'sem-1',
      seq: 2,
      model_id: null,
      stage: null,
      kind: 'queue_wait',
      detail: { wait_ms: 250, trigger: 'synthesize' },
      round_no: null,
      stage_call_id: null,
      created_at: '2026-11-16T07:00:01Z',
    },
  ] as unknown as AuditEventRead[]

  it('renders events in seq order with detail summaries', () => {
    render(<AuditLogView events={events} />)
    expect(screen.getByText('stage_call_finished')).toBeTruthy()
    expect(screen.getByText('queue_wait')).toBeTruthy()
    expect(screen.getByText(/Token 15/)).toBeTruthy()
    expect(screen.getByText(/排队等待 250 ms/)).toBeTruthy()
  })
})

describe('ChairBriefView', () => {
  const brief = {
    seminar_id: 'sem-1',
    brief_version: 1,
    brief_hash: 'sha256:briefhash',
    topic: 'Should we launch in Q3?',
    status: 'collecting',
    chair_mode: 'agent',
    chair_model_id: 'glint-agent',
    prepass: {
      items: [
        { item_id: 'I1', model_id: 'model-a', round_no: 2, field: 'key_evidence', text: 'Demand grows.', normalized_text: 'demand grows' },
        { item_id: 'I2', model_id: 'model-b', round_no: 2, field: 'key_evidence', text: 'Demand grows steadily.', normalized_text: 'demand grows steadily' },
      ],
      exact_groups: [['I1'], ['I2']],
      exact_duplicate_groups: 0,
      near_duplicate_groups: [['I1', 'I2']],
      near_duplicate_group_count: 1,
      near_duplicate_threshold: 0.8,
      item_count: 2,
      excluded_dissent_placeholders: 1,
    },
    deterministic_clusters: {
      claims: [
        {
          claim: 'Demand grows.',
          sources: [
            { item_id: 'I1', model_id: 'model-a', round_no: 2, field: 'key_evidence', stance: 'support', original_text: 'Demand grows.' },
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
    computed_metrics: DOCUMENT.computed_metrics,
    verdicts: [{ model_id: 'model-a', verdict: VERDICT, stage: STAGE, board_snapshot_seq: 3 }],
    participation_note: 'The agent chair did not participate.',
    absent_models: [{ model_id: 'model-b', status: 'failed', reason: 'failed at stage X (timeout)' }],
    finals_used: 1,
    roster_size: 2,
    partial: true,
    submit_endpoint: 'POST /seminars/sem-1/chair-synthesis',
  } as unknown as ChairBriefRead

  it('shows pre-pass items, near-duplicate candidates, clusters, and verdicts', () => {
    render(<ChairBriefView brief={brief} />)
    expect(screen.getByText(/简报 v1/)).toBeTruthy()
    expect(screen.getByText(/2 个主张项/)).toBeTruthy()
    expect(screen.getByText(/排除 1 个异议占位符/)).toBeTruthy()
    expect(screen.getAllByText(/Demand grows steadily\./)).toHaveLength(2)
    expect(screen.getByText(/POST \/seminars\/sem-1\/chair-synthesis/)).toBeTruthy()
    expect(screen.getByText(/缺席 model-b/)).toBeTruthy()
    expect(screen.getByText(/建议：Phase the rollout\./)).toBeTruthy()
  })
})
