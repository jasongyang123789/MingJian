// Living-strategy loop page: loop list + creation, and the timeline
// for the selected loop (trigger registrations, observations,
// iterations with their explicit actions). Every loop action is an
// explicit request — evaluation, re-simulation, comparison, and
// decisions never run on their own — and every refusal surfaces the
// backend's structured error code.

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { simulationApi } from '../api/endpoints'
import { loopsApi, parseApiError } from '../api/engine'
import type { LoopTriggerDefinition } from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import {
  IterationCard,
  ObservationForm,
  ObservationList,
  TriggerBuilder,
  TriggerRegistrations,
} from '../components/cockpit/LoopViews'
import { ITERATION_STATE_LABELS, loopInputClassName } from '../components/cockpit/loopDisplay'
import { RunPicker } from '../components/cockpit/RunPicker'
import type { CockpitRun } from '../components/cockpit/RunPicker'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useApi } from '../hooks/useApi'

function StartIterationForm({ loopId, onStarted }: { loopId: string; onStarted: () => void }) {
  const [decisionTime, setDecisionTime] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    if (!decisionTime) {
      setError('请选择评审时间。')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await loopsApi.startIteration(loopId, { decision_time: new Date(decisionTime).toISOString() })
      setDecisionTime('')
      onStarted()
    } catch (caught: unknown) {
      const info = parseApiError(caught)
      setError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500">
        评审时间即新一轮的证据截断：必须晚于上一截断，重新模拟会看到评审时间之前收集到的全部证据。
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-xs text-slate-500">
          评审时间
          <input
            type="datetime-local"
            value={decisionTime}
            onChange={(event) => setDecisionTime(event.target.value)}
            className={`${loopInputClassName()} mt-1`}
          />
        </label>
        <button
          type="button"
          disabled={busy}
          onClick={submit}
          className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3.5 py-1.5 text-sm text-blue-300 transition-colors hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:text-slate-600"
        >
          {busy ? '开启中…' : '开启新一轮评审'}
        </button>
      </div>
      {error && <ErrorBanner message={error} />}
    </div>
  )
}

