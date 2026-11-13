import { useState } from 'react'

import { simulationApi } from '../api/endpoints'
import {
  calibrationApi,
  distributionsApi,
  meceApi,
  nullOn404,
  robustnessApi,
  variablesApi,
} from '../api/engine'
import type {
  CalibrationFitRead,
  DecisionGatesRead,
  DeterminismRead,
  FirewallRead,
  MeceRunRead,
  MonteCarloResult,
  RobustnessRead,
  VariableRunRead,
} from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import {
  CalibrationFitsView,
  DecisionGatesView,
  DeterminismView,
  EnsembleView,
  FirewallView,
  RobustnessView,
  VariableBindingsView,
} from '../components/cockpit/RunArtifacts'
import { RunPicker } from '../components/cockpit/RunPicker'
import type { CockpitRun } from '../components/cockpit/RunPicker'
import { MeceTreeView, MeceValidationView } from '../components/cockpit/MeceViews'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useApi } from '../hooks/useApi'

function FragmentSection<T>({
  title,
  runId,
  fetcher,
  emptyText,
  children,
}: {
  title: string
  runId: string
  fetcher: () => Promise<T | null>
  emptyText: string
  children: (data: T) => React.ReactNode
}) {
  const { data, loading, error, reload } = useApi(fetcher, runId)
  return (
    <Card>
      <CardHeader title={title} />
      <CardBody>
        {loading && <LoadingSpinner />}
        {error && !loading && <ErrorBanner message={error} onRetry={reload} />}
        {!loading && !error && data === null && <EmptyState icon="📭" title={emptyText} />}
        {!loading && !error && data !== null && data !== undefined && children(data)}
      </CardBody>
    </Card>
  )
}

export default function Cockpit() {
  const { data: runs, loading, error, reload } = useApi(() => simulationApi.listRuns())
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />

  const runList = (runs || []) as CockpitRun[]
  const selectedRun = runList.find((run) => run.id === selectedRunId) ?? null

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">推演驾驶舱</h1>
        <p className="mt-1 text-sm text-slate-500">
          一个 Run 的全部数值工件：MECE 分解、变量绑定、分布、稳健性、防火墙审计与校准历史
        </p>
      </div>

      <CockpitNav />

      <RunPicker runs={runList} selectedId={selectedRunId} onSelect={setSelectedRunId} />

      {!selectedRun && (
        <EmptyState icon="🧭" title="请选择一个 Run" description="驾驶舱展示该 Run 已存储的全部 Sprint 1–5 工件" />
      )}

      {selectedRun && (
        <>
          <FragmentSection<MeceRunRead>
            title="MECE 分解"
            runId={selectedRun.id}
            fetcher={() => nullOn404(meceApi.getForRun(selectedRun.id))}
            emptyText="该 Run 未挂分解树"
          >
            {(data) => (
              <div className="space-y-5">
                <MeceTreeView tree={data.decomposition} />
                <MeceValidationView validation={data.validation} />
              </div>
            )}
          </FragmentSection>

          <FragmentSection<VariableRunRead>
            title="变量绑定"
            runId={selectedRun.id}
            fetcher={() => nullOn404(variablesApi.getForRun(selectedRun.id))}
            emptyText="该 Run 未挂变量绑定"
          >
            {(data) => <VariableBindingsView data={data} />}
          </FragmentSection>

          <FragmentSection<MonteCarloResult>
            title="分布（Monte Carlo ensemble）"
            runId={selectedRun.id}
            fetcher={() => nullOn404(distributionsApi.getMonteCarlo(selectedRun.id))}
            emptyText="该 Run 尚未运行 Monte Carlo"
          >
            {(data) => <EnsembleView result={data} />}
          </FragmentSection>

          <FragmentSection<DeterminismRead>
            title="确定性审计"
            runId={selectedRun.id}
            fetcher={() => nullOn404(distributionsApi.getDeterminism(selectedRun.id))}
            emptyText="该 Run 暂无确定性审计数据"
          >
            {(data) => <DeterminismView data={data} />}
          </FragmentSection>

          <FragmentSection<RobustnessRead>
            title="稳健性评估"
            runId={selectedRun.id}
            fetcher={() => nullOn404(robustnessApi.getAll(selectedRun.id))}
            emptyText="该 Run 尚未存储稳健性分析"
          >
            {(data) => <RobustnessView data={data} />}
          </FragmentSection>

          <FragmentSection<DecisionGatesRead>
            title="决策门"
            runId={selectedRun.id}
            fetcher={() => nullOn404(robustnessApi.getGates(selectedRun.id))}
            emptyText="该 Run 尚未注册决策门"
          >
            {(data) => <DecisionGatesView data={data} />}
          </FragmentSection>

          <FragmentSection<FirewallRead>
            title="防后视防火墙审计"
            runId={selectedRun.id}
            fetcher={() => nullOn404(calibrationApi.getFirewall(selectedRun.id))}
            emptyText="该 Run 暂无防火墙审计数据"
          >
            {(data) => <FirewallView data={data} />}
          </FragmentSection>

          <FragmentSection<CalibrationFitRead[]>
            title="校准拟合历史"
            runId={selectedRun.id}
            fetcher={() =>
              calibrationApi.listFits(
                selectedRun.domain_id ? { domain_id: selectedRun.domain_id, limit: 50 } : { limit: 50 },
              )
            }
            emptyText="该领域尚无校准拟合记录"
          >
            {(data) => <CalibrationFitsView fits={data} />}
          </FragmentSection>
        </>
      )}
    </div>
  )
}
