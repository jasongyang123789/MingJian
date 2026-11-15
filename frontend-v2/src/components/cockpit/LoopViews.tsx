// Living-strategy loop views (Sprint 9): trigger registrations,
// observations, iteration cards with explicit actions, and
// distribution-vs-distribution comparisons. Every action is an
// explicit button press — nothing here auto-evaluates,
// auto-re-simulates, or auto-decides — and every refusal surfaces
// the backend's structured error code.

import { useState } from 'react'

import { distributionsApi, loopsApi, nullOn404, parseApiError } from '../../api/engine'
import type {
  EnsembleComparison,
  GateMetric,
  LoopEvaluationRead,
  LoopIterationRead,
  LoopObservationRead,
  LoopTriggerDefinition,
  ResimulationRecord,
  ReviewDecision,
  TriggerEvaluationOutcome,
  TriggerKind,
  TriggerOperator,
  TriggerRegistration,
} from '../../api/engineTypes'
import { useApi } from '../../hooks/useApi'
import { EmptyState } from '../ui/EmptyState'
import { ErrorBanner } from '../ui/ErrorBanner'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { EnsembleHistograms } from './DistributionCharts'
import { formatHash, formatNumber, formatShare } from './format'
import { DECISION_LABELS, ITERATION_STATE_LABELS, loopInputClassName, triggerSummary } from './loopDisplay'

function actionButtonClassName(disabled: boolean) {
  return `rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
    disabled
      ? 'cursor-not-allowed border-slate-700/50 text-slate-600'
      : 'border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20'
  }`
}

const OUTCOME_BADGE: Record<string, string> = {
  fired: 'bg-red-500/10 text-red-400 border-red-500/20',
  quiet: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
  no_data: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
}

const OUTCOME_LABELS: Record<string, string> = {
  fired: '已触发',
  quiet: '未触发',
  no_data: '无数据',
}

