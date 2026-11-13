// Display formatting for engine numbers. Display-only: nothing here
// feeds back into a computation, and stored values keep full precision.

import type { VariableDefinition } from '../../api/engineTypes'

/** One-line summary of a variable's distribution from its own parameters. */
export function distributionSummary(variable: VariableDefinition): string {
  const d = variable.distribution
  switch (d.type) {
    case 'fixed':
      return `fixed = ${formatNumber(d.value ?? 0)}`
    case 'normal':
      return `normal(μ=${formatNumber(d.mean ?? 0)}, σ=${formatNumber(d.std ?? 0)})`
    case 'triangular':
      return `triangular(${formatNumber(d.min ?? 0)}, ${formatNumber(d.mode ?? 0)}, ${formatNumber(d.max ?? 0)})`
    case 'beta_pert':
      return `beta_pert(${formatNumber(d.min ?? 0)}, ${formatNumber(d.mode ?? 0)}, ${formatNumber(d.max ?? 0)})`
    case 'bernoulli':
      return `bernoulli(p=${formatNumber(d.p ?? 0)})`
  }
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value)
  if (Number.isInteger(value)) return String(value)
  return value
    .toFixed(4)
    .replace(/0+$/, '')
    .replace(/\.$/, '')
}

/** A 0–1 share (e.g. p_loss) as a percentage with one decimal. */
export function formatShare(value: number): string {
  if (!Number.isFinite(value)) return String(value)
  return `${(value * 100).toFixed(1)}%`
}

/** Shorten a sha256: hash for display, keeping the prefix recognizable. */
export function formatHash(hash: string | null | undefined): string {
  if (!hash) return '—'
  if (hash.length <= 20) return hash
  return `${hash.slice(0, 12)}…${hash.slice(-6)}`
}
