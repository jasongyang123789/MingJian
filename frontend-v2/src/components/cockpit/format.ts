// Display formatting for engine numbers. Display-only: nothing here
// feeds back into a computation, and stored values keep full precision.

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
