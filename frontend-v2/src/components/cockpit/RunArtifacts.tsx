import type {
  CalibrationFitRead,
  DecisionGatesRead,
  DeterminismRead,
  DistributionSummary,
  FirewallRead,
  MonteCarloResult,
  RobustnessRead,
  RuleWeightChange,
  ThresholdChange,
  VariableDefinition,
  VariableRunRead,
} from '../../api/engineTypes'
import { formatHash, formatNumber, formatShare } from './format'

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">{children}</h4>
  )
}

function KeyValue({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="shrink-0 text-xs text-slate-500">{label}</span>
      <span className="text-right font-mono text-xs text-slate-300">{value}</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sprint 2 — variable bindings
// ---------------------------------------------------------------------------

export function distributionSummary(variable: VariableDefinition): string {
  const d = variable.distribution
  switch (d.type) {
    case 'fixed':
      return `fixed = ${formatNumber(d.value ?? 0)}`
    case 'normal':
      return `normal(μ=${formatNumber(d.mean ?? 0)}, σ=${formatNumber(d.std ?? 0)})`
    case 'triangular':
      return `triangular(${formatNumber(d.min ?? 0)}, ${formatNumber(d.mode ?? 0)}, ${formatNumber(d.max ?? 0)})`
    case 'beta_pert':
      return `beta_pert(${formatNumber(d.min ?? 0)}, ${formatNumber(d.mode ?? 0)}, ${formatNumber(d.max ?? 0)})`
    case 'bernoulli':
      return `bernoulli(p=${formatNumber(d.p ?? 0)})`
  }
}

export function VariableBindingsView({ data }: { data: VariableRunRead }) {
  const { template, bindings, validation } = data
  return (
    <div className="space-y-5">
      {template && (
        <div>
          <SectionTitle>模板快照</SectionTitle>
          <KeyValue label="模板" value={`${template.name} (${template.id})`} />
          <KeyValue label="领域" value={template.domain_id} />
          <KeyValue label="内置预设" value={template.is_builtin ? '是（只读）' : '否'} />
          {template.state_fields.length > 0 && (
            <div className="mt-2 grid grid-cols-2 gap-x-6 sm:grid-cols-3">
              {template.state_fields.map((field) => (
                <KeyValue key={field.name} label={field.name} value={formatNumber(field.default)} />
              ))}
            </div>
          )}
        </div>
      )}

      {bindings && bindings.variables.length > 0 && (
        <div>
          <SectionTitle>变量绑定{bindings.name ? ` · ${bindings.name}` : ''}</SectionTitle>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-3 font-medium">变量</th>
                <th className="py-2 pr-3 font-medium">单位</th>
                <th className="py-2 pr-3 font-medium">分布</th>
                <th className="py-2 pr-3 font-medium">出处</th>
                <th className="py-2 font-medium">Scope 标签</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {bindings.variables.map((variable) => (
                <tr key={variable.id}>
                  <td className="py-2 pr-3 font-mono text-xs text-slate-200">{variable.id}</td>
                  <td className="py-2 pr-3 text-slate-400">{variable.unit || '—'}</td>
                  <td className="py-2 pr-3 font-mono text-xs text-slate-300">
                    {distributionSummary(variable)}
                  </td>
                  <td className="py-2 pr-3 text-xs text-slate-400">{variable.evidence_ref || '—'}</td>
                  <td className="py-2 font-mono text-xs text-slate-400">{variable.scope_tags.join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {bindings && bindings.formulas.length > 0 && (
        <div>
          <SectionTitle>公式图（派生变量）</SectionTitle>
          <div className="space-y-1">
            {bindings.formulas.map((formula) => (
              <div key={formula.output} className="font-mono text-xs text-slate-300">
                {formula.output} = {JSON.stringify(formula.expression)}
                {formula.description && <span className="ml-2 font-sans text-slate-500">{formula.description}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {bindings && Object.keys(bindings.internal).length > 0 && (
        <div>
          <SectionTitle>内部情况表</SectionTitle>
          <div className="space-y-1">
            {Object.entries(bindings.internal).map(([key, value]) => (
              <div key={key} className="flex gap-3 text-sm">
                <span className="shrink-0 font-mono text-xs text-slate-500">{key}</span>
                <span className="text-xs leading-5 text-slate-300">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {validation && (
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
              validation.is_valid
                ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                : 'border-red-500/20 bg-red-500/10 text-red-400'
            }`}
          >
            {validation.is_valid ? '变量表有效' : '变量表无效'}
          </span>
          <span className="text-xs text-slate-500">{validation.variable_count} 个变量</span>
          {validation.issues.map((issue, index) => (
            <span key={index} className="text-xs text-red-300">
              {issue.kind} · {issue.variable} · {issue.message}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sprint 3 — ensemble + determinism
// ---------------------------------------------------------------------------

function ArmRow({ label, summary }: { label: string; summary: DistributionSummary }) {
  return (
    <tr>
      <td className="py-2 pr-3 text-slate-200">{label}</td>
      <td className="py-2 pr-3 font-mono text-xs">{summary.n}</td>
      <td className="py-2 pr-3 font-mono text-xs">{formatNumber(summary.mean)}</td>
      <td className="py-2 pr-3 font-mono text-xs">{formatNumber(summary.min)}</td>
      <td className="py-2 pr-3 font-mono text-xs">{formatNumber(summary.p10)}</td>
      <td className="py-2 pr-3 font-mono text-xs font-medium text-slate-100">{formatNumber(summary.p50)}</td>
      <td className="py-2 pr-3 font-mono text-xs">{formatNumber(summary.p90)}</td>
      <td className="py-2 pr-3 font-mono text-xs">{formatNumber(summary.max)}</td>
      <td className="py-2 pr-3 font-mono text-xs">{formatNumber(summary.stddev)}</td>
      <td className="py-2 font-mono text-xs">{formatShare(summary.p_loss)}</td>
    </tr>
  )
}

export function EnsembleView({ result }: { result: MonteCarloResult }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-4">
        <KeyValue label="指标" value={result.metric} />
        <KeyValue label="试验数" value={result.trials} />
        <KeyValue label="种子" value={result.seed} />
        <KeyValue label="亏损阈值" value={formatNumber(result.loss_threshold)} />
      </div>
      {Object.keys(result.strategy_levers).length > 0 && (
        <KeyValue
          label="策略杠杆"
          value={Object.entries(result.strategy_levers)
            .map(([key, value]) => `${key}=${formatNumber(value)}`)
            .join(', ')}
        />
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
              <th className="py-2 pr-3 font-medium">臂</th>
              <th className="py-2 pr-3 font-medium">n</th>
              <th className="py-2 pr-3 font-medium">均值</th>
              <th className="py-2 pr-3 font-medium">最小</th>
              <th className="py-2 pr-3 font-medium">P10</th>
              <th className="py-2 pr-3 font-medium">P50</th>
              <th className="py-2 pr-3 font-medium">P90</th>
              <th className="py-2 pr-3 font-medium">最大</th>
              <th className="py-2 pr-3 font-medium">标准差</th>
              <th className="py-2 font-medium">亏损概率</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60 text-slate-300">
            <ArmRow label="基线" summary={result.baseline} />
            <ArmRow label="策略" summary={result.strategy} />
          </tbody>
        </table>
      </div>
      <div>
        <SectionTitle>配对差值（策略 − 基线，同种子配对）</SectionTitle>
        <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-4">
          <KeyValue label="平均差值" value={formatNumber(result.paired.mean_delta)} />
          <KeyValue label="P10 / P50 / P90" value={`${formatNumber(result.paired.p10)} / ${formatNumber(result.paired.p50)} / ${formatNumber(result.paired.p90)}`} />
          <KeyValue label="策略更优概率" value={formatShare(result.paired.p_strategy_better)} />
          <KeyValue label="协议" value={result.protocol} />
        </div>
      </div>
      <p className="font-mono text-[11px] text-slate-600">ensemble {result.ensemble_id}</p>
    </div>
  )
}

export function DeterminismView({ data }: { data: DeterminismRead }) {
  const ticks = Object.entries(data.state_hashes).sort(([a], [b]) => Number(a) - Number(b))
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
        <KeyValue label="种子" value={data.seed} />
        <KeyValue label="协议" value={data.protocol} />
        <KeyValue label="输入哈希" value={formatHash(data.input_hash)} />
      </div>
      {ticks.length > 0 && (
        <div>
          <SectionTitle>逐 tick 状态哈希</SectionTitle>
          <div className="max-h-40 space-y-1 overflow-y-auto">
            {ticks.map(([tick, hash]) => (
              <div key={tick} className="flex gap-3 font-mono text-xs">
                <span className="w-10 shrink-0 text-slate-500">tick {tick}</span>
                <span className="break-all text-slate-300">{hash}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {Object.keys(data.sampled_values).length > 0 && (
        <div>
          <SectionTitle>采样值（命中状态字段的已应用）</SectionTitle>
          <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
            {Object.entries(data.sampled_values).map(([key, value]) => (
              <KeyValue
                key={key}
                label={key}
                value={`${formatNumber(value)}${data.sampled_applied.includes(key) ? ' · 已应用' : ''}`}
              />
            ))}
          </div>
        </div>
      )}
      {Object.keys(data.derived_values).length > 0 && (
        <div>
          <SectionTitle>派生值（公式图）</SectionTitle>
          <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
            {Object.entries(data.derived_values).map(([key, value]) => (
              <KeyValue
                key={key}
                label={key}
                value={`${formatNumber(value)}${data.derived_applied.includes(key) ? ' · 已应用' : ''}`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sprint 4 — robustness + decision gates
// ---------------------------------------------------------------------------

export function RobustnessView({ data }: { data: RobustnessRead }) {
  const { expected_shortfall: es, tornado, threshold_search: threshold, bootstrap } = data
  return (
    <div className="space-y-6">
      {es && (
        <div>
          <SectionTitle>
            期望损失（ES，α={formatNumber(es.alpha)}，{es.tail === 'lower' ? '下尾' : '上尾'}）
          </SectionTitle>
          <div className="grid grid-cols-3 gap-x-6">
            <KeyValue label="基线" value={`${formatNumber(es.baseline.value)}（尾部 ${es.baseline.tail_count}/${es.baseline.n}）`} />
            <KeyValue label="策略" value={`${formatNumber(es.strategy.value)}（尾部 ${es.strategy.tail_count}/${es.strategy.n}）`} />
            <KeyValue label="配对差值" value={`${formatNumber(es.paired.value)}（尾部 ${es.paired.tail_count}/${es.paired.n}）`} />
          </div>
        </div>
      )}

      {tornado && (
        <div>
          <SectionTitle>
            龙卷风敏感性（P{Math.round(tornado.low_quantile * 100)}→P{Math.round(tornado.high_quantile * 100)}，按摆动降序）
          </SectionTitle>
          {tornado.rows.length === 0 ? (
            <p className="text-sm text-slate-500">无龙卷风行。</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-3 font-medium">变量</th>
                  <th className="py-2 pr-3 font-medium">低值 → 高值</th>
                  <th className="py-2 pr-3 font-medium">结果低值</th>
                  <th className="py-2 pr-3 font-medium">结果高值</th>
                  <th className="py-2 font-medium">摆动</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {tornado.rows.map((row) => (
                  <tr key={row.variable}>
                    <td className="py-2 pr-3 font-mono text-xs text-slate-200">{row.variable}</td>
                    <td className="py-2 pr-3 font-mono text-xs">
                      {formatNumber(row.low_value)} → {formatNumber(row.high_value)}
                    </td>
                    <td className="py-2 pr-3 font-mono text-xs">{formatNumber(row.outcome_low)}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{formatNumber(row.outcome_high)}</td>
                    <td className="py-2 font-mono text-xs font-medium text-slate-100">{formatNumber(row.swing)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {threshold && (
        <div>
          <SectionTitle>阈值搜索 · {threshold.variable}（{threshold.mode}，目标 {formatNumber(threshold.target)}）</SectionTitle>
          {threshold.reachable && threshold.threshold !== null ? (
            <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
              <KeyValue label="阈值" value={formatNumber(threshold.threshold)} />
              <KeyValue
                label="达成统计量"
                value={threshold.achieved_statistic !== null ? formatNumber(threshold.achieved_statistic) : '—'}
              />
              <KeyValue label="迭代次数" value={threshold.iterations} />
            </div>
          ) : (
            <div role="note" className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2">
              <p className="text-sm text-amber-300">目标不可达：搜索区间内统计量未跨过目标。</p>
              <p className="mt-0.5 text-xs text-slate-400">
                区间 [{formatNumber(threshold.bounds[0])}, {formatNumber(threshold.bounds[1])}] · {threshold.iterations}{' '}
                次迭代 · 每次 {threshold.trials_per_evaluation} 个试验。未找到阈值是如实报告的结果，不是错误。
              </p>
            </div>
          )}
        </div>
      )}

      {bootstrap && (
        <div>
          <SectionTitle>Bootstrap 区间（百分位法）</SectionTitle>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-3 font-medium">臂</th>
                <th className="py-2 pr-3 font-medium">统计量</th>
                <th className="py-2 pr-3 font-medium">估计</th>
                <th className="py-2 pr-3 font-medium">区间下限</th>
                <th className="py-2 pr-3 font-medium">区间上限</th>
                <th className="py-2 font-medium">抽取 / 置信水平</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {(['baseline', 'strategy'] as const).flatMap((arm) =>
                bootstrap[arm].map((interval) => (
                  <tr key={`${arm}-${interval.statistic}`}>
                    <td className="py-2 pr-3">{arm === 'baseline' ? '基线' : '策略'}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{interval.statistic}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{formatNumber(interval.estimate)}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{formatNumber(interval.low)}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{formatNumber(interval.high)}</td>
                    <td className="py-2 font-mono text-xs">
                      {interval.draws} / {formatShare(interval.level)}
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      )}

      {!es && !tornado && !threshold && !bootstrap && (
        <p className="text-sm text-slate-500">该 Run 尚未存储稳健性分析。</p>
      )}
    </div>
  )
}

export function DecisionGatesView({ data }: { data: DecisionGatesRead }) {
  return (
    <div className="space-y-5">
      {data.registrations.length === 0 ? (
        <p className="text-sm text-slate-500">尚未注册决策门。</p>
      ) : (
        data.registrations.map((registration) => (
          <div key={registration.id} className="rounded-lg border border-slate-800/60 p-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-xs text-slate-400">{registration.id}</span>
              <span
                className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${
                  registration.status === 'active'
                    ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                    : 'border-slate-500/20 bg-slate-500/10 text-slate-400'
                }`}
              >
                {registration.status === 'active' ? '生效中' : '已取代'}
              </span>
              <span className="text-xs text-slate-500">
                注册时 ensemble {registration.ensemble_existed_at_registration ? '已存在' : '不存在'}
                {registration.ensemble_id ? ` · ${registration.ensemble_id}` : ''}
              </span>
            </div>
            <ul className="mt-2 space-y-1">
              {registration.gates.map((gate) => (
                <li key={gate.name} className="font-mono text-xs text-slate-300">
                  {gate.name}: {gate.arm}.{gate.metric} {gate.operator} {formatNumber(gate.threshold)}
                  {gate.metric === 'expected_shortfall' ? ` (α=${formatNumber(gate.alpha)})` : ''}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}

      {data.evaluations.length > 0 && (
        <div>
          <SectionTitle>评估记录</SectionTitle>
          <div className="space-y-3">
            {data.evaluations.map((evaluation) => (
              <div key={evaluation.id} className="rounded-lg border border-slate-800/60 p-3">
                <div className="flex flex-wrap items-center gap-3">
                  <span
                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${
                      evaluation.all_passed
                        ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                        : 'border-red-500/20 bg-red-500/10 text-red-400'
                    }`}
                  >
                    {evaluation.all_passed ? '全部通过' : '有门未通过'}
                  </span>
                  <span className="text-xs text-slate-500">
                    预注册：{evaluation.pre_registered ? '是' : '否'} · ensemble {evaluation.ensemble_id}
                  </span>
                </div>
                <ul className="mt-2 space-y-1">
                  {evaluation.outcomes.map((outcome) => (
                    <li key={outcome.name} className="font-mono text-xs text-slate-300">
                      <span className={outcome.passed ? 'text-emerald-400' : 'text-red-400'}>
                        {outcome.passed ? 'PASS' : 'FAIL'}
                      </span>{' '}
                      {outcome.name}: 观测 {formatNumber(outcome.observed)} {outcome.operator}{' '}
                      {formatNumber(outcome.threshold)}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sprint 5 — firewall + calibration
// ---------------------------------------------------------------------------

export function FirewallView({ data }: { data: FirewallRead }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
        <KeyValue label="防火墙" value={data.firewall_active ? '生效' : '未生效'} />
        <KeyValue label="决策时间" value={data.decision_time ?? '—'} />
        <KeyValue label="截断来源" value={data.cutoff_source ?? '—'} />
      </div>
      <div>
        <SectionTitle>被防火墙挡在外的 claim（{data.excluded_claim_ids.length}）</SectionTitle>
        {data.excluded_claim_ids.length === 0 ? (
          <p className="text-sm text-slate-500">没有 claim 被挡在外面。</p>
        ) : (
          <ul className="space-y-1">
            {data.excluded_claim_ids.map((id) => (
              <li key={id} className="font-mono text-xs text-amber-300/90">{id}</li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <SectionTitle>纳入的 claim（{data.included_claim_ids.length}）</SectionTitle>
        {data.included_claim_ids.length === 0 ? (
          <p className="text-sm text-slate-500">没有纳入的 claim。</p>
        ) : (
          <ul className="max-h-32 space-y-1 overflow-y-auto">
            {data.included_claim_ids.map((id) => (
              <li key={id} className="font-mono text-xs text-slate-400">{id}</li>
            ))}
          </ul>
        )}
      </div>
      {data.stored_evidence_ids.length > 0 && (
        <p className="font-mono text-[11px] text-slate-600">
          执行时记录的 evidence id（另一 id 空间）：{data.stored_evidence_ids.length} 条
        </p>
      )}
    </div>
  )
}

function isThresholdChange(value: unknown): value is ThresholdChange {
  return (
    typeof value === 'object' &&
    value !== null &&
    'fitted_alert_threshold' in value &&
    'prior_alert_threshold' in value
  )
}

function isRuleWeightChange(value: unknown): value is RuleWeightChange {
  return (
    typeof value === 'object' &&
    value !== null &&
    'fitted_weight' in value &&
    'prior_weight' in value
  )
}

export function CalibrationFitsView({ fits }: { fits: CalibrationFitRead[] }) {
  if (fits.length === 0) {
    return <p className="text-sm text-slate-500">尚无校准拟合记录。</p>
  }
  return (
    <div className="space-y-4">
      {fits.map((fit) => {
        const metricChanges = Object.values((fit.changes.metrics ?? {}) as Record<string, unknown>).filter(
          isThresholdChange,
        )
        const ruleChanges = Object.values((fit.changes.rules ?? {}) as Record<string, unknown>).filter(
          isRuleWeightChange,
        )
        return (
          <div key={fit.id} className="rounded-lg border border-slate-800/60 p-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-xs text-slate-400">{fit.id}</span>
              <span className="rounded-full border border-slate-700/60 bg-slate-800/40 px-2 py-0.5 text-[11px] text-slate-300">
                {fit.kind}
              </span>
              <span className="text-xs text-slate-500">
                {fit.domain_id}
                {fit.metric ? ` · 目标 ${fit.metric}` : ''} · {fit.n_observations} 个观测 · λ=
                {formatNumber(fit.ridge_strength)}
              </span>
            </div>
            {fit.calibrated_template_id && (
              <p className="mt-1 text-xs text-slate-400">
                拟合后存为新模板版本：<span className="font-mono text-slate-300">{fit.calibrated_template_id}</span>
                （源模板 {fit.source_template_id} 未被修改）
              </p>
            )}
            {metricChanges.map((change) => (
              <div key={change.metric} className="mt-2 font-mono text-xs text-slate-300">
                {change.metric}（{change.preferred_direction}）：alert {formatNumber(change.prior_alert_threshold)} →{' '}
                {formatNumber(change.fitted_alert_threshold)}；critical {formatNumber(change.prior_critical_threshold)} →{' '}
                {formatNumber(change.fitted_critical_threshold)}
                {change.unchanged_reason && (
                  <span className="ml-2 font-sans text-slate-500">未改动：{change.unchanged_reason}</span>
                )}
              </div>
            ))}
            {ruleChanges.map((change) => (
              <div key={change.rule_id} className="mt-2 font-mono text-xs text-slate-300">
                {change.rule_id}：权重 {formatNumber(change.prior_weight)} → {formatNumber(change.fitted_weight)}（匹配{' '}
                {formatNumber(change.total_matches)} 次）
              </div>
            ))}
            {typeof fit.changes.association_note === 'string' && (
              <p className="mt-2 text-xs leading-5 text-slate-500">{fit.changes.association_note}</p>
            )}
            <p className="mt-1 font-mono text-[11px] text-slate-600">
              inputs_hash {formatHash(fit.inputs_hash)}
              {fit.loo_rmse !== null ? ` · LOO RMSE ${formatNumber(fit.loo_rmse)}` : ''}
              {` · ${fit.created_at}`}
            </p>
          </div>
        )
      })}
    </div>
  )
}
