import type { SalesLayerRowRead } from '../../api/engineTypes'

export interface OemSummary {
  oem_id: string
  customer_status: string
  nameplate_count: number
}

/** Read OEM ids, customer statuses, and nameplate counts from a stored
 * split structure. Tolerant of malformed shapes: returns [] instead of
 * throwing, so the page degrades to an empty list. */
export function oemSummaries(structure: Record<string, unknown>): OemSummary[] {
  const oems = structure.oems
  if (!Array.isArray(oems)) return []
  const summaries: OemSummary[] = []
  for (const oem of oems) {
    if (typeof oem !== 'object' || oem === null) continue
    const record = oem as Record<string, unknown>
    if (typeof record.oem_id !== 'string') continue
    summaries.push({
      oem_id: record.oem_id,
      customer_status: typeof record.customer_status === 'string' ? record.customer_status : '—',
      nameplate_count: Array.isArray(record.nameplates) ? record.nameplates.length : 0,
    })
  }
  return summaries
}

/** One segment of the S-layer detail chart: a single OEM × product cell.
 * The segment key is the legend label; the segment value at a tick is the
 * SUM of the detail rows sharing that tick, OEM, and product (a tick can
 * carry several rows for one OEM × product when two generations of one
 * nameplate both fit the same product). */
export function detailSegmentKey(row: SalesLayerRowRead): string {
  return `${row.oem_id} · ${row.product_id}`
}

/** Distinct detail segments in first-appearance order (stable legend
 * order). Tolerant of malformed rows: skips rows without string ids. */
export function detailSegments(rows: SalesLayerRowRead[]): string[] {
  const seen = new Set<string>()
  const segments: string[] = []
  for (const row of rows) {
    if (typeof row.oem_id !== 'string' || typeof row.product_id !== 'string') continue
    const key = detailSegmentKey(row)
    if (!seen.has(key)) {
      seen.add(key)
      segments.push(key)
    }
  }
  return segments
}

export type DetailMeasure = 'capacity_value' | 'units' | 'own_sales'

/** Pivot detail rows to one point per tick, keyed by segment. Missing
 * cells read as 0; a null own_sales (un-attributed row) reads as 0 in
 * the chart — the exact-value table keeps the literal null as '—', so
 * no information is lost, only the chart's zero-vs-null distinction. */
export function detailSeriesByTick(
  rows: SalesLayerRowRead[],
  measure: DetailMeasure,
): Array<Record<string, number>> {
  const segments = detailSegments(rows)
  const ticks = [...new Set(rows.map((row) => row.tick))].sort((a, b) => a - b)
  return ticks.map((tick) => {
    const point: Record<string, number> = { tick }
    for (const segment of segments) point[segment] = 0
    for (const row of rows) {
      if (row.tick !== tick) continue
      if (typeof row.oem_id !== 'string' || typeof row.product_id !== 'string') continue
      const value = row[measure]
      point[detailSegmentKey(row)] += value === null ? 0 : value
    }
    return point
  })
}
