import { StatusBadge } from '../ui/StatusBadge'
import { domainLabel, shortDate, statusLabel } from '../ui/dataSurfaceUtils'

/** The run-list shape the Simulation page already relies on. */
export interface CockpitRun {
  id: string
  status: string
  domain_id?: string
  company_id?: string
  created_at: string
  tick_count?: number
}

/** 选项文案：推演短号 + 领域 + 中文状态；公司与领域编号不直接显示。 */
export function runOptionLabel(run: CockpitRun): string {
  const parts = [`推演 ${run.id.slice(0, 8)}`]
  const domain = domainLabel(run.domain_id)
  if (domain && domain !== '默认') parts.push(domain)
  parts.push(statusLabel(run.status))
  return parts.join(' · ')
}

export function RunPicker({
  runs,
  selectedId,
  onSelect,
  label = '选择推演',
}: {
  runs: CockpitRun[]
  selectedId: string | null
  onSelect: (runId: string) => void
  label?: string
}) {
  const selected = runs.find((run) => run.id === selectedId)
  return (
    <div className="flex flex-wrap items-center gap-3">
      <label htmlFor="cockpit-run-picker" className="text-xs text-slate-500">
        {label}
      </label>
      <select
        id="cockpit-run-picker"
        value={selectedId ?? ''}
        onChange={(event) => onSelect(event.target.value)}
        className="min-w-64 rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 focus:border-blue-500/50 focus:outline-none"
      >
        <option value="" disabled>
          {runs.length === 0 ? '暂无模拟记录' : '请选择一个推演'}
        </option>
        {runs.map((run) => (
          <option key={run.id} value={run.id}>
            {runOptionLabel(run)}
          </option>
        ))}
      </select>
      {selected && <StatusBadge status={selected.status.toLowerCase()} />}
      {selected && selected.created_at && (
        <span className="text-xs text-slate-500">创建于 {shortDate(selected.created_at)}</span>
      )}
    </div>
  )
}
