import type {
  DirectionMappingOrigin,
  DirectionMappingStatus,
} from '../../api/engineTypes'

/**
 * Labels for stored direction mappings. The maps are exhaustive over the
 * backend's origin/status literals: every origin the backend can serve
 * has its own label, so a proposal row is never shown as manual input
 * again. Unknown future values fall back to the raw value itself —
 * never to a wrong label — and a missing value renders as nothing.
 */
export const ORIGIN_LABELS: Record<DirectionMappingOrigin, string> = {
  derived: '推导',
  authored: '手动',
  llm_proposal: 'LLM 提案',
  override: '变量覆盖',
}

export const STATUS_LABELS: Record<DirectionMappingStatus, string> = {
  active: '可用',
  proposed: '待评审',
  rejected: '已拒绝',
}

export function originLabel(origin: string | null | undefined): string {
  if (typeof origin !== 'string' || origin.length === 0) return ''
  return ORIGIN_LABELS[origin as DirectionMappingOrigin] ?? origin
}

export function statusLabel(status: string | null | undefined): string {
  if (typeof status !== 'string' || status.length === 0) return ''
  return STATUS_LABELS[status as DirectionMappingStatus] ?? status
}

export interface ProposalRecordSummary {
  rationale: string | null
  keyVariables: string[]
  model: string | null
  templateId: string | null
  templateVersion: string | null
  proposalHash: string | null
}

function asNonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string')
}

/**
 * Read the proposal record the backend pins on an `llm_proposal` row.
 * The record is an untyped JSON object; only well-shaped fields are
 * surfaced, anything else is dropped rather than rendered raw.
 * Returns null when the row carries no proposal record.
 */
export function parseProposalRecord(
  record: Record<string, unknown> | null | undefined,
): ProposalRecordSummary | null {
  if (!record || typeof record !== 'object') return null
  return {
    rationale: asNonEmptyString(record.rationale),
    keyVariables: asStringList(record.key_variables),
    model: asNonEmptyString(record.model),
    templateId: asNonEmptyString(record.template_id),
    templateVersion: asNonEmptyString(record.template_version),
    proposalHash: asNonEmptyString(record.proposal_hash),
  }
}

export interface OverrideRecordSummary {
  overrides: Array<{ variableId: string; value: number }>
  branchId: string | null
  forkStep: number | null
  overrideHash: string | null
}

/**
 * Read the override record the backend pins on an `override` row:
 * the fixed-value overrides, the scenario branch they created, and
 * the fork step. Only finite numeric override values are surfaced,
 * in variable-id order so the same spec always renders the same.
 */
export function parseOverrideRecord(
  record: Record<string, unknown> | null | undefined,
): OverrideRecordSummary | null {
  if (!record || typeof record !== 'object') return null
  const raw = record.overrides
  const overrides: Array<{ variableId: string; value: number }> = []
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    for (const variableId of Object.keys(raw).sort()) {
      const value = (raw as Record<string, unknown>)[variableId]
      if (typeof value === 'number' && Number.isFinite(value)) {
        overrides.push({ variableId, value })
      }
    }
  }
  const forkStep = record.fork_step
  return {
    overrides,
    branchId: asNonEmptyString(record.branch_id),
    forkStep: typeof forkStep === 'number' && Number.isFinite(forkStep) ? forkStep : null,
    overrideHash: asNonEmptyString(record.override_hash),
  }
}

/** Shorten a `sha256:…` hash for display; short values pass through. */
export function shortHash(hash: string, keep = 20): string {
  return hash.length > keep ? `${hash.slice(0, keep)}…` : hash
}

/**
 * One-line summary of an override record for the stored list, e.g.
 * `cash=80 · 分叉步 2`. Returns null when the record carries nothing
 * renderable, so the row shows no summary line at all.
 */
export function overrideSummaryText(summary: OverrideRecordSummary | null): string | null {
  if (!summary) return null
  const parts = summary.overrides.map(({ variableId, value }) => `${variableId}=${value}`)
  if (summary.forkStep !== null) parts.push(`分叉步 ${summary.forkStep}`)
  return parts.length > 0 ? parts.join(' · ') : null
}
