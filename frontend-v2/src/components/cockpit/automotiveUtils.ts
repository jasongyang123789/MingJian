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
