// Distribution charts page: ensemble histograms from stored trial
// values plus tornado / bootstrap / threshold-search charts over the
// stored Sprint 4 results. Every chart degrades honestly — no
// ensemble, no trial values, or no stored analysis each renders an
// empty state explaining what to run, and nothing is ever synthesized
// from summary statistics. Each empty state that names a POST endpoint
// also offers a launch button for it (Sprint 12); launching reloads
// the stored fragment, so charts still only ever render stored data.

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { simulationApi } from '../api/endpoints'
import { distributionsApi, nullOn404, robustnessApi } from '../api/engine'
import type { MonteCarloResult } from '../api/engineTypes'
import {
  BootstrapLauncher,
  MonteCarloLauncher,
  ThresholdSearchLauncher,
  TornadoLauncher,
} from '../components/cockpit/AnalysisLaunchers'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import { EnsembleHistograms } from '../components/cockpit/DistributionCharts'
import { BootstrapChart, ThresholdSearchChart, TornadoChart } from '../components/cockpit/RobustnessCharts'
import { RunPicker } from '../components/cockpit/RunPicker'
import type { CockpitRun } from '../components/cockpit/RunPicker'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useApi } from '../hooks/useApi'

function EnsembleSection({ runId, result }: { runId: string; result: MonteCarloResult }) {
  const { data: trialValues, loading, error, reload } = useApi(
    () => nullOn404(distributionsApi.getTrialValues(runId)),
    runId,
  )
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  if (trialValues === null) {
    return (
      <EmptyState
        title="试验值不可用"
        description="该模拟集合存在，但试验行缺失或不完整，无法画出分布直方图。此处不会用摘要统计量伪造分布。"
      />
    )
  }
  return <EnsembleHistograms result={result} trialValues={trialValues} />
}

function RobustnessSection({ runId, refreshSignal }: { runId: string; refreshSignal: number }) {
  const { data, loading, error, reload } = useApi(
    () => nullOn404(robustnessApi.getAll(runId)),
    `${runId}:${refreshSignal}`,
  )
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  if (data === null) {
    return (
      <EmptyState
        title="暂无稳健性分析"
        description="该推演尚未存储任何稳健性分析结果。先运行一次蒙特卡洛模拟集合，再运行龙卷风、自助法或阈值搜索分析。"
      />
    )
  }
  return (
    <div className="space-y-8">
      <div>
        <h4 className="mb-2 text-sm font-medium text-slate-200">龙卷风图（敏感性）</h4>
        {data.tornado ? (
          <TornadoChart tornado={data.tornado} />
        ) : (
          <>
            <EmptyState
              title="尚未运行龙卷风分析"
              description="对该推演的模拟集合运行一次龙卷风分析，图表会在此出现。"
            />
            <TornadoLauncher runId={runId} onLaunched={reload} />
          </>
        )}
      </div>
      <div>
        <h4 className="mb-2 text-sm font-medium text-slate-200">自助法区间</h4>
        {data.bootstrap ? (
          <BootstrapChart bootstrap={data.bootstrap} />
        ) : (
          <>
            <EmptyState
              title="尚未运行自助法分析"
              description="对该推演的模拟集合运行一次自助法分析，图表会在此出现。"
            />
            <BootstrapLauncher runId={runId} onLaunched={reload} />
          </>
        )}
      </div>
      <div>
        <h4 className="mb-2 text-sm font-medium text-slate-200">阈值搜索</h4>
        {data.threshold_search ? (
          <ThresholdSearchChart search={data.threshold_search} />
        ) : (
          <>
            <EmptyState
              title="尚未运行阈值搜索"
              description="对该推演的模拟集合运行一次阈值搜索，图表会在此出现。"
            />
            <ThresholdSearchLauncher runId={runId} onLaunched={reload} />
          </>
        )}
      </div>
    </div>
  )
}

export default function Charts() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: runs, loading, error, reload } = useApi(() => simulationApi.listRuns())
  const [selectedRunId, setSelectedRunId] = useState<string | null>(searchParams.get('run'))
  // Bumped after an ensemble launch: the robustness section refetches so
  // its per-analysis launchers appear once the ensemble exists.
  const [robustnessRefresh, setRobustnessRefresh] = useState(0)

  const {
    data: ensemble,
    loading: ensembleLoading,
    error: ensembleError,
    reload: reloadEnsemble,
  } = useApi(
    () =>
      selectedRunId
        ? nullOn404(distributionsApi.getMonteCarlo(selectedRunId))
        : Promise.resolve(null),
    selectedRunId,
  )

  function selectRun(runId: string) {
    setSelectedRunId(runId)
    setSearchParams({ run: runId })
  }

  function handleEnsembleLaunched() {
    reloadEnsemble()
    setRobustnessRefresh((count) => count + 1)
  }

  const selectedRun = (runs as CockpitRun[] | null)?.find((run) => run.id === selectedRunId) ?? null

  return (
    <div className="space-y-6">
      <CockpitNav />
      <div>
        <h2 className="text-2xl font-bold text-slate-100">分布图表</h2>
        <p className="mt-1 text-sm text-slate-400">
          只画真实存储的数据：ensemble 直方图来自 trial 值，龙卷风、bootstrap 与阈值搜索图来自存储的稳健性分析结果。没有数据时如实显示空状态。
        </p>
      </div>

      {loading && <LoadingSpinner />}
      {error && <ErrorBanner message={error} onRetry={reload} />}
      {runs && (
        <RunPicker
          runs={runs as CockpitRun[]}
          selectedId={selectedRunId}
          onSelect={selectRun}
          label="选择推演"
        />
      )}

      {!selectedRunId && (
        <EmptyState title="请选择一个推演" description="图表展示该推演已存储的模拟集合与稳健性分析结果" />
      )}

      {selectedRunId && (
        <Card>
          <CardHeader title={`模拟集合分布（${selectedRun?.id ?? selectedRunId}）`} />
          <CardBody>
            {ensembleLoading && <LoadingSpinner />}
            {ensembleError && <ErrorBanner message={ensembleError} onRetry={reloadEnsemble} />}
            {!ensembleLoading && !ensembleError && ensemble === null && (
              <>
                <EmptyState
                  title="暂无模拟集合结果"
                  description="该推演尚未存储蒙特卡洛模拟集合结果。先对该推演运行一次模拟集合，分布图会在此出现。"
                />
                <MonteCarloLauncher runId={selectedRunId} onLaunched={handleEnsembleLaunched} />
              </>
            )}
            {!ensembleLoading && !ensembleError && ensemble !== null && (
              <EnsembleSection runId={selectedRunId} result={ensemble} />
            )}
          </CardBody>
        </Card>
      )}

      {selectedRunId && (
        <Card>
          <CardHeader title="稳健性图表" />
          <CardBody>
            <RobustnessSection runId={selectedRunId} refreshSignal={robustnessRefresh} />
          </CardBody>
        </Card>
      )}
    </div>
  )
}
