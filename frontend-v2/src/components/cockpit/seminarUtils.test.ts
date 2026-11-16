import { describe, expect, it } from 'vitest'

import type { ChairBriefRead, SynthesizeRead } from '../../api/engineTypes'
import {
  auditDetailLines,
  clustersPrefillFromBrief,
  endpointSummary,
  formatDurationMs,
  isChairBrief,
  parseJsonTextarea,
  stageRecordSummary,
  synthesisTemplate,
} from './seminarUtils'

const BRIEF = {
  deterministic_clusters: {
    claims: [
      {
        claim: 'Demand grows.',
        sources: [
          { item_id: 'I1', stance: 'support' },
          { item_id: 'I2', stance: 'support' },
        ],
      },
      { claim: 'Costs rise.', sources: [{ item_id: 'I3', stance: 'support' }] },
    ],
  },
} as unknown as ChairBriefRead

describe('isChairBrief', () => {
  it('tells a stored brief apart from a report summary', () => {
    const brief = { brief_version: 1 } as unknown as ChairBriefRead
    const report = { version: 1 } as unknown as SynthesizeRead
    expect(isChairBrief(brief)).toBe(true)
    expect(isChairBrief(report)).toBe(false)
  })
})

describe('formatDurationMs', () => {
  it('formats milliseconds, seconds, and missing values', () => {
    expect(formatDurationMs(null)).toBe('—')
    expect(formatDurationMs(250)).toBe('250 ms')
    expect(formatDurationMs(2500)).toBe('2.5 s')
  })
})

describe('endpointSummary', () => {
  it('summarizes target and inline endpoints by name only', () => {
    expect(endpointSummary({ target: 'primary' })).toBe('target: primary')
    expect(
      endpointSummary({ base_url_env: 'MY_URL', api_key_env: 'MY_KEY', model: 'm1' }),
    ).toBe('inline (base_url_env: MY_URL, api_key_env: MY_KEY, model: m1)')
    expect(endpointSummary(null)).toBe('—')
  })
})

describe('stageRecordSummary', () => {
  it('includes pinned versions and reported accounting only', () => {
    expect(
      stageRecordSummary({
        stage: 'intake',
        template_id: 'mckinsey.intake_classify',
        template_version: '2',
        contract_version: '2',
        output: {},
        model: 'gpt-6.1-sol',
        usage: { total_tokens: 120 },
        duration_ms: 1500,
        attempts: 2,
      }),
    ).toBe(
      '模板 mckinsey.intake_classify v2 · 契约 v2 · 模型 gpt-6.1-sol · 尝试 2 次 · 耗时 1.5 s · Token 120',
    )
    expect(
      stageRecordSummary({
        stage: 'intake',
        template_id: 't',
        template_version: '1',
        contract_version: '1',
        output: {},
        model: null,
        usage: null,
        duration_ms: null,
        attempts: null,
      }),
    ).toBe('模板 t v1 · 契约 v1')
  })
})

describe('auditDetailLines', () => {
  it('summarizes a finished stage call with usage', () => {
    const lines = auditDetailLines('stage_call_finished', {
      attempt: 1,
      duration_ms: 1200,
      outcome: 'ok',
      usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
    })
    expect(lines[0]).toContain('尝试 1')
    expect(lines[0]).toContain('1.2 s')
    expect(lines[0]).toContain('ok')
    expect(lines[1]).toContain('Token 15')
    expect(lines[1]).toContain('提示 10 + 完成 5')
  })

  it('summarizes retries, budget exhaustion, and queue waits', () => {
    expect(
      auditDetailLines('retry', {
        attempt: 1,
        next_attempt: 2,
        backoff_seconds: 1,
        error_kind: 'timeout',
      })[0],
    ).toContain('尝试 1 → 2')
    expect(
      auditDetailLines('budget_exhausted', { budget: 'stage_calls', used: 200, limit: 200 })[0],
    ).toContain('已用 200 / 上限 200')
    expect(auditDetailLines('queue_wait', { wait_ms: 250, trigger: 'synthesize' })[0]).toContain(
      '排队等待 250 ms',
    )
  })

  it('summarizes transitions, reports, refusals, and failures', () => {
    expect(
      auditDetailLines('status_transition', { from: 'open', to: 'running', trigger: 'advance' })[0],
    ).toBe('open → running（advance）')
    expect(
      auditDetailLines('report_written', {
        version: 2,
        production_path: 'chair',
        cluster_production: 'llm',
        partial: false,
      })[0],
    ).toContain('报告 v2')
    expect(
      auditDetailLines('refusal', { code: 'seminar_no_finals', message: 'no finals' })[0],
    ).toContain('seminar_no_finals')
    expect(
      auditDetailLines('stage_failure', {
        error_kind: 'contract',
        stage: 'seminar.cluster',
        message: 'bad shape',
      })[0],
    ).toContain('contract @ seminar.cluster')
  })

  it('falls back to raw JSON for unknown shapes', () => {
    expect(auditDetailLines('mystery_kind', { a: 1 })[0]).toBe('{"a":1}')
  })
})

describe('clustersPrefillFromBrief', () => {
  it('covers every pre-pass item exactly once', () => {
    const prefill = clustersPrefillFromBrief(BRIEF) as {
      claims: Array<{ claim: string; sources: Array<{ item_id: string; stance: string }> }>
    }
    expect(prefill.claims).toHaveLength(2)
    const ids = prefill.claims.flatMap((claim) => claim.sources.map((source) => source.item_id))
    expect(ids.sort()).toEqual(['I1', 'I2', 'I3'])
    expect(prefill.claims[0].sources[0].stance).toBe('support')
  })
})

describe('synthesisTemplate', () => {
  it('carries every SeminarSynthesis field with placeholders', () => {
    const template = synthesisTemplate() as Record<string, unknown>
    for (const key of [
      'unified_recommendation',
      'recommendation_basis',
      'agreement_level',
      'alternatives_ranked',
      'aggregation_rule',
      'key_evidence',
      'kill_criteria',
      'minority_report',
      'open_questions',
      'chair_notes',
    ]) {
      expect(template[key]).toBeDefined()
    }
    expect(String(template.unified_recommendation)).toContain('【')
  })
})

describe('parseJsonTextarea', () => {
  it('rejects empty and malformed input, accepts valid JSON', () => {
    expect(parseJsonTextarea('', '聚类载荷').ok).toBe(false)
    expect(parseJsonTextarea('  ', '聚类载荷').ok).toBe(false)
    const bad = parseJsonTextarea('{oops', '聚类载荷')
    expect(bad.ok).toBe(false)
    if (!bad.ok) expect(bad.error).toContain('聚类载荷')
    const good = parseJsonTextarea('{"claims": []}', '聚类载荷')
    expect(good).toEqual({ ok: true, value: { claims: [] } })
  })
})
