import type {
  DecisionNarrativeRead,
  NarrativeDirection,
  NarrativeProvenance,
} from '../../api/engineTypes'
import { Card, CardBody, CardHeader } from '../ui/Card'
import { formatHash, formatNumber, formatShare } from './format'

const PROVENANCE_LABEL: Record<NarrativeProvenance, string> = {
  computed: '计算',
  deliberated: '商议引用',
  template: '模板措辞',
}

const PROVENANCE_CLASS: Record<NarrativeProvenance, string> = {
  computed: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
  deliberated: 'border-violet-500/30 bg-violet-500/10 text-violet-300',
  template: 'border-slate-500/30 bg-slate-500/10 text-slate-400',
}

export function ProvenanceBadge({ provenance }: { provenance: NarrativeProvenance }) {
  return (
    <span
      className={`rounded-full border px-2 py-0.5 text-xs ${PROVENANCE_CLASS[provenance]}`}
      title={
        provenance === 'template'
          ? '模板措辞，不代表分析结论'
          : provenance === 'deliberated'
            ? '引自已存储的商议输出'
            : '由已存储的数值结果计算'
      }
    >
      {PROVENANCE_LABEL[provenance]}
    </span>
  )
}

const SIGNAL_KIND_LABEL: Record<string, string> = {
  decision_gate: '决策门',
  threshold_search: '阈值搜索',
  loop_trigger: '循环触发器',
  advisory_contract: '商议合同',
  wargame_playbook: '推演剧本',
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-2 text-sm font-semibold text-slate-200">{children}</h4>
}