export default function LivingLoop() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedLoopId, setSelectedLoopId] = useState<string | null>(searchParams.get('loop'))
  const [showCreate, setShowCreate] = useState(false)
  const [loopName, setLoopName] = useState('')
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null)
  const [pendingTriggers, setPendingTriggers] = useState<LoopTriggerDefinition[]>([])
  const [createBusy, setCreateBusy] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [registerError, setRegisterError] = useState<string | null>(null)

  const { data: runs } = useApi(() => simulationApi.listRuns())
  const {
    data: loops,
    loading: loopsLoading,
    error: loopsError,
    reload: reloadLoops,
  } = useApi(() => loopsApi.listLoops())
  const {
    data: timeline,
    loading: timelineLoading,
    error: timelineError,
    reload: reloadTimeline,
  } = useApi(
    () => (selectedLoopId ? loopsApi.getTimeline(selectedLoopId) : Promise.resolve(null)),
    selectedLoopId,
  )

  function selectLoop(loopId: string) {
    setSelectedLoopId(loopId)
    setSearchParams({ loop: loopId })
  }

  async function createLoop() {
    if (!loopName.trim() || !baselineRunId) {
      setCreateError('循环名称与基线 Run 都必须选择。')
      return
    }
    setCreateError(null)
    setCreateBusy(true)
    try {
      const created = await loopsApi.createLoop({
        baseline_run_id: baselineRunId,
        name: loopName.trim(),
        triggers: pendingTriggers,
      })
      setLoopName('')
      setBaselineRunId(null)
      setPendingTriggers([])
      setShowCreate(false)
      await reloadLoops()
      selectLoop(created.id)
    } catch (caught: unknown) {
      const info = parseApiError(caught)
      setCreateError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setCreateBusy(false)
    }
  }

  async function registerTriggers(triggers: LoopTriggerDefinition[], supersedes: string | null) {
    if (!selectedLoopId) return
    setRegisterError(null)
    try {
      await loopsApi.registerTriggers(selectedLoopId, { triggers, supersedes })
      reloadTimeline()
    } catch (caught: unknown) {
      const info = parseApiError(caught)
      setRegisterError(info.code ? `${info.code}：${info.message}` : info.message)
    }
  }

  const activeRegistration = timeline?.loop.triggers.find((item) => item.status === 'active')
  const openIteration = timeline?.iterations.find((item) => item.state !== 'decided')

  return (
    <div className="space-y-6">
      <CockpitNav />
      <div>
        <h2 className="text-2xl font-bold text-slate-100">活战略循环</h2>
        <p className="mt-1 text-sm text-slate-400">
          监测实际值 → 评估预注册触发器 → 用新证据重新模拟 → 分布对分布比较 → 记录评审决策。循环记录是审计轨迹：只追加、不静默修改，修正靠新一轮评审。
        </p>
      </div>

      <Card>
        <CardHeader
          title="战略循环"
          action={
            <button
              type="button"
              onClick={() => setShowCreate(!showCreate)}
              className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3 py-1 text-xs text-blue-300 transition-colors hover:bg-blue-500/20"
            >
              {showCreate ? '取消新建' : '新建循环'}
            </button>
          }
        />
        <CardBody>
          {loopsLoading && <LoadingSpinner />}
          {loopsError && <ErrorBanner message={loopsError} onRetry={reloadLoops} />}
          {!loopsLoading && !loopsError && (loops === null || loops.length === 0) && (
            <EmptyState
              title="暂无战略循环"
              description="从一个已完成的 Run 创建循环：基线 Run 的分解、模板与绑定会成为重模拟的起点。"
            />
          )}
          {loops && loops.length > 0 && (
            <div className="space-y-2">
              {loops.map((loop) => (
                <button
                  key={loop.id}
                  type="button"
                  onClick={() => selectLoop(loop.id)}
                  className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
                    loop.id === selectedLoopId
                      ? 'border-blue-500/30 bg-blue-500/10'
                      : 'border-slate-700/50 hover:bg-slate-800/40'
                  }`}
                >
                  <span className="text-sm font-medium text-slate-100">{loop.name}</span>
                  <span className="ml-2 text-xs text-slate-500">
                    {loop.domain_id} · 基线 Run {loop.baseline_run_id.slice(0, 8)} ·{' '}
                    {loop.triggers.length} 次触发器注册
                  </span>
                </button>
              ))}
            </div>
          )}
          {showCreate && (
            <div className="mt-4 space-y-4 border-t border-slate-800/60 pt-4">
              <label className="block text-xs text-slate-500">
                循环名称
                <input
                  value={loopName}
                  onChange={(event) => setLoopName(event.target.value)}
                  placeholder="例如 AI 客服线"
                  className={`${loopInputClassName()} mt-1`}
                />
              </label>
              {runs && (
                <RunPicker
                  runs={runs as CockpitRun[]}
                  selectedId={baselineRunId}
                  onSelect={setBaselineRunId}
                  label="基线 Run（须已完成）"
                />
              )}
              <div>
                <h4 className="mb-2 text-sm font-medium text-slate-200">初始触发器（可选）</h4>
                <TriggerBuilder
                  submitLabel="确定初始触发器"
                  onSubmit={(triggers) => setPendingTriggers(triggers)}
                />
                {pendingTriggers.length > 0 && (
                  <p className="mt-2 text-xs text-slate-400">
                    已选择 {pendingTriggers.length} 个触发器：{pendingTriggers.map((t) => t.name).join('、')}
                    <button
                      type="button"
                      onClick={() => setPendingTriggers([])}
                      className="ml-2 text-red-400 hover:text-red-300"
                    >
                      清除
                    </button>
                  </p>
                )}
              </div>
              {createError && <ErrorBanner message={createError} />}
              <button
                type="button"
                disabled={createBusy}
                onClick={createLoop}
                className="rounded-full border border-blue-500/30 bg-blue-500/10 px-3.5 py-1.5 text-sm text-blue-300 transition-colors hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:text-slate-600"
              >
                {createBusy ? '创建中…' : '创建循环'}
              </button>
            </div>
          )}
        </CardBody>
      </Card>

      {!selectedLoopId && (
        <EmptyState title="请选择一个循环" description="时间线展示该循环的触发器、观测记录与历次评审。" />
      )}

      {selectedLoopId && timelineLoading && <LoadingSpinner />}
      {selectedLoopId && timelineError && <ErrorBanner message={timelineError} onRetry={reloadTimeline} />}
      {selectedLoopId && timeline && (
        <>
          <Card>
            <CardHeader title={`时间线：${timeline.loop.name}`} />
            <CardBody>
              <p className="text-sm text-slate-400">
                基线 Run <span className="font-mono text-xs">{timeline.loop.baseline_run_id}</span> · 域{' '}
                {timeline.loop.domain_id} · 创建于 {timeline.loop.created_at}
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="触发器（预注册）" />
            <CardBody>
              <div className="space-y-4">
                <TriggerRegistrations registrations={timeline.loop.triggers} />
                <div className="border-t border-slate-800/60 pt-4">
                  <h4 className="mb-2 text-sm font-medium text-slate-200">注册新触发器集</h4>
                  <TriggerBuilder
                    submitLabel="注册触发器"
                    supersedeOption={
                      activeRegistration ? { activeRegistrationId: activeRegistration.id } : undefined
                    }
                    onSubmit={registerTriggers}
                  />
                  {registerError && <ErrorBanner message={registerError} />}
                </div>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="观测记录" />
            <CardBody>
              <div className="space-y-4">
                <ObservationList observations={timeline.observations} />
                <div className="border-t border-slate-800/60 pt-4">
                  <h4 className="mb-2 text-sm font-medium text-slate-200">记录观测</h4>
                  <ObservationForm loopId={timeline.loop.id} onRecorded={reloadTimeline} />
                </div>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="评审轮次" />
            <CardBody>
              <div className="space-y-4">
                {timeline.iterations.length === 0 && (
                  <EmptyState
                    title="尚未开启评审"
                    description="开启一轮评审：选定评审时间（新证据截断），评估窗口内的触发器，再决定是否重新模拟。"
                  />
                )}
                {timeline.iterations.map((iteration) => (
                  <IterationCard key={iteration.id} iteration={iteration} onChanged={reloadTimeline} />
                ))}
                {openIteration ? (
                  <p className="text-xs text-slate-500">
                    评审 #{openIteration.index} 尚未决策（{ITERATION_STATE_LABELS[openIteration.state]}）：
                    先记录其决策，再开启下一轮。
                  </p>
                ) : (
                  <div className="border-t border-slate-800/60 pt-4">
                    <StartIterationForm loopId={timeline.loop.id} onStarted={reloadTimeline} />
                  </div>
                )}
              </div>
            </CardBody>
          </Card>
        </>
      )}
    </div>
  )
}
