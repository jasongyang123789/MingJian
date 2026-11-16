// Pure helpers for the seminar cockpit views (Sprint 20). Display-only:
// nothing here feeds back into a computation, and every value shown
// comes from a stored backend row. Kept in a separate module because
// the react-refresh rule forbids non-component exports from component
// files (the Phase 2 automotiveUtils precedent).

import type {
  ChairBriefRead,
  SeminarEndpointConfig,
  StageRecordRead,
  SynthesizeRead,
} from '../../api/engineTypes'
import { formatNumber } from './format'

// Configured-target names (planagent/config/openai.py TARGET_NAMES).
export const SEMINAR_TARGET_NAMES = [
  'primary',
  'extraction',
  'x_search',
  'report',
  'debate_advocate',
  'debate_challenger',
  'debate_arbitrator',
] as const

// The 13 stored audit event kinds (AuditEventKind in audit.py).
export const SEMINAR_AUDIT_EVENT_KINDS = [
  'stage_call_started',
  'stage_call_finished',
  'retry',
  'stage_failure',
  'budget_exhausted',
  'fallback',
  'queue_wait',
  'status_transition',
  'chair_brief_produced',
  'synthesis_submitted',
  'report_written',
  'synthesis_failed',
  'refusal',
] as const

/** Synthesize answers a report summary (model chair) or a chair brief
 * (agent chair); the brief carries `brief_version`, the report does not. */
