// Analysis launchers for the Charts page: run a stored analysis for the
// selected run from its empty state, then reload the stored fragment so
// charts always render stored data (Sprint 8 discipline — the POST
// response is never rendered directly). Payloads use the backend
// defaults read from the Sprint 3/4 request models; the only
// user-supplied values are the ones the backend requires with no
// default (the monte-carlo metric, the threshold-search variable and
// target). Failures surface the backend's message honestly with a
// retry; nothing is fabricated while an analysis is missing or failed.

import { useCallback, useState } from 'react'
import type { ReactNode } from 'react'

import {
  distributionsApi,
  nullOn404,
  parseApiError,
  robustnessApi,
  variablesApi,
} from '../../api/engine'
import type {
  BootstrapRequest,
  MonteCarloRequest,
  ThresholdSearchRequest,
  TornadoRequest,
} from '../../api/engineTypes'
import { useApi } from '../../hooks/useApi'
import { ErrorBanner } from '../ui/ErrorBanner'
import { loopInputClassName } from './loopDisplay'

function useLaunchAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const launch = useCallback(async (run: () => Promise<unknown>, onDone: () => void) => {
    setBusy(true)
    setError(null)
    try {
      await run()
      onDone()
    } catch (caught: unknown) {
      const info = parseApiError(caught)
      setError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setBusy(false)
    }
  }, [])

  return { busy, error, launch }
}

function useRunVariables(runId: string) {
  return useApi(() => nullOn404(variablesApi.getForRun(runId)), runId)
}

function LauncherShell({
  children,
  busy,
  error,
  onRetry,
  onLaunch,
  launchDisabled,
  launchLabel,
  note,
}: {
  children?: ReactNode
  busy: boolean
  error: string | null
  onRetry: () => void
  onLaunch: () => void
  launchDisabled: boolean
  launchLabel: string
  note: string
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 pb-2">
      {children}
      <button
        onClick={onLaunch}
        disabled={busy || launchDisabled}
        className="rounded-lg bg-blue-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-600 disabled:opacity-50"
      >
        {busy ? '运行中…' : launchLabel}
      </button>
      <p className="max-w-md text-center text-xs leading-5 text-slate-500">{note}</p>
      {error && (
        <div className="w-full">
          <ErrorBanner message={error} onRetry={onRetry} />
        </div>
      )}
    </div>
  )
}

const SELECT_CLASS = 'rounded-lg border border-slate-700/50 bg-slate-800/40 px-2 py-1.5 text-xs text-slate-200 focus:border-blue-500/50 focus:outline-none'

export function MonteCarloLauncher({
  runId,
  onLaunched,
}: {
  runId: string
  onLaunched: () => void
}) {
  const { busy, error, launch } = useLaunchAction()
  const { data: variables, loading: variablesLoading } = useRunVariables(runId)
  const [metricInput, setMetricInput] = useState('')
  const stateFields = variables?.template?.state_fields ?? []
  const metric = metricInput.trim() !== '' ? metricInput.trim() : (stateFields[0]?.name ?? '')

  function handleLaunch() {
    if (!metric) return
    const payload: MonteCarloRequest = {
      trials: 50,
      seed: null,
      metric,
      loss_threshold: 0,
      strategy_levers: {},
    }
    void launch(() => distributionsApi.runMonteCarlo(runId, payload), onLaunched)
  }

  return (
    <LauncherShell
      busy={busy}
      error={error}
      onRetry={handleLaunch}
      onLaunch={handleLaunch}
      launchDisabled={metric === ''}
      launchLabel="运行 Ensemble"
      note={
        stateFields.length > 0
          ? '试验数 50、loss_threshold 0、无策略杠杆、seed 由后端定（后端默认值）。'
          : '未取到该 Run 的状态字段，手动输入指标名，后端会校验它是否为该领域的状态字段。试验数 50、loss_threshold 0、无策略杠杆（后端默认值）。'
      }
    >
      {variablesLoading ? (
        <p className="text-xs text-slate-500">正在加载该 Run 的状态字段…</p>
      ) : stateFields.length > 0 ? (
        <span className="flex items-center gap-2">
          <label htmlFor="mc-metric" className="text-xs text-slate-400">
            指标
          </label>
          <select
            id="mc-metric"
            value={metric}
            onChange={(event) => setMetricInput(event.target.value)}
            className={SELECT_CLASS}
          >
            {stateFields.map((field) => (
              <option key={field.name} value={field.name}>
                {field.name}
              </option>
            ))}
          </select>
        </span>
      ) : (
        <span className="flex items-center gap-2">
          <label htmlFor="mc-metric" className="text-xs text-slate-400">
            指标
          </label>
          <input
            id="mc-metric"
            value={metricInput}
            onChange={(event) => setMetricInput(event.target.value)}
            placeholder="如 cash"
            className={loopInputClassName()}
          />
        </span>
      )}
    </LauncherShell>
  )
}