export function TriggerRegistrations({ registrations }: { registrations: TriggerRegistration[] }) {
  if (registrations.length === 0) {
    return (
      <EmptyState
        title="尚未注册触发器"
        description="触发器必须预先注册：先注册触发器，再评估评审窗口。注册时会记录当时已有的观测数量，作为预注册的可检查证据。"
      />
    )
  }
  return (
    <div className="space-y-3">
      {registrations.map((registration) => (
        <div key={registration.id} className="rounded-lg border border-slate-700/50 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                registration.status === 'active'
                  ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                  : 'border-slate-500/20 bg-slate-500/10 text-slate-400'
              }`}
            >
              {registration.status === 'active' ? '活动' : '已取代'}
            </span>
            <span className="text-xs text-slate-500">
              注册于 {registration.registered_at} · 注册时已有观测 {registration.observation_count_at_registration} 条
            </span>
            {registration.supersedes && (
              <span className="text-xs text-slate-500">取代 {registration.supersedes.slice(0, 8)}</span>
            )}
          </div>
          <ul className="mt-2 space-y-1">
            {registration.triggers.map((trigger) => (
              <li key={trigger.name} className="text-sm text-slate-200">
                <span className="font-medium">{trigger.name}</span>
                <span className="text-slate-400"> — {triggerSummary(trigger)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

export function ObservationList({ observations }: { observations: LoopObservationRead[] }) {
  if (observations.length === 0) {
    return (
      <EmptyState
        title="暂无观测记录"
        description="记录实际观测值（字段、数值、观测时间），评审窗口按观测时间、而非记录时间划分。"
      />
    )
  }
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-700/50 text-xs text-slate-500">
          <th className="py-2 pr-3 font-medium">观测时间</th>
          <th className="py-2 pr-3 font-medium">字段</th>
          <th className="py-2 pr-3 font-medium">观测值</th>
          <th className="py-2 font-medium">来源备注</th>
        </tr>
      </thead>
      <tbody>
        {observations.map((observation) => (
          <tr key={observation.id} className="border-b border-slate-800/60">
            <td className="py-2 pr-3 font-mono text-xs text-slate-400">{observation.observed_at}</td>
            <td className="py-2 pr-3 text-slate-200">{observation.field}</td>
            <td className="py-2 pr-3 font-mono text-slate-200">{formatNumber(observation.value)}</td>
            <td className="py-2 text-slate-400">{observation.source_note ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function TriggerOutcomes({ outcomes }: { outcomes: TriggerEvaluationOutcome[] }) {
  if (outcomes.length === 0) {
    return <p className="text-sm text-slate-500">尚未评估。</p>
  }
  return (
    <div className="space-y-2">
      {outcomes.map((outcome) => (
        <div key={outcome.name} className="rounded-lg border border-slate-700/50 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${OUTCOME_BADGE[outcome.status]}`}
            >
              {OUTCOME_LABELS[outcome.status]}
            </span>
            <span className="text-sm font-medium text-slate-100">{outcome.name}</span>
            <span className="text-xs text-slate-500">
              {outcome.field} · {outcome.observation_ids.length} 条观测
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-300">{outcome.note}</p>
          {outcome.observed_value !== null && (
            <p className="mt-1 font-mono text-xs text-slate-500">
              观测值 {formatNumber(outcome.observed_value)}
              {outcome.threshold !== null && ` · 阈值 ${formatNumber(outcome.threshold)}`}
              {outcome.tolerance !== null && ` · 容差 ${formatNumber(outcome.tolerance)}`}
              {outcome.reference_value !== null &&
                ` · 参考值 ${formatNumber(outcome.reference_value)}`}
              {outcome.consecutive_breaches !== null &&
                ` · 连续偏离 ${outcome.consecutive_breaches} 次`}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

const EVALUATION_BADGE: Record<string, string> = {
  ...OUTCOME_BADGE,
  error: 'bg-red-500/20 text-red-300 border-red-500/30',
}

const EVALUATION_LABELS: Record<string, string> = {
  ...OUTCOME_LABELS,
  error: '评估失败',
}

export function EvaluationHistory({ evaluations }: { evaluations: LoopEvaluationRead[] }) {
  if (evaluations.length === 0) {
    return (
      <EmptyState
        title="暂无监测评估"
        description="监测 worker 定期评估触发器并记录结果；也可以手动运行一次监测。评估只记录触发状态，不创建 Run、不推进评审。"
      />
    )
  }
  return (
    <div className="space-y-3">
      {evaluations.map((evaluation) => (
        <div key={evaluation.id} className="rounded-lg border border-slate-700/50 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${EVALUATION_BADGE[evaluation.summary]}`}
            >
              {EVALUATION_LABELS[evaluation.summary]}
            </span>
            <span className="font-mono text-xs text-slate-400">{evaluation.evaluated_at}</span>
            <span className="text-xs text-slate-500">
              {evaluation.observation_ids.length} 条观测 · 指纹 {formatHash(evaluation.observation_fingerprint)}
            </span>
          </div>
          {evaluation.summary === 'error' && (
            <p className="mt-1 text-sm text-red-300">
              {evaluation.error_code}
              {evaluation.error_message ? `：${evaluation.error_message}` : ''}
            </p>
          )}
          {evaluation.outcomes.length > 0 && (
            <div className="mt-2">
              <TriggerOutcomes outcomes={evaluation.outcomes} />
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

export function ResimulationView({ record }: { record: ResimulationRecord }) {
  const changes = Object.entries(record.changes)
  return (
    <div className="space-y-2 text-sm">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <p className="text-slate-300">
          新 Run <span className="font-mono text-xs text-slate-400">{record.run_id}</span>
        </p>
        <p className="text-slate-300">
          seed {record.seed} · {record.tick_count} ticks
        </p>
        <p className="text-slate-300">
          证据截断 <span className="font-mono text-xs">{record.previous_cutoff ?? '（无）'}</span>
          {' → '}
          <span className="font-mono text-xs">{record.new_cutoff}</span>
        </p>
        <p className="text-slate-300">
          输入哈希 <span className="font-mono text-xs">{formatHash(record.previous_input_hash)}</span>
          {' → '}
          <span className="font-mono text-xs">{formatHash(record.new_input_hash)}</span>
          <span className="text-slate-500">（截断前进，哈希不同是设计要求）</span>
        </p>
        <p className="text-slate-300">
          可见 claims {record.claims_visible} 条 · 被防火墙排除 {record.claims_excluded} 条
        </p>
        {record.template_id && (
          <p className="text-slate-300">
            模板 <span className="font-mono text-xs">{record.template_id}</span>
            {record.template_snapshot_hash !== record.resolved_template_snapshot_hash && (
              <span className="text-amber-400">（模板快照已漂移）</span>
            )}
          </p>
        )}
      </div>
      {changes.length > 0 && (
        <div>
          <p className="text-xs font-medium text-slate-400">显式变更</p>
          <ul className="mt-1 space-y-0.5">
            {changes.map(([key, value]) => (
              <li key={key} className="font-mono text-xs text-slate-300">
                {key}: {JSON.stringify(value)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {changes.length === 0 && (
        <p className="text-xs text-slate-500">无显式变更：分解、模板与绑定、seed、tick 数全部继承基线 Run。</p>
      )}
    </div>
  )
}

function ArmDeltaTable({
  label,
  arm,
}: {
  label: string
  arm: EnsembleComparison['baseline_arm']
}) {
  const rows: { label: string; oldValue: number; newValue: number; delta: number; share?: boolean }[] = [
    { label: 'P10', oldValue: arm.old.p10, newValue: arm.new.p10, delta: arm.delta_p10 },
    { label: 'P50', oldValue: arm.old.p50, newValue: arm.new.p50, delta: arm.delta_p50 },
    { label: 'P90', oldValue: arm.old.p90, newValue: arm.new.p90, delta: arm.delta_p90 },
    { label: '均值', oldValue: arm.old.mean, newValue: arm.new.mean, delta: arm.delta_mean },
    { label: '亏损概率', oldValue: arm.old.p_loss, newValue: arm.new.p_loss, delta: arm.delta_p_loss, share: true },
  ]
  return (
    <div>
      <h5 className="mb-1 text-sm font-medium text-slate-200">{label}</h5>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs text-slate-500">
            <th className="py-1.5 pr-3 font-medium">统计量</th>
            <th className="py-1.5 pr-3 font-medium">旧分布</th>
            <th className="py-1.5 pr-3 font-medium">新分布</th>
            <th className="py-1.5 font-medium">变化</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label} className="border-b border-slate-800/60">
              <td className="py-1.5 pr-3 text-slate-400">{row.label}</td>
              <td className="py-1.5 pr-3 font-mono text-slate-200">
                {row.share ? formatShare(row.oldValue) : formatNumber(row.oldValue)}
              </td>
              <td className="py-1.5 pr-3 font-mono text-slate-200">
                {row.share ? formatShare(row.newValue) : formatNumber(row.newValue)}
              </td>
              <td className="py-1.5 font-mono text-slate-200">
                {row.share
                  ? `${row.delta >= 0 ? '+' : ''}${(row.delta * 100).toFixed(1)}pp`
                  : `${row.delta >= 0 ? '+' : ''}${formatNumber(row.delta)}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ComparisonView({ comparison }: { comparison: EnsembleComparison }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>
          指标 {comparison.metric} · 亏损阈值 {formatNumber(comparison.loss_threshold)}
        </span>
        <span
          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${
            comparison.seeds_paired
              ? 'border-blue-500/20 bg-blue-500/10 text-blue-300'
              : 'border-slate-500/20 bg-slate-500/10 text-slate-400'
          }`}
        >
          {comparison.seeds_paired ? '种子配对' : '种子未配对'}
        </span>
        <span>比较于 {comparison.compared_at}</span>
      </div>
      {comparison.evidence_caveat && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-300">
          {comparison.evidence_caveat}
        </div>
      )}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ArmDeltaTable label="基线臂" arm={comparison.baseline_arm} />
        <ArmDeltaTable label="策略臂" arm={comparison.strategy_arm} />
      </div>
      <div className="text-sm text-slate-300">
        <p>
          配对均值差 {formatNumber(comparison.paired_mean_delta_old)} →{' '}
          {formatNumber(comparison.paired_mean_delta_new)}（变化{' '}
          {comparison.paired_mean_delta_change >= 0 ? '+' : ''}
          {formatNumber(comparison.paired_mean_delta_change)}）
        </p>
        <p>
          策略更优概率 {formatShare(comparison.paired_p_strategy_better_old)} →{' '}
          {formatShare(comparison.paired_p_strategy_better_new)}（变化{' '}
          {comparison.paired_p_strategy_better_change >= 0 ? '+' : ''}
          {(comparison.paired_p_strategy_better_change * 100).toFixed(1)}pp）
        </p>
      </div>
      {comparison.gate_reevaluation && (
        <div>
          <h5 className="mb-1 text-sm font-medium text-slate-200">
            基线决策门在新 ensemble 上的重评估
            {comparison.gate_reevaluation.pre_registered ? '（预注册）' : '（非预注册）'} ·{' '}
            {comparison.gate_reevaluation.all_passed ? '全部通过' : '有门未通过'}
          </h5>
          <ul className="space-y-1">
            {comparison.gate_reevaluation.outcomes.map((outcome) => (
              <li key={outcome.name} className="text-sm text-slate-300">
                <span className={outcome.passed ? 'text-emerald-400' : 'text-red-400'}>
                  {outcome.passed ? '通过' : '未通过'}
                </span>{' '}
                {outcome.name}：{outcome.metric} {outcome.operator} {formatNumber(outcome.threshold)}
                ，观测值 {formatNumber(outcome.observed)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {comparison.threshold_drift.length > 0 && (
        <div>
          <h5 className="mb-1 text-sm font-medium text-slate-200">阈值漂移</h5>
          <ul className="space-y-1">
            {comparison.threshold_drift.map((row) => (
              <li key={`${row.variable}:${row.mode}`} className="text-sm text-slate-300">
                {row.variable}（{row.mode}）：旧阈值{' '}
                {row.old_reachable && row.old_threshold !== null ? formatNumber(row.old_threshold) : '不可达'}
                {' → '}新阈值{' '}
                {row.new_reachable && row.new_threshold !== null ? formatNumber(row.new_threshold) : '不可达'}
              </li>
            ))}
          </ul>
        </div>
      )}
      <ComparisonHistograms comparison={comparison} />
    </div>
  )
}

/**
 * Old-vs-new ensemble histograms, reusing the Sprint 8 chart
 * components. Each histogram is shown only when the run's current
 * stored ensemble is the one the comparison references — a newer
 * ensemble run later must not silently stand in for the compared
 * one. Missing trial values render an honest empty state.
 */
export function ComparisonHistograms({ comparison }: { comparison: EnsembleComparison }) {
  const { data, loading, error, reload } = useApi(async () => {
    const [oldEnsemble, newEnsemble] = await Promise.all([
      nullOn404(distributionsApi.getMonteCarlo(comparison.baseline_run_id)),
      nullOn404(distributionsApi.getMonteCarlo(comparison.new_run_id)),
    ])
    const [oldValues, newValues] = await Promise.all([
      oldEnsemble && oldEnsemble.ensemble_id === comparison.baseline_ensemble_id
        ? nullOn404(distributionsApi.getTrialValues(comparison.baseline_run_id))
        : Promise.resolve(null),
      newEnsemble && newEnsemble.ensemble_id === comparison.new_ensemble_id
        ? nullOn404(distributionsApi.getTrialValues(comparison.new_run_id))
        : Promise.resolve(null),
    ])
    return { oldEnsemble, newEnsemble, oldValues, newValues }
  }, comparison.new_ensemble_id)

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  if (!data) return null
  const { oldEnsemble, newEnsemble, oldValues, newValues } = data
  const oldMatches =
    oldEnsemble !== null && oldEnsemble.ensemble_id === comparison.baseline_ensemble_id
  const newMatches =
    newEnsemble !== null && newEnsemble.ensemble_id === comparison.new_ensemble_id
  return (
    <div className="space-y-6">
      <div>
        <h5 className="mb-2 text-sm font-medium text-slate-200">旧 Ensemble 分布</h5>
        {!oldMatches ? (
          <EmptyState
            title="旧 ensemble 已不是该 Run 当前存储的 ensemble"
            description="该 Run 之后又运行了新的 ensemble；比较对应的是旧 ensemble，此处不以新分布代替。"
          />
        ) : oldValues === null ? (
          <EmptyState
            title="旧 ensemble 的 trial 值不可用"
            description="trial 行缺失或不完整，无法画出分布直方图。此处不会用摘要统计量伪造分布。"
          />
        ) : (
          <EnsembleHistograms result={oldEnsemble} trialValues={oldValues} />
        )}
      </div>
      <div>
        <h5 className="mb-2 text-sm font-medium text-slate-200">新 Ensemble 分布</h5>
        {!newMatches ? (
          <EmptyState
            title="新 ensemble 已不是该 Run 当前存储的 ensemble"
            description="该 Run 之后又运行了新的 ensemble；比较对应的是旧 ensemble，此处不以新分布代替。"
          />
        ) : newValues === null ? (
          <EmptyState
            title="新 ensemble 的 trial 值不可用"
            description="trial 行缺失或不完整，无法画出分布直方图。此处不会用摘要统计量伪造分布。"
          />
        ) : (
          <EnsembleHistograms result={newEnsemble} trialValues={newValues} />
        )}
      </div>
    </div>
  )
}

const OBSERVABLE_GATE_METRICS: GateMetric[] = [
  'mean',
  'p10',
  'p50',
  'p90',
  'min',
  'max',
  'stddev',
  'p_loss',
  'expected_shortfall',
]

/** Parse a form field as a finite number; blank or non-numeric is null
 * (plain Number('') is 0, which would silently accept an empty field). */
function parseFinite(raw: string): number | null {
  if (raw.trim() === '') return null
  const value = Number(raw)
  return Number.isFinite(value) ? value : null
}

/**
 * Builds a trigger set one trigger at a time, then submits the set.
 * The parent owns the API call (loop creation or trigger
 * registration). Paired gate metrics are not offered: observations
 * have no arms, and the backend refuses them.
 */
export function TriggerBuilder({
  submitLabel,
  supersedeOption,
  onSubmit,
}: {
  submitLabel: string
  supersedeOption?: { activeRegistrationId: string }
  onSubmit: (triggers: LoopTriggerDefinition[], supersedes: string | null) => void
}) {
  const [triggers, setTriggers] = useState<LoopTriggerDefinition[]>([])
  const [kind, setKind] = useState<TriggerKind>('threshold')
  const [name, setName] = useState('')
  const [field, setField] = useState('')
  const [operator, setOperator] = useState<TriggerOperator>('<')
  const [threshold, setThreshold] = useState('')
  const [metric, setMetric] = useState<GateMetric>('mean')
  const [lossThreshold, setLossThreshold] = useState('')
  const [tolerance, setTolerance] = useState('')
  const [consecutive, setConsecutive] = useState('2')
  const [referenceValue, setReferenceValue] = useState('')
  const [supersede, setSupersede] = useState(true)
  const [formError, setFormError] = useState<string | null>(null)

  function addTrigger() {
    setFormError(null)
    const trimmedName = name.trim()
    const trimmedField = field.trim()
    if (!trimmedName || !trimmedField) {
      setFormError('触发器名称与字段不能为空。')
      return
    }
    if (triggers.some((item) => item.name === trimmedName)) {
      setFormError(`触发器名称 ${trimmedName} 已存在。`)
      return
    }
    if (kind === 'threshold') {
      const value = parseFinite(threshold)
      if (value === null) {
        setFormError('阈值必须是有限数值。')
        return
      }
      setTriggers([...triggers, { kind, name: trimmedName, field: trimmedField, operator, threshold: value }])
    } else if (kind === 'gate') {
      const value = parseFinite(threshold)
      if (value === null) {
        setFormError('阈值必须是有限数值。')
        return
      }
      let loss: number | null = null
      if (metric === 'p_loss') {
        loss = parseFinite(lossThreshold)
        if (loss === null) {
          setFormError('p_loss 门需要亏损阈值。')
          return
        }
      }
      setTriggers([
        ...triggers,
        {
          kind,
          name: trimmedName,
          field: trimmedField,
          gate: { name: trimmedName, metric, operator, threshold: value, arm: 'baseline', alpha: 0.05 },
          loss_threshold: loss,
        },
      ])
    } else {
      const tol = parseFinite(tolerance)
      const count = parseFinite(consecutive)
      if (tol === null || tol <= 0) {
        setFormError('容差必须是大于 0 的有限数值。')
        return
      }
      if (count === null || !Number.isInteger(count) || count < 1) {
        setFormError('连续次数必须是大于等于 1 的整数。')
        return
      }
      let reference: number | null = null
      if (referenceValue.trim() !== '') {
        reference = parseFinite(referenceValue)
        if (reference === null) {
          setFormError('参考值必须是有限数值，留空则使用基线终值。')
          return
        }
      }
      setTriggers([
        ...triggers,
        { kind, name: trimmedName, field: trimmedField, tolerance: tol, consecutive: count, reference_value: reference },
      ])
    }
    setName('')
    setField('')
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block text-xs text-slate-500">
          触发器类型
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value as TriggerKind)}
            className={`${loopInputClassName()} mt-1`}
          >
            <option value="threshold">阈值（最新观测）</option>
            <option value="gate">决策门统计量（窗口观测）</option>
            <option value="deviation">重复偏离</option>
          </select>
        </label>
        <label className="block text-xs text-slate-500">
          触发器名称
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如 cash-floor"
            className={`${loopInputClassName()} mt-1`}
          />
        </label>
        <label className="block text-xs text-slate-500">
          状态字段
          <input
            value={field}
            onChange={(event) => setField(event.target.value)}
            placeholder="例如 cash"
            className={`${loopInputClassName()} mt-1`}
          />
        </label>
        {kind !== 'deviation' && (
          <label className="block text-xs text-slate-500">
            比较符
            <select
              value={operator}
              onChange={(event) => setOperator(event.target.value as TriggerOperator)}
              className={`${loopInputClassName()} mt-1`}
            >
              <option value="&lt;">&lt;</option>
              <option value="&lt;=">&lt;=</option>
              <option value="&gt;">&gt;</option>
              <option value="&gt;=">&gt;=</option>
            </select>
          </label>
        )}
        {kind === 'gate' && (
          <label className="block text-xs text-slate-500">
            统计量
            <select
              value={metric}
              onChange={(event) => setMetric(event.target.value as GateMetric)}
              className={`${loopInputClassName()} mt-1`}
            >
              {OBSERVABLE_GATE_METRICS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind !== 'deviation' && (
          <label className="block text-xs text-slate-500">
            阈值
            <input
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              inputMode="decimal"
              placeholder="数值"
              className={`${loopInputClassName()} mt-1`}
            />
          </label>
        )}
        {kind === 'gate' && metric === 'p_loss' && (
          <label className="block text-xs text-slate-500">
            亏损阈值
            <input
              value={lossThreshold}
              onChange={(event) => setLossThreshold(event.target.value)}
              inputMode="decimal"
              placeholder="数值"
              className={`${loopInputClassName()} mt-1`}
            />
          </label>
        )}
        {kind === 'deviation' && (
          <>
            <label className="block text-xs text-slate-500">
              容差（大于 0）
              <input
                value={tolerance}
                onChange={(event) => setTolerance(event.target.value)}
                inputMode="decimal"
                placeholder="数值"
                className={`${loopInputClassName()} mt-1`}
              />
            </label>
            <label className="block text-xs text-slate-500">
              连续次数
              <input
                value={consecutive}
                onChange={(event) => setConsecutive(event.target.value)}
                inputMode="numeric"
                className={`${loopInputClassName()} mt-1`}
              />
            </label>
            <label className="block text-xs text-slate-500">
              参考值（留空用基线终值）
              <input
                value={referenceValue}
                onChange={(event) => setReferenceValue(event.target.value)}
                inputMode="decimal"
                placeholder="数值或留空"
                className={`${loopInputClassName()} mt-1`}
              />
            </label>
          </>
        )}
      </div>
      {formError && <ErrorBanner message={formError} />}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={addTrigger} className={actionButtonClassName(false)}>
          添加触发器
        </button>
      </div>
      {triggers.length > 0 && (
        <ul className="space-y-1">
          {triggers.map((trigger) => (
            <li key={trigger.name} className="flex items-center gap-2 text-sm text-slate-200">
              <span className="font-medium">{trigger.name}</span>
              <span className="text-slate-400">— {triggerSummary(trigger)}</span>
              <button
                type="button"
                onClick={() => setTriggers(triggers.filter((item) => item.name !== trigger.name))}
                className="text-xs text-red-400 hover:text-red-300"
              >
                移除
              </button>
            </li>
          ))}
        </ul>
      )}
      {supersedeOption && (
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={supersede} onChange={(event) => setSupersede(event.target.checked)} />
          取代当前活动注册（旧注册保留为“已取代”，不删除）
        </label>
      )}
      <button
        type="button"
        disabled={triggers.length === 0}
        onClick={() =>
          onSubmit(triggers, supersedeOption && supersede ? supersedeOption.activeRegistrationId : null)
        }
        className={actionButtonClassName(triggers.length === 0)}
      >
        {submitLabel}
      </button>
    </div>
  )
}

export function ObservationForm({
  loopId,
  onRecorded,
}: {
  loopId: string
  onRecorded: () => void
}) {
  const [field, setField] = useState('')
  const [value, setValue] = useState('')
  const [observedAt, setObservedAt] = useState('')
  const [sourceNote, setSourceNote] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  async function submit() {
    setFormError(null)
    setActionError(null)
    const numeric = parseFinite(value)
    if (!field.trim() || numeric === null || !observedAt) {
      setFormError('字段、数值与观测时间都必须填写，数值为有限数值。')
      return
    }
    setSubmitting(true)
    try {
      await loopsApi.recordObservation(loopId, {
        field: field.trim(),
        value: numeric,
        observed_at: new Date(observedAt).toISOString(),
        source_claim_id: null,
        source_note: sourceNote.trim() || null,
      })
      setField('')
      setValue('')
      setObservedAt('')
      setSourceNote('')
      onRecorded()
    } catch (caught: unknown) {
      const info = parseApiError(caught)
      setActionError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block text-xs text-slate-500">
          状态字段
          <input
            value={field}
            onChange={(event) => setField(event.target.value)}
            placeholder="例如 cash"
            className={`${loopInputClassName()} mt-1`}
          />
        </label>
        <label className="block text-xs text-slate-500">
          观测值
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            inputMode="decimal"
            placeholder="数值"
            className={`${loopInputClassName()} mt-1`}
          />
        </label>
        <label className="block text-xs text-slate-500">
          观测时间
          <input
            type="datetime-local"
            value={observedAt}
            onChange={(event) => setObservedAt(event.target.value)}
            className={`${loopInputClassName()} mt-1`}
          />
        </label>
        <label className="block text-xs text-slate-500">
          来源备注（可选）
          <input
            value={sourceNote}
            onChange={(event) => setSourceNote(event.target.value)}
            placeholder="例如 月度结算"
            className={`${loopInputClassName()} mt-1`}
          />
        </label>
      </div>
      {formError && <ErrorBanner message={formError} />}
      {actionError && <ErrorBanner message={actionError} />}
      <button type="button" disabled={submitting} onClick={submit} className={actionButtonClassName(submitting)}>
        {submitting ? '记录中…' : '记录观测'}
      </button>
    </div>
  )
}

export function IterationCard({
  iteration,
  onChanged,
}: {
  iteration: LoopIterationRead
  onChanged: () => void
}) {
  const [seed, setSeed] = useState('')
  const [tickCount, setTickCount] = useState('')
  const [note, setNote] = useState('')
  const [decision, setDecision] = useState<ReviewDecision>('continue')
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  async function run(action: 'evaluate' | 'resimulate' | 'compare' | 'decide') {
    setActionError(null)
    setBusy(true)
    try {
      if (action === 'evaluate') {
        await loopsApi.evaluateIteration(iteration.loop_id, iteration.id)
      } else if (action === 'compare') {
        await loopsApi.compareIteration(iteration.loop_id, iteration.id)
      } else if (action === 'decide') {
        await loopsApi.decideIteration(iteration.loop_id, iteration.id, {
          decision,
          rationale: rationale.trim(),
        })
      } else {
        const payload: { seed?: number; tick_count?: number; note?: string } = {}
        const parsedSeed = parseFinite(seed)
        const parsedTicks = parseFinite(tickCount)
        if (seed.trim() !== '' && parsedSeed !== null) payload.seed = parsedSeed
        if (tickCount.trim() !== '' && parsedTicks !== null) payload.tick_count = parsedTicks
        if (note.trim() !== '') payload.note = note.trim()
        await loopsApi.resimulateIteration(iteration.loop_id, iteration.id, payload)
      }
      onChanged()
    } catch (caught: unknown) {
      const info = parseApiError(caught)
      setActionError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-slate-700/50 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-semibold text-slate-100">评审 #{iteration.index}</h4>
        <span className="inline-flex items-center rounded-full border border-slate-500/20 bg-slate-500/10 px-2 py-0.5 text-[11px] font-medium text-slate-300">
          {ITERATION_STATE_LABELS[iteration.state]}
        </span>
        <span className="font-mono text-xs text-slate-500">
          评审时间 {iteration.decision_time}
          {iteration.previous_cutoff && ` · 上一截断 ${iteration.previous_cutoff}`}
        </span>
      </div>

      {iteration.window_from !== null && (
        <p className="mt-2 text-xs text-slate-500">
          评估窗口 ({iteration.window_from}, {iteration.window_to}] · {iteration.observation_ids.length} 条观测
        </p>
      )}

      <div className="mt-3 space-y-4">
        <div>
          <h5 className="mb-1.5 text-sm font-medium text-slate-200">触发器评估</h5>
          <TriggerOutcomes outcomes={iteration.trigger_evaluations} />
        </div>
        {iteration.resimulation && (
          <div>
            <h5 className="mb-1.5 text-sm font-medium text-slate-200">重新模拟</h5>
            <ResimulationView record={iteration.resimulation} />
          </div>
        )}
        {iteration.comparison && (
          <div>
            <h5 className="mb-1.5 text-sm font-medium text-slate-200">分布比较</h5>
            <ComparisonView comparison={iteration.comparison} />
          </div>
        )}
        {iteration.decision && (
          <div>
            <h5 className="mb-1.5 text-sm font-medium text-slate-200">评审决策</h5>
            <p className="text-sm text-slate-200">
              <span className="font-medium">{DECISION_LABELS[iteration.decision.decision]}</span>
              {' — '}
              {iteration.decision.rationale}
            </p>
            <p className="mt-0.5 text-xs text-slate-500">决策于 {iteration.decision.decided_at}</p>
          </div>
        )}
      </div>

      {iteration.state !== 'decided' && (
        <div className="mt-4 space-y-3 border-t border-slate-800/60 pt-3">
          {iteration.state === 'open' && (
            <button
              type="button"
              disabled={busy}
              onClick={() => run('evaluate')}
              className={actionButtonClassName(busy)}
            >
              {busy ? '评估中…' : '评估触发器'}
            </button>
          )}
          {iteration.state === 'evaluated' && (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                <label className="block text-xs text-slate-500">
                  Seed（留空继承基线）
                  <input
                    value={seed}
                    onChange={(event) => setSeed(event.target.value)}
                    inputMode="numeric"
                    className={`${loopInputClassName()} mt-1`}
                  />
                </label>
                <label className="block text-xs text-slate-500">
                  Tick 数（留空继承基线）
                  <input
                    value={tickCount}
                    onChange={(event) => setTickCount(event.target.value)}
                    inputMode="numeric"
                    className={`${loopInputClassName()} mt-1`}
                  />
                </label>
                <label className="block text-xs text-slate-500">
                  备注（可选）
                  <input
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    className={`${loopInputClassName()} mt-1`}
                  />
                </label>
              </div>
              <p className="text-xs text-slate-500">
                重新模拟走与手工创建相同的路径：MECE 门、变量门与防火墙全部生效；被拒时不写任何行。
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => run('resimulate')}
                className={actionButtonClassName(busy)}
              >
                {busy ? '模拟中…' : '重新模拟'}
              </button>
            </>
          )}
          {iteration.state === 'resimulated' && (
            <>
              <p className="text-xs text-slate-500">
                比较需要基线 Run 与新 Run 各自已存储的 ensemble（POST /runs/&#123;id&#125;/monte-carlo）；缺失时后端会如实拒绝并点名缺失的一方。
              </p>
              <button
                type="button"
                disabled={busy}
                onClick={() => run('compare')}
                className={actionButtonClassName(busy)}
              >
                {busy ? '比较中…' : '比较 Ensemble'}
              </button>
            </>
          )}
          {(iteration.state === 'evaluated' || iteration.state === 'compared') && (
            <div className="space-y-2">
              <label className="block text-xs text-slate-500">
                评审决策
                <select
                  value={decision}
                  onChange={(event) => setDecision(event.target.value as ReviewDecision)}
                  className={`${loopInputClassName()} mt-1`}
                >
                  {(Object.keys(DECISION_LABELS) as ReviewDecision[]).map((key) => (
                    <option key={key} value={key}>
                      {DECISION_LABELS[key]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-xs text-slate-500">
                决策理由（必填，记入审计轨迹）
                <textarea
                  value={rationale}
                  onChange={(event) => setRationale(event.target.value)}
                  rows={2}
                  className={`${loopInputClassName()} mt-1`}
                />
              </label>
              <button
                type="button"
                disabled={busy || rationale.trim() === ''}
                onClick={() => run('decide')}
                className={actionButtonClassName(busy || rationale.trim() === '')}
              >
                {busy ? '记录中…' : '记录决策'}
              </button>
            </div>
          )}
          {actionError && <ErrorBanner message={actionError} />}
        </div>
      )}
    </div>
  )
}