export function isChairBrief(
  value: SynthesizeRead | ChairBriefRead,
): value is ChairBriefRead {
  return 'brief_version' in value
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—'
  if (ms < 1000) return `${formatNumber(ms)} ms`
  return `${formatNumber(ms / 1000)} s`
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

/** One-line endpoint summary. Env-var NAMES only — keys never appear. */
export function endpointSummary(endpoint: SeminarEndpointConfig | null | undefined): string {
  if (!endpoint) return '—'
  if (endpoint.target) return `target: ${endpoint.target}`
  const parts = [
    endpoint.base_url_env ? `base_url_env: ${endpoint.base_url_env}` : null,
    endpoint.api_key_env ? `api_key_env: ${endpoint.api_key_env}` : null,
    endpoint.model ? `model: ${endpoint.model}` : null,
  ].filter((part): part is string => part !== null)
  return parts.length > 0 ? `inline (${parts.join(', ')})` : '—'
}

/** Provenance line for one stored stage record (template/contract
 * versions pinned at execution time, plus S18 accounting when the
 * port reported it — never fabricated). */
export function stageRecordSummary(stage: StageRecordRead): string {
  const parts = [
    `模板 ${stage.template_id} v${stage.template_version}`,
    `契约 v${stage.contract_version}`,
  ]
  if (stage.model) parts.push(`模型 ${stage.model}`)
  if (stage.attempts !== null && stage.attempts !== undefined) {
    parts.push(`尝试 ${stage.attempts} 次`)
  }
  if (stage.duration_ms !== null && stage.duration_ms !== undefined) {
    parts.push(`耗时 ${formatDurationMs(stage.duration_ms)}`)
  }
  const usage = stage.usage
  if (usage) {
    const total = asNumber(usage.total_tokens)
    if (total !== null) parts.push(`Token ${formatNumber(total)}`)
  }
  return parts.join(' · ')
}

/** Human-readable summary lines for one audit event's detail dict.
 * Shapes come from the recorder call sites (instrumentation.py +
 * service.py); unknown shapes fall back to raw JSON, never silence. */
export function auditDetailLines(kind: string, detail: Record<string, unknown>): string[] {
  const attempt = asNumber(detail.attempt)
  switch (kind) {
    case 'stage_call_started':
      return [attempt !== null ? `尝试 ${attempt}` : '调用开始']
    case 'stage_call_finished': {
      const lines: string[] = []
      const outcome = asString(detail.outcome)
      const duration = asNumber(detail.duration_ms)
      lines.push(
        [
          attempt !== null ? `尝试 ${attempt}` : null,
          duration !== null ? `耗时 ${formatDurationMs(duration)}` : null,
          outcome ? `结果 ${outcome}` : null,
        ]
          .filter((part): part is string => part !== null)
          .join(' · ') || '调用完成',
      )
      const usage = asRecord(detail.usage)
      if (usage) {
        const total = asNumber(usage.total_tokens)
        const prompt = asNumber(usage.prompt_tokens)
        const completion = asNumber(usage.completion_tokens)
        lines.push(
          `Token ${total !== null ? formatNumber(total) : '—'}` +
            (prompt !== null || completion !== null
              ? `（提示 ${prompt !== null ? formatNumber(prompt) : '—'} + 完成 ${completion !== null ? formatNumber(completion) : '—'}）`
              : ''),
        )
      }
      const message = asString(detail.error_message)
      if (message) lines.push(`错误：${message}`)
      return lines
    }
    case 'retry': {
      const next = asNumber(detail.next_attempt)
      const backoff = asNumber(detail.backoff_seconds)
      const errorKind = asString(detail.error_kind)
      const message = asString(detail.error_message)
      return [
        [
          attempt !== null && next !== null ? `尝试 ${attempt} → ${next}` : '重试',
          backoff !== null ? `退避 ${formatNumber(backoff)}s` : null,
          errorKind ? `错误种类 ${errorKind}` : null,
        ]
          .filter((part): part is string => part !== null)
          .join(' · '),
        ...(message ? [`错误：${message}`] : []),
      ]
    }
    case 'budget_exhausted': {
      const budget = asString(detail.budget)
      const used = asNumber(detail.used)
      const limit = asNumber(detail.limit)
      return [
        `${budget ?? '预算'}已耗尽：已用 ${used !== null ? formatNumber(used) : '—'} / 上限 ${limit !== null ? formatNumber(limit) : '—'}`,
      ]
    }
    case 'stage_failure': {
      const errorKind = asString(detail.error_kind)
      const stage = asString(detail.stage)
      const message = asString(detail.message)
      return [`${errorKind ?? '失败'}${stage ? ` @ ${stage}` : ''}${message ? `：${message}` : ''}`]
    }
    case 'fallback': {
      const errorKind = asString(detail.error_kind)
      const reason = asString(detail.reason)
      return [`兜底：${errorKind ?? '未知原因'}${reason ? `：${reason}` : ''}`]
    }
    case 'queue_wait': {
      const waitMs = asNumber(detail.wait_ms)
      const trigger = asString(detail.trigger)
      return [
        `排队等待 ${waitMs !== null ? formatDurationMs(waitMs) : '—'}${trigger ? `（${trigger}）` : ''}`,
      ]
    }
    case 'status_transition': {
      const from = asString(detail.from)
      const to = asString(detail.to)
      const trigger = asString(detail.trigger)
      return [`${from ?? '?'} → ${to ?? '?'}${trigger ? `（${trigger}）` : ''}`]
    }
    case 'chair_brief_produced': {
      const version = asNumber(detail.brief_version)
      const hash = asString(detail.brief_hash)
      return [`简报 v${version ?? '—'}${hash ? ` · ${hash}` : ''}`]
    }
    case 'synthesis_submitted': {
      const version = asNumber(detail.brief_version)
      const path = asString(detail.production_path)
      return [`回答简报 v${version ?? '—'}${path ? ` · ${path}` : ''}`]
    }
    case 'report_written': {
      const version = asNumber(detail.version)
      const path = asString(detail.production_path)
      const cluster = asString(detail.cluster_production)
      const partial = detail.partial
      return [
        `报告 v${version ?? '—'} · ${path ?? '—'} / ${cluster ?? '—'} · 部分报告：${partial === true ? '是' : '否'}`,
      ]
    }
    case 'synthesis_failed': {
      const errorKind = asString(detail.error_kind)
      const message = asString(detail.message)
      return [`${errorKind ?? '失败'}${message ? `：${message}` : ''}`]
    }
    case 'refusal': {
      const code = asString(detail.code)
      const message = asString(detail.message)
      return [`${code ?? '拒绝'}${message ? `：${message}` : ''}`]
    }
    default:
      return [JSON.stringify(detail)]
  }
}

/** Build a coverage-valid ClaimClusters payload from the brief's own
 * deterministic clusters: one claim per exact group, every pre-pass
 * item covered exactly once, stance `support` throughout (the same
 * shape `deterministic_clusters` produces). The chair edits from
 * here; the server re-validates coverage on submit. */
export function clustersPrefillFromBrief(brief: ChairBriefRead): unknown {
  return {
    claims: brief.deterministic_clusters.claims.map((claim) => ({
      claim: claim.claim,
      sources: claim.sources.map((source) => ({
        item_id: source.item_id,
        stance: source.stance,
      })),
    })),
  }
}

/** A SeminarSynthesis-shaped starting template. Every field carries
 * an explicit placeholder the chair must replace with real judgment —
 * submitting it unchanged would write placeholder prose into a
 * versioned report, so the form warns before submit. */
export function synthesisTemplate(): unknown {
  return {
    unified_recommendation: '【主控判断：写统一建议】',
    recommendation_basis: 'chair_judgment',
    agreement_level: 'moderate',
    alternatives_ranked: ['【方案一】', '【方案二】'],
    aggregation_rule: '【写聚合规则：主控如何综合各模型排序】',
    key_evidence: [{ text: '【关键证据】', source_models: ['【模型 id】'] }],
    kill_criteria: [{ text: '【叫停标准】', source_models: ['【模型 id】'] }],
    minority_report: '【少数派观点：逐字保留，不可概括】',
    open_questions: ['【开放问题】'],
    chair_notes: '【主控备注】',
  }
}

export type JsonParseResult =
  | { ok: true; value: unknown }
  | { ok: false; error: string }

/** Client-side JSON validation for the chair-submission textareas:
 * empty input and malformed JSON are inline errors, never a POST. */
export function parseJsonTextarea(text: string, label: string): JsonParseResult {
  if (text.trim() === '') return { ok: false, error: `${label}为空：请粘贴合法的 JSON 对象。` }
  try {
    return { ok: true, value: JSON.parse(text) as unknown }
  } catch (e: unknown) {
    return {
      ok: false,
      error: `${label} JSON 解析失败：${e instanceof Error ? e.message : String(e)}`,
    }
  }
}
