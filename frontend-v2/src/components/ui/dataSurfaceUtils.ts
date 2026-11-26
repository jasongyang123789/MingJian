export type DataRecord = Record<string, unknown>

export function asArray<T = DataRecord>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[]
  if (value && typeof value === 'object') {
    const record = value as DataRecord
    for (const key of ['items', 'results', 'data', 'tasks', 'agents', 'predictions', 'watch_rules']) {
      if (Array.isArray(record[key])) return record[key] as T[]
    }
  }
  return []
}

export function asRecord(value: unknown): DataRecord {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as DataRecord : {}
}

export function textValue(value: unknown, fallback = '—') {
  if (typeof value === 'string' && value.trim()) return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

export function titleOf(item: unknown, fallback = '未命名') {
  const record = asRecord(item)
  const named = textValue(
    record.title ?? record.name ?? record.topic ?? record.label ?? record.statement,
    ''
  )
  if (named) return named
  // 没有名字时不再直接露编号：用公司/领域 + 创建时间拼一个可读标签
  const who = textValue(
    record.company_id ?? record.company ?? record.domain_id ?? record.domain,
    ''
  )
  const when = shortDate(record.created_at ?? record.createdAt ?? record.updated_at ?? record.timestamp)
  const label = [who, when].filter(Boolean).join(' · ')
  if (label) return label
  return fallback
}

/** 紧凑日期：2026-11-26T05:47:16 → "11-26 13:47"（本地时间） */
export function shortDate(value: unknown) {
  if (typeof value !== 'string' || !value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const mm = String(date.getMonth() + 1).padStart(2, '0')
  const dd = String(date.getDate()).padStart(2, '0')
  const hh = String(date.getHours()).padStart(2, '0')
  const min = String(date.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${min}`
}

export function formatDate(value: unknown) {
  if (typeof value !== 'string' || !value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function metricNumber(value: unknown) {
  if (typeof value === 'number') return value.toLocaleString()
  if (Array.isArray(value)) return value.length.toLocaleString()
  if (value && typeof value === 'object') return Object.keys(value).length.toLocaleString()
  if (value == null || value === '') return '0'
  return String(value)
}
