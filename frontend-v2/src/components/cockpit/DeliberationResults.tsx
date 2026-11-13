import { findTemplate } from '../../data/skillTemplates'
import type {
  AdvisoryBoardResult,
  LensPosition,
  LensRevision,
  SkillDeliberationRecord,
  StageRecord,
  StrategyTeamResult,
} from '../../api/engineTypes'
import { formatNumber } from './format'

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">{children}</h4>
  )
}

function BulletList({ items }: { items: string[] }) {
  if (items.length === 0) return null
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-slate-300">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Stage provenance (shared by both pipelines)
// ---------------------------------------------------------------------------

export function StageProvenanceList({ stages }: { stages: StageRecord[] }) {
  return (
    <div>
      <SectionTitle>阶段出处（模板 id + 版本）</SectionTitle>
      <div className="space-y-1">
        {stages.map((stage, index) => {
          const template = findTemplate(stage.template_id)
          return (
            <div key={index} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono text-xs">
              <span className="text-slate-200">{stage.stage}</span>
              <span className="text-slate-400">
                {stage.template_id} v{stage.template_version}
              </span>
              <span className="text-slate-500">contract skills-v{stage.contract_version}</span>
              {stage.model && <span className="text-slate-500">{stage.model}</span>}
              {template && <span className="font-sans text-slate-500">{template.title}</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Strategy team (McKinsey pipeline)
// ---------------------------------------------------------------------------

export function StrategyTeamResultView({ result }: { result: StrategyTeamResult }) {
  const { shortlist, synthesis, panel, tally } = result
  const criteria = shortlist.ranked[0] ? Object.keys(shortlist.ranked[0].scores) : []
  return (
    <div className="space-y-6">
      <div>
        <SectionTitle>问题界定</SectionTitle>
        <p className="text-sm leading-6 text-slate-300">{result.intake.problem_statement}</p>
        <p className="mt-1 text-xs text-slate-500">
          决策问题：{result.intake.decision_question} · 类型：{result.intake.engagement_type} · 受众：
          {result.intake.audience}
        </p>
        {result.intake.constraints.length > 0 && (
          <p className="mt-1 text-xs text-slate-500">约束：{result.intake.constraints.join('；')}</p>
        )}
      </div>

      <div>
        <SectionTitle>Shortlist（{shortlist.ranked.length} 个入围）</SectionTitle>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
              <th className="py-2 pr-3 font-medium">选项</th>
              {criteria.map((criterion) => (
                <th key={criterion} className="py-2 pr-3 font-medium">
                  {criterion}
                </th>
              ))}
              <th className="py-2 font-medium">入围理由</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {shortlist.ranked.map((entry, rank) => (
              <tr key={entry.name}>
                <td className="py-2 pr-3">
                  <span className="font-medium text-slate-100">
                    #{rank + 1} {entry.name}
                  </span>
                  <p className="mt-0.5 max-w-md text-xs leading-5 text-slate-400">{entry.description}</p>
                </td>
                {criteria.map((criterion) => (
                  <td key={criterion} className="py-2 pr-3 font-mono text-xs text-slate-300">
                    {entry.scores[criterion] !== undefined ? formatNumber(entry.scores[criterion]) : '—'}
                  </td>
                ))}
                <td className="py-2 text-xs leading-5 text-slate-400">{entry.rationale}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {shortlist.dropped.length > 0 && (
          <div className="mt-2 space-y-1">
            {shortlist.dropped.map((dropped) => (
              <p key={dropped.name} className="text-xs text-slate-500">
                落选：{dropped.name} —— {dropped.reason}
              </p>
            ))}
          </div>
        )}
      </div>

      <div>
        <SectionTitle>综合建议（Pyramid）</SectionTitle>
        <p className="text-sm font-medium leading-6 text-slate-100">{synthesis.governing_thought}</p>
        <div className="mt-3 space-y-2">
          {synthesis.arguments.map((argument, index) => (
            <div key={index} className="rounded-lg border border-slate-800/60 px-3 py-2">
              <p className="text-sm text-slate-200">{argument.claim}</p>
              <p className="mt-0.5 text-xs leading-5 text-slate-400">{argument.backing}</p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-sm text-slate-300">
          推荐选项：<span className="font-medium text-slate-100">{synthesis.recommended_option}</span>{' '}
          {result.synthesis_recommendation_in_shortlist ? (
            <span className="text-xs text-emerald-400">（在 shortlist 内）</span>
          ) : (
            <span className="text-xs text-amber-300">（不在 shortlist 内——仅记录，未被拒绝）</span>
          )}
        </p>
        <div className="mt-2">
          <p className="text-xs text-slate-500">承重假设：</p>
          <BulletList items={synthesis.load_bearing_assumptions} />
        </div>
      </div>

      <div>
        <SectionTitle>验证 Panel  tally（≥2 个不同 lens 标记为 fatal 才算 must-address）</SectionTitle>
        {tally.flags.length === 0 ? (
          <p className="text-sm text-slate-500">Panel 未标记任何 fatal flag。</p>
        ) : (
          <div className="space-y-2">
            {tally.flags.map((flag) => (
              <div
                key={flag.flag}
                className={`rounded-lg border px-3 py-2 ${
                  flag.must_address
                    ? 'border-red-500/30 bg-red-500/10'
                    : 'border-slate-800/60 bg-slate-800/20'
                }`}
              >
                <p className="text-sm text-slate-200">
                  {flag.must_address && (
                    <span className="mr-2 rounded-full border border-red-500/30 bg-red-500/20 px-2 py-0.5 text-[11px] font-medium text-red-300">
                      MUST ADDRESS
                    </span>
                  )}
                  {flag.flag}
                </p>
                <p className="mt-0.5 font-mono text-[11px] text-slate-500">
                  lens：{flag.lenses.join(', ')}（{flag.lens_count} 个独立视角）
                </p>
              </div>
            ))}
          </div>
        )}
      </div>

      {panel.wargame && (
        <div>
          <SectionTitle>
            War-game 推演{result.wargame_loop_rounds > 0 ? `（深度模式追加 ${result.wargame_loop_rounds} 轮，${result.wargame_loop_stop_reason}）` : ''}
          </SectionTitle>
          <div className="space-y-2">
            {panel.wargame.scenarios.map((scenario) => (
              <div key={scenario.name} className="rounded-lg border border-slate-800/60 px-3 py-2">
                <p className="text-sm font-medium text-slate-200">{scenario.name}</p>
                <p className="mt-0.5 text-xs leading-5 text-slate-400">
                  触发：{scenario.trigger} · 影响：{scenario.impact} · 可能性：{scenario.likelihood} · 严重度：
                  {scenario.severity}
                </p>
              </div>
            ))}
          </div>
          {panel.wargame.playbook.length > 0 && (
            <div className="mt-3">
              <p className="mb-1 text-xs text-slate-500">Playbook（信号 → 响应 → 负责人）：</p>
              <ul className="space-y-1">
                {panel.wargame.playbook.map((entry, index) => (
                  <li key={index} className="text-sm text-slate-300">
                    {entry.signal} → {entry.response}（{entry.owner}）
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {result.tournament && (
        <div>
          <SectionTitle>Tournament（两两对决，深度模式）</SectionTitle>
          <p className="mb-2 text-sm text-slate-300">
            胜出：<span className="font-medium text-slate-100">{result.tournament.winner ?? '—'}</span> ·
            胜场：
            {Object.entries(result.tournament.wins)
              .map(([option, wins]) => `${option} ${wins}`)
              .join('，')}
          </p>
          <div className="space-y-2">
            {result.tournament.matches.map((match, index) => (
              <div key={index} className="rounded-lg border border-slate-800/60 px-3 py-2 text-sm">
                <p className="text-slate-200">
                  {match.option_a} vs {match.option_b} → 胜者 <span className="font-medium">{match.winner}</span>
                </p>
                <p className="mt-0.5 text-xs leading-5 text-slate-400">{match.rationale}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {panel.premortem && (
        <div>
          <SectionTitle>事前验尸（Pre-mortem）</SectionTitle>
          <p className="text-sm leading-6 text-slate-300">{panel.premortem.failure_narrative}</p>
          <div className="mt-2 space-y-2">
            {panel.premortem.failure_modes.map((mode) => (
              <div key={mode.mode} className="rounded-lg border border-slate-800/60 px-3 py-2">
                <p className="text-sm text-slate-200">{mode.mode}</p>
                <p className="mt-0.5 text-xs leading-5 text-slate-400">
                  原因：{mode.cause} · 早期信号：{mode.early_signal} · 预防：{mode.prevention}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <StageProvenanceList stages={result.stages} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Advisory board (5-persona)
// ---------------------------------------------------------------------------

const LENS_LABELS: Record<string, string> = {
  product_clarity: '产品清晰度',
  risk_capital: '风险与资本',
  scale_systems: '规模与系统',
  offer_strength: 'Offer 强度',
  future_self: '未来自我',
}

function lensLabel(lens: string): string {
  return LENS_LABELS[lens] ?? lens
}

function ScoreTable({
  title,
  rows,
  scoreOf,
}: {
  title: string
  rows: (LensPosition | LensRevision)[]
  scoreOf: (row: LensPosition | LensRevision) => Record<string, number>
}) {
  const options: string[] = []
  for (const row of rows) {
    for (const option of Object.keys(scoreOf(row))) {
      if (!options.includes(option)) options.push(option)
    }
  }
  return (
    <div>
      <SectionTitle>{title}</SectionTitle>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
            <th className="py-2 pr-3 font-medium">Lens</th>
            {options.map((option) => (
              <th key={option} className="py-2 pr-3 font-medium">
                {option}
              </th>
            ))}
            <th className="py-2 font-medium">置信度</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/60">
          {rows.map((row) => {
            const scores = scoreOf(row)
            return (
              <tr key={row.lens}>
                <td className="py-2 pr-3 text-slate-200">
                  {lensLabel(row.lens)} <span className="font-mono text-[11px] text-slate-500">{row.lens}</span>
                </td>
                {options.map((option) => (
                  <td key={option} className="py-2 pr-3 font-mono text-xs text-slate-300">
                    {scores[option] !== undefined ? formatNumber(scores[option]) : '—'}
                  </td>
                ))}
                <td className="py-2 text-xs text-slate-400">{row.confidence}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function AdvisoryBoardResultView({ result }: { result: AdvisoryBoardResult }) {
  const { contract } = result
  return (
    <div className="space-y-6">
      {result.has_unmitigated_veto && (
        <div
          role="alert"
          className="rounded-[20px] border border-red-500/30 bg-red-500/10 px-4 py-3"
        >
          <p className="text-sm font-medium text-red-300">存在未缓解的否决（unmitigated veto）：决策被挡住</p>
          {result.vetoes.map((veto) => (
            <p key={veto.lens} className="mt-1 text-xs leading-5 text-red-200/80">
              {lensLabel(veto.lens)}：{veto.failure_path}（{veto.severity}）——缓解路径：{veto.mitigation}
            </p>
          ))}
          <p className="mt-1 text-xs text-slate-400">
            主席 verdict 为 choose，但否决未被缓解路径覆盖；该否决仍记录在决策契约中。
          </p>
        </div>
      )}

      {result.vetoes.length > 0 && !result.has_unmitigated_veto && (
        <div role="note" className="rounded-[20px] border border-amber-500/20 bg-amber-500/5 px-4 py-3">
          <p className="text-sm font-medium text-amber-300">
            记录在案的否决（{result.vetoes.length}）：已由 validate_first / reject 的缓解路径覆盖
          </p>
          {result.vetoes.map((veto) => (
            <p key={veto.lens} className="mt-1 text-xs leading-5 text-amber-200/80">
              {lensLabel(veto.lens)}：{veto.failure_path}（{veto.severity}）——缓解：{veto.mitigation}
            </p>
          ))}
        </div>
      )}

      <ScoreTable
        title="Round 1 · 各 lens 独立打分"
        rows={result.positions}
        scoreOf={(row) => (row as LensPosition).option_scores}
      />

      <div>
        <SectionTitle>加权方向（lens 分数的加权平均——只是汇总，不是答案）</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <p className="mb-1 text-xs text-slate-500">Round 1（等权）</p>
            <ol className="space-y-1">
              {result.weighted_direction_round1.ranking.map((option, index) => (
                <li key={option} className="text-sm text-slate-300">
                  #{index + 1} {option} ·{' '}
                  {formatNumber(result.weighted_direction_round1.scores[option] ?? 0)}
                </li>
              ))}
            </ol>
          </div>
          <div>
            <p className="mb-1 text-xs text-slate-500">最终（Round 3 × 主席权重）</p>
            <ol className="space-y-1">
              {result.weighted_direction_final.ranking.map((option, index) => (
                <li key={option} className="text-sm text-slate-300">
                  #{index + 1} {option} ·{' '}
                  {formatNumber(result.weighted_direction_final.scores[option] ?? 0)}
                </li>
              ))}
            </ol>
          </div>
        </div>
        {result.unanimous_option && (
          <p className="mt-2 text-xs text-slate-500">
            一致性提示：五个 lens 全部首选 {result.unanimous_option}，强制辩论中已注入 steelman 要求。
          </p>
        )}
      </div>

      {result.revisions.length > 0 && (
        <ScoreTable
          title="Round 3 · 修订后打分"
          rows={result.revisions}
          scoreOf={(row) => (row as LensRevision).revised_scores}
        />
      )}

      {result.debate && (
        <div>
          <SectionTitle>强制辩论 · 分歧</SectionTitle>
          <div className="space-y-3">
            {result.debate.disagreements.map((disagreement, index) => (
              <div key={index} className="rounded-lg border border-slate-800/60 px-3 py-2">
                <p className="text-sm font-medium text-slate-200">{disagreement.trade_off}</p>
                <p className="mt-1 text-xs leading-5 text-slate-400">甲方：{disagreement.case_a}</p>
                <p className="text-xs leading-5 text-slate-400">乙方：{disagreement.case_b}</p>
                <p className="mt-1 text-xs leading-5 text-slate-400">
                  决定性证据：{disagreement.settling_evidence} · 最便宜的验证：{disagreement.cheapest_test}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-500">
            少数派异议：{result.debate.minority_objection}
          </p>
        </div>
      )}

      <div>
        <SectionTitle>决策契约</SectionTitle>
        <div className="rounded-lg border border-slate-800/60 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <span
              className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
                contract.verdict === 'choose'
                  ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
                  : contract.verdict === 'reject'
                    ? 'border-red-500/20 bg-red-500/10 text-red-400'
                    : 'border-amber-500/20 bg-amber-500/10 text-amber-300'
              }`}
            >
              {contract.verdict}
            </span>
            <span className="text-sm text-slate-300">{contract.why_now}</span>
          </div>
          <div className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            <p className="text-slate-300">
              <span className="text-xs text-slate-500">Go 阈值：</span>
              {contract.go_threshold}
            </p>
            <p className="text-slate-300">
              <span className="text-xs text-slate-500">Kill 准则：</span>
              {contract.kill_criterion}
            </p>
            <p className="text-slate-300">
              <span className="text-xs text-slate-500">负责人：</span>
              {contract.owner}
            </p>
            <p className="text-slate-300">
              <span className="text-xs text-slate-500">截止：</span>
              {contract.deadline}
            </p>
            <p className="text-slate-300">
              <span className="text-xs text-slate-500">复核日期：</span>
              {contract.review_date}
            </p>
            <p className="text-slate-300">
              <span className="text-xs text-slate-500">下一步：</span>
              {contract.next_action}
            </p>
          </div>
          <div className="mt-3">
            <p className="text-xs text-slate-500">前置条件：</p>
            <BulletList items={contract.conditions} />
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            最便宜的验证：{contract.cheapest_validation_test}
          </p>
          <p className="mt-1 text-xs leading-5 text-slate-400">不做清单：{contract.do_not_do}</p>
          <p className="mt-1 text-xs leading-5 text-slate-400">少数派报告：{contract.minority_report}</p>
          <p className="mt-1 font-mono text-[11px] text-slate-500">
            lens 权重：
            {Object.entries(contract.lens_weights)
              .map(([lens, weight]) => `${lens}=${weight}`)
              .join(', ')}
          </p>
        </div>
      </div>

      <StageProvenanceList stages={result.stages} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Record dispatch
// ---------------------------------------------------------------------------

export function DeliberationRecordView({ record }: { record: SkillDeliberationRecord }) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-full border border-slate-700/60 bg-slate-800/40 px-2.5 py-0.5 text-[11px] text-slate-300">
          {record.pipeline === 'strategy_team' ? '策略团队' : '顾问团'}
        </span>
        <span className="text-xs text-slate-500">模式：{record.mode}</span>
        <span className="font-mono text-[11px] text-slate-600">
          {record.id} · {record.created_at}
        </span>
      </div>
      {record.result.pipeline === 'strategy_team' ? (
        <StrategyTeamResultView result={record.result} />
      ) : (
        <AdvisoryBoardResultView result={record.result} />
      )}
    </div>
  )
}