export function TornadoLauncher({
  runId,
  onLaunched,
}: {
  runId: string
  onLaunched: () => void
}) {
  const { busy, error, launch } = useLaunchAction()

  function handleLaunch() {
    const payload: TornadoRequest = {
      low_quantile: 0.1,
      high_quantile: 0.9,
      seed: null,
      variables: null,
    }
    void launch(() => robustnessApi.tornado(runId, payload), onLaunched)
  }

  return (
    <LauncherShell
      busy={busy}
      error={error}
      onRetry={handleLaunch}
      onLaunch={handleLaunch}
      launchDisabled={false}
      launchLabel="运行龙卷风分析"
      note="分位数 0.10 / 0.90，全部变量（后端默认值）。"
    />
  )
}

export function BootstrapLauncher({
  runId,
  onLaunched,
}: {
  runId: string
  onLaunched: () => void
}) {
  const { busy, error, launch } = useLaunchAction()

  function handleLaunch() {
    const payload: BootstrapRequest = {
      statistics: ['mean', 'median', 'p_loss'],
      draws: 1000,
      seed: null,
      level: 0.9,
    }
    void launch(() => robustnessApi.bootstrap(runId, payload), onLaunched)
  }

  return (
    <LauncherShell
      busy={busy}
      error={error}
      onRetry={handleLaunch}
      onLaunch={handleLaunch}
      launchDisabled={false}
      launchLabel="运行 Bootstrap 分析"
      note="统计量 mean / median / p_loss，1000 次 draws，level 0.90（后端默认值）。"
    />
  )
}

export function ThresholdSearchLauncher({
  runId,
  onLaunched,
}: {
  runId: string
  onLaunched: () => void
}) {
  const { busy, error, launch } = useLaunchAction()
  const { data: variables, loading: variablesLoading } = useRunVariables(runId)
  const [variableInput, setVariableInput] = useState('')
  const [targetInput, setTargetInput] = useState('0.5')
  const boundIds = variables?.bindings?.variables.map((variable) => variable.id) ?? []
  const variable =
    variableInput.trim() !== '' ? variableInput.trim() : (boundIds[0] ?? '')
  const target = Number(targetInput)
  const targetValid = targetInput.trim() !== '' && Number.isFinite(target) && target > 0 && target < 1

  function handleLaunch() {
    if (!variable || !targetValid) return
    const payload: ThresholdSearchRequest = {
      variable,
      mode: 'p_loss',
      target,
      direction: 'increasing',
      bounds: null,
      trials_per_evaluation: 20,
      max_iterations: 8,
      tolerance: 0.001,
      seed: null,
      loss_threshold: null,
    }
    void launch(() => robustnessApi.thresholdSearch(runId, payload), onLaunched)
  }

  return (
    <LauncherShell
      busy={busy}
      error={error}
      onRetry={handleLaunch}
      onLaunch={handleLaunch}
      launchDisabled={variable === '' || !targetValid}
      launchLabel="运行阈值搜索"
      note={
        boundIds.length > 0
          ? 'p_loss 模式、方向 increasing、每评估 20 次试验、最多 8 轮（后端默认值）。目标为概率，须在 0 与 1 之间。'
          : '未取到该 Run 的变量绑定，手动输入变量 id，后端会校验。p_loss 模式、方向 increasing、每评估 20 次试验、最多 8 轮（后端默认值）。目标为概率，须在 0 与 1 之间。'
      }
    >
      {variablesLoading ? (
        <p className="text-xs text-slate-500">正在加载该 Run 的变量绑定…</p>
      ) : boundIds.length > 0 ? (
        <span className="flex items-center gap-2">
          <label htmlFor="ts-variable" className="text-xs text-slate-400">
            变量
          </label>
          <select
            id="ts-variable"
            value={variable}
            onChange={(event) => setVariableInput(event.target.value)}
            className={SELECT_CLASS}
          >
            {boundIds.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        </span>
      ) : (
        <span className="flex items-center gap-2">
          <label htmlFor="ts-variable" className="text-xs text-slate-400">
            变量
          </label>
          <input
            id="ts-variable"
            value={variableInput}
            onChange={(event) => setVariableInput(event.target.value)}
            placeholder="变量 id，如 cash"
            className={loopInputClassName()}
          />
        </span>
      )}
      <span className="flex items-center gap-2">
        <label htmlFor="ts-target" className="text-xs text-slate-400">
          目标概率
        </label>
        <input
          id="ts-target"
          type="number"
          min={0}
          max={1}
          step={0.05}
          value={targetInput}
          onChange={(event) => setTargetInput(event.target.value)}
          className={loopInputClassName()}
        />
      </span>
    </LauncherShell>
  )
}
