import { Database, RefreshCw, Signal, Star } from 'lucide-react'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { sourcesApi } from '../api/endpoints'
import { useApi, useApiAction } from '../hooks/useApi'
import { ExpandableRecord, MetricCard } from '../components/ui/DataSurface'
import { asArray, asRecord, sourceTypeLabel, statusLabel, titleOf } from '../components/ui/dataSurfaceUtils'

/** 显示名取可读名：URL 只取域名，类型码翻成中文，其余原样。 */
function readableSourceName(record: Record<string, unknown>): string {
  const display = String(record.display_name ?? record.source_key ?? '')
  if (!display) return '数据源'
  if (/^https?:\/\//i.test(display)) {
    try {
      return new URL(display).hostname
    } catch {
      return display
    }
  }
  return sourceTypeLabel(display) || display
}

export default function Sources() {
  const { data: states, loading, error, reload } = useApi(() => sourcesApi.listStates())
  const { data: reputations } = useApi(() => sourcesApi.listReputations())
  const { data: health } = useApi(() => sourcesApi.listHealth().catch(() => null))
  const { data: snapshots } = useApi(() => sourcesApi.listSnapshots().catch(() => null))
  const { data: changes } = useApi(() => sourcesApi.listChanges())
  const { execute: reanalyze, loading: reanalyzing } = useApiAction((id: string) => sourcesApi.reanalyzeChange(id))

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />

  const stateList = asArray(states)
  const reputationList = asArray(reputations)
  const changeList = asArray(changes)

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs text-blue-300">数据源</p>
          <h1 className="mt-1 text-3xl font-semibold text-slate-50">数据源</h1>
          <p className="mt-2 text-sm text-slate-500">
            开源版使用内置公开数据源；自定义数据源连接器保留在 Cloud 和 Enterprise。
          </p>
        </div>
        <button onClick={reload} className="glass-button inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm text-slate-200">
          <RefreshCw className="h-4 w-4" />刷新
        </button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <MetricCard label="源状态" value={stateList.length} icon={<Database className="h-5 w-5" />} tone="blue" />
        <MetricCard label="声誉记录" value={reputationList.length} icon={<Star className="h-5 w-5" />} tone="amber" />
        <MetricCard label="增量变更" value={changeList.length} icon={<Signal className="h-5 w-5" />} tone="slate" />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_1fr]">
        <Card>
          <CardHeader title="数据源状态" />
          {stateList.length === 0 ? (
            <CardBody><EmptyState icon="▥" title="暂无源状态" /></CardBody>
          ) : (
            stateList.map((item, index) => <ExpandableRecord key={index} item={item} eyebrow="数据源" />)
          )}
        </Card>
        <Card>
          <CardHeader title="健康与声誉快照" />
          <CardBody className="space-y-4">
            {reputationList.length === 0 && asArray(health).length === 0 && asArray(snapshots).length === 0 ? (
              <EmptyState icon="▥" title="暂无健康与声誉数据" />
            ) : (
              <>
                {reputationList.length > 0 && (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                      <thead>
                        <tr className="border-b border-slate-800 text-xs text-slate-500">
                          <th className="py-2 pr-3 font-medium">来源名</th>
                          <th className="py-2 pr-3 font-medium">类型</th>
                          <th className="py-2 font-medium">声誉分</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/60">
                        {reputationList.map((item, index) => {
                          const record = asRecord(item)
                          const score = Number(record.reputation_score)
                          return (
                            <tr key={index}>
                              <td className="py-2 pr-3 text-slate-200">{readableSourceName(record)}</td>
                              <td className="py-2 pr-3 text-slate-400">{sourceTypeLabel(record.source_type) || '其他'}</td>
                              <td className="py-2 text-slate-200">{Number.isFinite(score) ? `${Math.round(score * 100)}%` : '—'}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
                {asArray(health).length > 0 && (
                  <div className="space-y-2">
                    {asArray(health).map((item, index) => {
                      const record = asRecord(item)
                      return (
                        <div key={index} className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-slate-300">{sourceTypeLabel(record.source_type) || '数据源'}</span>
                          <span className="text-xs text-slate-500">
                            {statusLabel(record.status)}
                            {Number(record.consecutive_failures) > 0 ? ` · 连续失败 ${record.consecutive_failures} 次` : ''}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )}
                {asArray(snapshots).length > 0 && (
                  <p className="text-xs text-slate-500">快照 {asArray(snapshots).length} 条</p>
                )}
              </>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="增量变更" />
        {changeList.length === 0 ? (
          <CardBody><EmptyState icon="▦" title="暂无变更" /></CardBody>
        ) : (
          changeList.slice(0, 12).map((item, index) => {
            const record = asRecord(item)
            const id = String(record.id ?? record.change_id ?? '')
            return (
              <div key={id || index} className="border-b border-slate-800/50 px-5 py-4 last:border-b-0">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium text-slate-100">{titleOf(item, `变更 ${index + 1}`)}</p>
                    <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                      {String(record.summary ?? record.description ?? record.source_key ?? '')}
                    </p>
                  </div>
                  <button
                    disabled={!id || reanalyzing}
                    onClick={() => reanalyze(id).then(reload)}
                    className="rounded-md border border-blue-400/20 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-300 disabled:opacity-50"
                  >
                    重分析
                  </button>
                </div>
              </div>
            )
          })
        )}
      </Card>
    </div>
  )
}
