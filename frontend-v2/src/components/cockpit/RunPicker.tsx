import { StatusBadge } from '../ui/StatusBadge'

/** The run-list shape the Simulation page already relies on. */
export interface CockpitRun {
  id: string
  status: string
  domain_id?: string
  company_id?: string
  created_at: string
  tick_count?: number
}

export function RunPicker({
  runs,
  selectedId,
  onSelect,
  label = '选择模拟 Run',
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
          {runs.length === 0 ? '暂无模拟记录' : '请选择一个 Run'}
        </option>
        {runs.map((run) => (
          <option key={run.id} value={run.id}>
            {run.company_id || run.id.slice(0, 8)} · {run.domain_id ?? '—'} · {run.status}
          </option>
        ))}
      </select>
      {selected && <StatusBadge status={selected.status.toLowerCase()} />}
      {selected && (
        <span className="font-mono text-xs text-slate-500">{selected.id}</span>
      )}
    </div>
  )
}