export function DirectionView({ direction }: { direction: NarrativeDirection }) {
  const dist = direction.distribution
  const esValue = dist.expected_shortfall ? asNumber(dist.expected_shortfall.value) : null
  return (
    <Card>
      <CardHeader
        title={`方向 ${direction.rank}：${direction.name}`}
        action={
          <span className="text-xs text-slate-400">
            {direction.arm} 臂 · Run {direction.source_run_id.slice(0, 8)}
          </span>
        }
      />
      <CardBody className="space-y-5">
        <div>
          <div className="flex items-center gap-2">
            <SectionTitle>结果分布</SectionTitle>
            <ProvenanceBadge provenance={dist.provenance} />
          </div>
          <p className="text-sm text-slate-300">
            {dist.metric}：P10 {formatNumber(dist.p10)} / P50 {formatNumber(dist.p50)} / P90{' '}
            {formatNumber(dist.p90)}；均值 {formatNumber(dist.mean)}；亏损概率{' '}
            {formatShare(dist.p_loss)}；n={dist.n}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            ensemble {dist.ensemble_id} · {dist.trials} trials · seed {dist.seed} · loss
            threshold {formatNumber(dist.loss_threshold)}
          </p>
          {esValue !== null && (
            <p className="mt-1 text-sm text-slate-300">
              期望损失（ES）：{formatNumber(esValue)}
            </p>
          )}
          {dist.bootstrap_intervals.map((interval, index) => {
            const estimate = asNumber(interval.estimate)
            const low = asNumber(interval.low)
            const high = asNumber(interval.high)
            if (estimate === null || low === null || high === null) return null
            return (
              <p key={index} className="mt-1 text-sm text-slate-300">
                Bootstrap {String(interval.statistic ?? '')}：估计 {formatNumber(estimate)}，区间
                [{formatNumber(low)}, {formatNumber(high)}]
              </p>
            )
          })}
        </div>

        <div>
          <div className="flex items-center gap-2">
            <SectionTitle>关键驱动</SectionTitle>
            <ProvenanceBadge provenance={direction.drivers.provenance} />
          </div>
          {direction.drivers.rows.length > 0 ? (
            <ul className="space-y-1 text-sm text-slate-300">
              {direction.drivers.rows.map((row) => (
                <li key={row.variable}>
                  {row.variable}：{formatNumber(row.low_value)} → {formatNumber(row.high_value)}{' '}
                  时结果 {formatNumber(row.outcome_low)} → {formatNumber(row.outcome_high)}
                  （swing {formatNumber(row.swing)}）
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">{direction.drivers.note}</p>
          )}
        </div>

        <div>
          <SectionTitle>调头信号</SectionTitle>
          {direction.signals.length > 0 ? (
            <ul className="space-y-1.5 text-sm text-slate-300">
              {direction.signals.map((signal, index) => (
                <li key={index} className="flex flex-wrap items-center gap-2">
                  <span className="text-slate-500">
                    {SIGNAL_KIND_LABEL[signal.kind] ?? signal.kind}
                  </span>
                  <ProvenanceBadge provenance={signal.provenance} />
                  <span>{signal.text}</span>
                  {signal.passed === false && (
                    <span className="text-red-400">（未通过）</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">{direction.signals_note}</p>
          )}
        </div>

        <div>
          <div className="flex items-center gap-2">
            <SectionTitle>事前验尸</SectionTitle>
            <ProvenanceBadge provenance={direction.premortem.provenance} />
          </div>
          {direction.premortem.failure_narrative ? (
            <>
              <p className="text-sm text-slate-300">{direction.premortem.failure_narrative}</p>
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                {direction.premortem.failure_modes.map((mode) => (
                  <li key={mode.mode}>
                    失败模式：{mode.mode}；原因：{mode.cause}；早期信号：{mode.early_signal}；
                    预防：{mode.prevention}
                  </li>
                ))}
                {direction.premortem.fatal_flags.map((flag) => (
                  <li key={flag}>致命标记：{flag}</li>
                ))}
              </ul>
              {direction.premortem.deliberation_id && (
                <p className="mt-1 text-xs text-slate-500">
                  引自 deliberation {direction.premortem.deliberation_id}
                  {direction.premortem.template_id
                    ? ` · 模板 ${direction.premortem.template_id}`
                    : ''}
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-slate-400">{direction.premortem.note}</p>
          )}
        </div>

        <div>
          <div className="flex items-center gap-2">
            <SectionTitle>48 小时第一步</SectionTitle>
            <ProvenanceBadge provenance={direction.first_step.provenance} />
          </div>
          {direction.first_step.next_action ? (
            <>
              <p className="text-sm text-slate-300">{direction.first_step.next_action}</p>
              {direction.first_step.cheapest_validation_test && (
                <p className="mt-1 text-sm text-slate-300">
                  最便宜的验证：{direction.first_step.cheapest_validation_test}
                </p>
              )}
              {direction.first_step.conditions.map((condition) => (
                <p key={condition} className="mt-1 text-sm text-slate-300">
                  条件：{condition}
                </p>
              ))}
              {direction.first_step.deliberation_id && (
                <p className="mt-1 text-xs text-slate-500">
                  引自 deliberation {direction.first_step.deliberation_id}
                  {direction.first_step.template_id
                    ? ` · 模板 ${direction.first_step.template_id}`
                    : ''}
                </p>
              )}
            </>
          ) : (
            <p className="text-sm text-slate-400">{direction.first_step.note}</p>
          )}
        </div>

        <div>
          <SectionTitle>回溯</SectionTitle>
          {direction.mece_trace ? (
            <ul className="space-y-1 text-sm text-slate-300">
              {direction.mece_trace.branches.map((branch) => (
                <li key={branch.name}>
                  MECE 分支：{branch.name}（{branch.scope.join(', ')}）
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-400">{direction.mece_note}</p>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

export function NarrativeView({
  narrative,
  onPolish,
  polishing,
  polishError,
}: {
  narrative: DecisionNarrativeRead
  onPolish: () => void
  polishing: boolean
  polishError: string | null
}) {
  const body = narrative.body
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={`简报：${body.topic}`} />
        <CardBody className="space-y-2 text-sm text-slate-300">
          <p>
            版本 v{narrative.version} · 锚定 Run {body.anchor_run_id} · 领域 {body.domain_id} ·
            协议 {body.protocol}
          </p>
          <p className="text-xs text-slate-500">
            inputs {formatHash(narrative.inputs_hash)} · content{' '}
            {formatHash(narrative.content_hash)} · 生成于 {narrative.created_at}
          </p>
          {body.mece && (
            <p>
              MECE：{body.mece.topic}；校验{body.mece.is_mece ? '通过' : '未通过'}；
              {body.mece.branch_count} 个分支，{body.mece.scope_tag_count} 个 scope 标签
            </p>
          )}
          {body.calibration_context.map((entry) => (
            <p key={entry.fit_id}>
              校准拟合 {entry.fit_id}（{entry.kind}，LOO RMSE{' '}
              {entry.loo_rmse !== null ? formatNumber(entry.loo_rmse) : 'n/a'}，
              {entry.n_observations} 个观测）
            </p>
          ))}
          {body.loop_context && (
            <p>
              监测循环：{body.loop_context.loop_name}（{body.loop_context.loop_id}），
              {body.loop_context.trigger_count} 个触发器
            </p>
          )}
        </CardBody>
      </Card>

      {body.directions.map((direction) => (
        <DirectionView key={direction.rank} direction={direction} />
      ))}

      <Card>
        <CardHeader title="确定性简报原文" />
        <CardBody>
          <pre className="whitespace-pre-wrap text-sm text-slate-300">{body.markdown}</pre>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="LLM 润色"
          action={
            <button
              type="button"
              onClick={onPolish}
              disabled={polishing}
              className="rounded-full border border-slate-600 px-3 py-1 text-xs text-slate-200 transition hover:bg-slate-700/50 disabled:opacity-50"
            >
              {polishing ? '润色中…' : '请求润色'}
            </button>
          }
        />
        <CardBody className="space-y-2">
          {polishError && <p className="text-sm text-red-400">{polishError}</p>}
          {narrative.polish ? (
            <>
              <p className="text-xs text-amber-300">
                以下文本由 LLM 生成（模型：{narrative.polish.model ?? '未知'}，模板{' '}
                {narrative.polish.template_id} v{narrative.polish.template_version}），仅供阅读；
                结构化简报仍是事实来源。
              </p>
              <pre className="whitespace-pre-wrap text-sm text-slate-300">
                {narrative.polish.polished_markdown}
              </pre>
            </>
          ) : (
            <p className="text-sm text-slate-400">
              尚未润色。润色只改写措辞，不改变任何数字与结论；LLM 不可用时显示确定性原文。
            </p>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
