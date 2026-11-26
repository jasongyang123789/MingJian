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

/** 后端状态码 → 中文标签（全站集中映射；界面不再直接显示英文状态码）。 */
const STATUS_LABELS: Record<string, string> = {
  active: '有效',
  online: '在线',
  offline: '离线',
  completed: '已完成',
  running: '运行中',
  pending: '待处理',
  failed: '失败',
  error: '异常',
  accepted: '已接受',
  rejected: '已拒绝',
  verified: '已验证',
  refuted: '已驳回',
  configured: '已配置',
  env: '未配置',
  paused: '已暂停',
  attention: '注意',
  ready: '正常',
  dev_fallback: '开发版备用',
  unknown: '未知',
  adopt: '采纳',
  defer: '推迟',
  need_more_info: '需更多信息',
  reject: '拒绝',
  in_progress: '进行中',
  queued: '排队中',
  cancelled: '已取消',
  timeout: '超时',
  skipped: '已跳过',
  draft: '草稿',
  approved: '已批准',
  superseded: '已替代',
  passed: '通过',
  warning: '警告',
  healthy: '正常',
  unhealthy: '异常',
  ok: '正常',
  created: '已创建',
  archived: '已归档',
}

export function statusLabel(value: unknown): string {
  if (value == null) return '未知'
  const raw = String(value).trim()
  if (!raw) return '未知'
  const mapped = STATUS_LABELS[raw.toLowerCase()]
  if (mapped) return mapped
  // 已是中文或其他可读文本时原样显示；纯英文编码兜底为“未知”
  if (/[\u4e00-\u9fff]/.test(raw)) return raw
  if (/^[a-z0-9_]+$/i.test(raw)) return '未知'
  return raw
}

/** 领域编号 → 中文标签；未知编号返回空（调用方自行隐藏）。 */
const DOMAIN_LABELS: Record<string, string> = {
  automotive: '汽车',
  corporate: '企业',
  auto: '汽车',
  default: '默认',
}

export function domainLabel(value: unknown): string {
  if (value == null) return ''
  const raw = String(value).trim()
  if (!raw) return ''
  return DOMAIN_LABELS[raw.toLowerCase()] ?? ''
}

/** 来源类型码 → 中文标签。 */
const SOURCE_TYPE_LABELS: Record<string, string> = {
  rss_feed: '订阅源',
  blog: '博客',
  analyst_note: '分析师笔记',
}

export function sourceTypeLabel(value: unknown): string {
  if (value == null) return ''
  const raw = String(value).trim()
  if (!raw) return ''
  return SOURCE_TYPE_LABELS[raw.toLowerCase()] ?? ''
}

/** 推演模式码 → 中文标签（standard / deep / quick）。 */
const MODE_LABELS: Record<string, string> = {
  standard: '标准',
  deep: '深度',
  quick: '快速',
}

export function modeLabel(value: unknown): string {
  if (value == null) return ''
  const raw = String(value).trim()
  if (!raw) return ''
  return MODE_LABELS[raw.toLowerCase()] ?? raw
}
