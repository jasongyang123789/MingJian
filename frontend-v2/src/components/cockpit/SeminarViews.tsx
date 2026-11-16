// Seminar cockpit views (Sprint 20): presentational components over
// stored seminar rows only. Board digests and verdicts are rendered
// as quotations (design §4.3: board content may be right or wrong,
// never an instruction); disagreements are shown prominently and
// never averaged away; every number comes from a stored row or a
// computed-metrics block the backend assembled — nothing here
// re-derives, estimates, or synthesizes.

import type {
  AuditEventRead,
  BoardRowRead,
  CanonicalClaimRead,
  ChairBriefRead,
  ComputedMetricsRead,
  DisagreementRead,
  FinalRowRead,
  FinalVerdictRead,
  RoundRowRead,
  SeminarBudgetsRead,
  SeminarDetailRead,
  SeminarDiagnosisRead,
  SeminarReportDocument,
  StageRecordRead,
} from '../../api/engineTypes'
import { StatusBadge } from '../ui/StatusBadge'
import { ProvenanceBadge } from './DirectionViews'
import { formatHash, formatNumber, formatShare } from './format'
import {
  auditDetailLines,
  endpointSummary,
  formatDurationMs,
  stageRecordSummary,
} from './seminarUtils'

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-2 text-sm font-semibold text-slate-200">{children}</h4>
}

export function JsonBlock({ value, label }: { value: unknown; label?: string }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
        {label ?? '原始 JSON'}
      </summary>
      <pre className="mt-1 max-h-64 overflow-auto rounded-lg bg-slate-900/60 p-3 font-mono text-[11px] leading-5 text-slate-300">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  )
}

function StringList({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-slate-500">{empty}</p>
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
      {items.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  )
}

/** One model's final verdict, verbatim. Shared by the finals list,
 * the chair brief, and the report's rounds-evolution section. */
export function VerdictCard({
  modelId,
  verdict,
  stage,
  boardSeq,
}: {
  modelId: string
  verdict: FinalVerdictRead
  stage?: StageRecordRead | null
  boardSeq?: number | null
}) {
  return (
    <div className="space-y-3 rounded-lg border border-slate-700/50 bg-slate-800/20 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-100">{modelId}</span>
        <span className="text-xs text-slate-400">置信度：{verdict.confidence}</span>
        {boardSeq !== null && boardSeq !== undefined && (
          <span className="text-xs text-slate-500">board 快照 seq {boardSeq}</span>
        )}
      </div>
      <blockquote className="border-l-2 border-violet-500/40 pl-3 text-sm text-slate-200">
        建议：{verdict.recommendation}
      </blockquote>
      <div>
        <p className="text-xs text-slate-400">排序方案</p>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-300">
          {verdict.ranked_alternatives.map((alternative, index) => (
            <li key={index}>{alternative}</li>
          ))}
        </ol>
      </div>
      <div>
        <p className="text-xs text-slate-400">关键证据</p>
        <StringList items={verdict.key_evidence} empty="无" />
      </div>
      <div>
        <p className="text-xs text-slate-400">关键假设（load-bearing）</p>
        <StringList items={verdict.load_bearing_assumptions} empty="无" />
      </div>
      <div>
        <p className="text-xs text-slate-400">叫停标准</p>
        <StringList items={verdict.kill_criteria} empty="无" />
      </div>
      <div>
        <p className="text-xs text-slate-400">保留异议</p>
        <StringList items={verdict.dissent_held} empty="无" />
      </div>
      <div>
        <p className="text-xs text-slate-400">轮次小结</p>
        <p className="whitespace-pre-wrap text-sm text-slate-300">{verdict.rounds_summary}</p>
      </div>
      {stage && <p className="text-xs text-slate-500">{stageRecordSummary(stage)}</p>}
    </div>
  )
}

export function BudgetsPanel({ budgets }: { budgets: SeminarBudgetsRead }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-lg border border-slate-700/50 bg-slate-800/20 p-3">
        <p className="text-xs text-slate-400">阶段调用预算</p>
        <p className="text-sm text-slate-100">
          已用 {formatNumber(budgets.stage_calls_used)} / 上限{' '}
          {formatNumber(budgets.max_stage_calls)} · 剩余{' '}
          {formatNumber(budgets.stage_calls_remaining)}
        </p>
      </div>
      <div className="rounded-lg border border-slate-700/50 bg-slate-800/20 p-3">
        <p className="text-xs text-slate-400">Token 预算</p>
        <p className="text-sm text-slate-100">
          已用 {formatNumber(budgets.tokens_used)} / 上限 {formatNumber(budgets.max_tokens)} ·
          剩余 {formatNumber(budgets.tokens_remaining)}
        </p>
      </div>
    </div>
  )
}

export function DiagnosisPanel({ diagnosis }: { diagnosis: SeminarDiagnosisRead }) {
  const errorEntries = Object.entries(diagnosis.error_counts)
  return (
    <div className="space-y-2 text-sm text-slate-300">
      <p>
        阶段调用 {formatNumber(diagnosis.stage_calls)} 次（{formatNumber(diagnosis.stage_call_attempts)}{' '}
        次尝试）· 重试 {formatNumber(diagnosis.retries)} 次 · 兜底{' '}
        {formatNumber(diagnosis.fallbacks)} 次 · 排队等待 {formatNumber(diagnosis.queue_waits)} 次
      </p>
      <p>
        Token 合计 {formatNumber(diagnosis.total_tokens)}（提示{' '}
        {formatNumber(diagnosis.total_prompt_tokens)} + 完成{' '}
        {formatNumber(diagnosis.total_completion_tokens)}）· 总耗时{' '}
        {formatDurationMs(diagnosis.total_duration_ms)}
      </p>
      {errorEntries.length === 0 ? (
        <p className="text-slate-500">无已记录失败（每次失败恰好计一次；重试后恢复的超时不计入）。</p>
      ) : (
        <ul className="space-y-1">
          {errorEntries.map(([kind, count]) => (
            <li key={kind}>
              失败 {kind}：{formatNumber(count)} 次
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function RosterProgressTable({ detail }: { detail: SeminarDetailRead }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-300">
        <span>
          状态 <StatusBadge status={detail.status} />
        </span>
        <span>
          主控模式：{detail.config.chair_mode === 'agent' ? 'agent（Glint）' : 'model'}
          {detail.config.chair_participates ? ' · 主控同时是名册模型（自偏风险，见报告）' : ''}
        </span>
        <span>
          终裁 {detail.finals_count} / {detail.roster.length}
        </span>
        <span>
          board 发布 {detail.board_publications} 条 · 最新 seq {detail.board_latest_seq}
        </span>
        <span>快照哈希 {formatHash(detail.case_snapshot_hash)}</span>
      </div>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs text-slate-400">
            <th className="py-2 pr-3 font-medium">模型</th>
            <th className="py-2 pr-3 font-medium">状态</th>
            <th className="py-2 pr-3 font-medium">轮次</th>
            <th className="py-2 pr-3 font-medium">终裁</th>
            <th className="py-2 pr-3 font-medium">最新 board seq</th>
            <th className="py-2 font-medium">端点</th>
          </tr>
        </thead>
        <tbody>
          {detail.roster.map((entry) => {
            const progress = detail.per_model.find((row) => row.model_id === entry.model_id)
            return (
              <tr key={entry.model_id} className="border-b border-slate-800/60">
                <td className="py-2 pr-3 text-slate-100">{entry.model_id}</td>
                <td className="py-2 pr-3">
                  <StatusBadge status={progress?.status} />
                </td>
                <td className="py-2 pr-3 text-slate-300">{progress?.rounds ?? 0}</td>
                <td className="py-2 pr-3 text-slate-300">{progress?.has_final ? '是' : '否'}</td>
                <td className="py-2 pr-3 text-slate-300">
                  {progress?.latest_board_seq ?? '—'}
                </td>
                <td className="py-2 text-xs text-slate-400">
                  {endpointSummary(entry.endpoint)} · 温度 {formatNumber(entry.temperature)} ·
                  超时 {formatNumber(entry.timeout_seconds)}s
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="text-xs text-slate-500">
        管线 {detail.config.pipeline} / {detail.config.mode} · 最多 {detail.config.max_rounds}{' '}
        轮 · quiet {detail.config.quiet_rounds} 轮 · 语言 {detail.config.output_language} ·
        重试上限 {detail.config.max_retries} 次 · 近似重复阈值{' '}
        {formatNumber(detail.config.near_duplicate_threshold)}
      </p>
    </div>
  )
}

export function BoardTimeline({ rows }: { rows: BoardRowRead[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">board 上还没有发布。推进一波后，各模型的摘要会按 seq 顺序出现在这里。</p>
  }
  return (
    <ol className="space-y-4">
      {rows.map((row) => (
        <li key={row.id} className="rounded-lg border border-slate-700/50 bg-slate-800/20 p-4">
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="font-mono text-slate-300">seq {row.seq}</span>
            <span className="font-medium text-slate-100">{row.model_id}</span>
            <span>第 {row.round_no} 轮</span>
            {row.digest.confidence && <span>置信度：{row.digest.confidence}</span>}
            <span>读取 board 快照 seq {row.digest.board_snapshot_seq}</span>
            {row.digest.reflection_missing && (
              <span className="text-amber-300">反思缺失（分析成立，反思阶段失败）</span>
            )}
          </div>
          {/* Quotation, not instruction: board content may be right or
              wrong (design §4.3). */}
          <blockquote className="border-l-2 border-blue-500/40 pl-3 text-sm text-slate-200">
            {row.digest.recommendation}
          </blockquote>
          {row.digest.key_arguments.length > 0 && (
            <div className="mt-2">
              <p className="text-xs text-slate-400">关键论点</p>
              <StringList items={row.digest.key_arguments} empty="无" />
            </div>
          )}
          {row.digest.kill_criteria.length > 0 && (
            <div className="mt-2">
              <p className="text-xs text-slate-400">叫停标准</p>
              <StringList items={row.digest.kill_criteria} empty="无" />
            </div>
          )}
          {row.digest.changes.length > 0 && (
            <div className="mt-2">
              <p className="text-xs text-slate-400">相对上一轮的变化</p>
              <StringList items={row.digest.changes} empty="无" />
            </div>
          )}
        </li>
      ))}
    </ol>
  )
}

export function RoundsComparison({ rows }: { rows: RoundRowRead[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">还没有轮次记录。推进一波后，各模型的轮次会在这里按模型对比。</p>
  }
  const byModel = new Map<string, RoundRowRead[]>()
  for (const row of rows) {
    const list = byModel.get(row.model_id) ?? []
    list.push(row)
    byModel.set(row.model_id, list)
  }
  return (
    <div className="space-y-6">
      {[...byModel.entries()].map(([modelId, modelRows]) => (
        <div key={modelId}>
          <SectionTitle>{modelId}</SectionTitle>
          <div className="space-y-3">
            {[...modelRows]
              .sort((a, b) => a.round_no - b.round_no)
              .map((row) => (
                <div
                  key={row.id}
                  className="space-y-2 rounded-lg border border-slate-700/50 bg-slate-800/20 p-4"
                >
                  <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                    <span className="font-medium text-slate-100">第 {row.round_no} 轮</span>
                    <StatusBadge status={row.status} />
                    <span>读取 board 快照 seq {row.board_snapshot_seq}</span>
                    <span>{row.stages.length} 个分析阶段</span>
                  </div>
                  {row.stages.length > 0 && (
                    <p className="text-xs text-slate-500">
                      阶段：{row.stages.map((stage) => stage.template_id).join(' → ')}
                    </p>
                  )}
                  {row.error && (
                    <p className="text-sm text-red-300">
                      失败（{row.error.kind}
                      {row.error.stage ? ` @ ${row.error.stage}` : ''}）：{row.error.message}
                    </p>
                  )}
                  {row.reflection ? (
                    <div className="space-y-1 text-sm text-slate-300">
                      <p>
                        反思置信度：{row.reflection.confidence}（{row.reflection.confidence_basis}）
                      </p>
                      {row.reflection.critique.length > 0 && (
                        <ul className="list-disc space-y-1 pl-5">
                          {row.reflection.critique.map((point, index) => (
                            <li key={index}>
                              弱点：{point.weak_point} — {point.reason}
                            </li>
                          ))}
                        </ul>
                      )}
                      {row.reflection.responses.length > 0 && (
                        <ul className="list-disc space-y-1 pl-5">
                          {row.reflection.responses.map((response, index) => (
                            <li key={index}>
                              回应 {response.model_id}（{response.stance}）：{response.reason}
                            </li>
                          ))}
                        </ul>
                      )}
                      {row.reflection.changes.length > 0 && (
                        <p>变化：{row.reflection.changes.join('；')}</p>
                      )}
                      {row.reflection.open_questions.length > 0 && (
                        <p>开放问题：{row.reflection.open_questions.join('；')}</p>
                      )}
                      {row.reflection_stage && (
                        <p className="text-xs text-slate-500">
                          {stageRecordSummary(row.reflection_stage)}
                        </p>
                      )}
                    </div>
                  ) : (
                    row.status !== 'failed' && (
                      <p className="text-sm text-slate-500">无反思记录。</p>
                    )
                  )}
                </div>
              ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function FinalsList({ rows }: { rows: FinalRowRead[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">还没有终裁。定稿后，各模型的终裁会逐字出现在这里。</p>
  }
  return (
    <div className="space-y-4">
      {rows.map((row) => (
        <VerdictCard
          key={row.id}
          modelId={row.model_id}
          verdict={row.verdict}
          stage={row.stage}
          boardSeq={row.board_snapshot_seq}
        />
      ))}
    </div>
  )
}

export function ComputedMetricsView({ metrics }: { metrics: ComputedMetricsRead }) {
  const agreement = metrics.recommendation_agreement
  const borda = metrics.borda
  const dedup = metrics.dedup
  return (
    <div className="space-y-3 text-sm text-slate-300">
      <p>
        推荐一致率：{agreement.pairs_agreeing}/{agreement.pairs_total} 对一致
        {agreement.rate !== null ? `（${formatShare(agreement.rate)}）` : '（单模型，无配对）'} ·{' '}
        {agreement.n_models} 个模型
      </p>
      <p>
        置信度分布：低 {metrics.confidence_distribution.low ?? 0} · 中{' '}
        {metrics.confidence_distribution.medium ?? 0} · 高{' '}
        {metrics.confidence_distribution.high ?? 0}
      </p>
      <p>
        去重：{dedup.original_items} 个原始主张项 → {dedup.canonical_claims} 条规范主张 ·{' '}
        {dedup.exact_duplicate_groups} 个精确重复组 · {dedup.semantic_merge_groups} 个语义合并组
        （聚类生产：{dedup.cluster_production}）
      </p>
      <p>分歧数：{metrics.disagreement_count}</p>
      <div>
        <p className="text-xs text-slate-400">Borda 计数（{borda.method}）</p>
        <ol className="list-decimal space-y-1 pl-5">
          {borda.ranked.map((name) => (
            <li key={name}>
              {name}：{formatNumber(borda.totals[name] ?? 0)} 分
            </li>
          ))}
        </ol>
      </div>
      <p>
        轮次合计 {metrics.rounds.total_rounds} 轮 · 终裁 {metrics.finals_used} / 名册{' '}
        {metrics.roster_size}
      </p>
      {metrics.absent_models.length > 0 && (
        <div>
          <p className="text-xs text-slate-400">缺席模型</p>
          <ul className="list-disc space-y-1 pl-5">
            {metrics.absent_models.map((absent) => (
              <li key={absent.model_id}>
                {absent.model_id}（{absent.status}）：{absent.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ClaimsView({
  claims,
  mergeMap,
}: {
  claims: CanonicalClaimRead[]
  mergeMap: Record<string, number>
}) {
  if (claims.length === 0) return <p className="text-sm text-slate-500">无规范主张。</p>
  return (
    <div className="space-y-3">
      {claims.map((claim, index) => (
        <div key={index} className="rounded-lg border border-slate-700/50 bg-slate-800/20 p-3">
          <p className="text-sm text-slate-100">
            主张 {index}：{claim.claim}
          </p>
          <ul className="mt-2 space-y-1 text-xs text-slate-400">
            {claim.sources.map((source) => (
              <li key={source.item_id}>
                [{source.item_id} | {source.model_id} | 第 {source.round_no} 轮 | {source.field} |{' '}
                {source.stance}] “{source.original_text}”
              </li>
            ))}
          </ul>
        </div>
      ))}
      <p className="text-xs text-slate-500">
        merge_map（主张项 → 主张序号，由代码生成）：{' '}
        {Object.entries(mergeMap)
          .map(([itemId, claimIndex]) => `${itemId}→${claimIndex}`)
          .join(', ') || '—'}
      </p>
    </div>
  )
}

/** Disagreements are PRESERVED, never averaged away: prominent red
 * cards, both sides quoted verbatim, stances labeled. */
export function DisagreementsView({ items }: { items: DisagreementRead[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        无分歧：没有一条主张同时承载两种以上立场。分歧由代码从立场推导，从不由主控裁决谁对谁错。
      </p>
    )
  }
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-red-300">
        分歧 {items.length} 条 — 被保留、被展示，从不被平均掉。主控只识别分歧，不裁决分歧。
      </p>
      {items.map((disagreement) => (
        <div
          key={disagreement.claim_index}
          className="rounded-lg border border-red-500/40 bg-red-500/5 p-4"
        >
          <p className="text-sm font-medium text-slate-100">
            主张 {disagreement.claim_index}：{disagreement.claim}
          </p>
          <p className="mt-1 text-xs text-red-300">立场：{disagreement.stances.join(' / ')}</p>
          <div className="mt-2 space-y-2">
            {disagreement.positions.map((position) => (
              <div key={position.stance}>
                <p className="text-xs font-medium text-slate-300">立场 {position.stance}：</p>
                <ul className="mt-1 space-y-1 text-xs text-slate-400">
                  {position.sources.map((source, index) => (
                    <li key={index}>
                      [{source.model_id} | 第 {source.round_no} 轮 | {source.field}] “
                      {source.original_text}”
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function ReportDocumentView({ document }: { document: SeminarReportDocument }) {
  const header = document.header
  return (
    <div className="space-y-6">
      <div className="space-y-1 text-sm text-slate-300">
        <p>
          报告 v{header.version} · {header.partial ? '部分报告（终裁数少于名册）' : '完整报告'} ·
          主控 {header.chair_model_id}（{header.chair_mode} 模式）· 生产路径{' '}
          {header.production_path} / {header.cluster_production}
        </p>
        <p>
          终裁 {header.finals_used} / 名册 {header.roster_size} · 哈希{' '}
          {formatHash(header.report_hash)}
        </p>
        {header.brief_version !== undefined && (
          <p>
            回答简报 v{header.brief_version}
            {header.brief_hash ? ` · ${formatHash(header.brief_hash)}` : ''}
          </p>
        )}
        {header.chair_provenance_note && (
          <p className="text-xs text-slate-400">{header.chair_provenance_note}</p>
        )}
        {header.chair_participation_flag && (
          <p className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-200">
            {header.chair_participation_flag}
          </p>
        )}
        {header.fallback_reason && (
          <p className="text-xs text-amber-300">兜底原因：{header.fallback_reason}</p>
        )}
        {header.absent_models.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-xs text-slate-400">
            {header.absent_models.map((absent) => (
              <li key={absent.model_id}>
                缺席 {absent.model_id}（{absent.status}）：{absent.reason}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>统一建议</SectionTitle>
          <ProvenanceBadge provenance={document.unified_recommendation.provenance} />
        </div>
        <p className="whitespace-pre-wrap text-sm text-slate-200">
          {document.unified_recommendation.text}
        </p>
        {document.unified_recommendation.basis && (
          <p className="mt-1 text-xs text-slate-400">
            依据：{document.unified_recommendation.basis}
          </p>
        )}
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>一致程度（主控判断与计算结果并列，互不替代）</SectionTitle>
          <ProvenanceBadge provenance={document.agreement.chair_provenance} />
        </div>
        <p className="text-sm text-slate-300">
          主控判断：{document.agreement.chair_level ?? '无'}
          {document.agreement.computed && (
            <>
              {' '}· 计算一致率：{document.agreement.computed.pairs_agreeing}/
              {document.agreement.computed.pairs_total} 对
              {document.agreement.computed.rate !== null
                ? `（${formatShare(document.agreement.computed.rate)}）`
                : ''}
            </>
          )}
        </p>
        <p className="mt-1 text-xs text-slate-500">{document.agreement.note}</p>
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>分歧</SectionTitle>
          <ProvenanceBadge provenance={document.disagreements.provenance} />
        </div>
        <DisagreementsView items={document.disagreements.items} />
        <p className="mt-1 text-xs text-slate-500">{document.disagreements.note}</p>
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>规范主张</SectionTitle>
          <ProvenanceBadge provenance={document.canonical_claims.provenance} />
        </div>
        <ClaimsView claims={document.canonical_claims.claims} mergeMap={document.canonical_claims.merge_map} />
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>备选方案</SectionTitle>
          <ProvenanceBadge provenance={document.alternatives.borda_provenance} />
        </div>
        {document.alternatives.borda && (
          <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-300">
            {document.alternatives.borda.ranked.map((name) => (
              <li key={name}>
                {name}：Borda {formatNumber(document.alternatives.borda?.totals[name] ?? 0)} 分
              </li>
            ))}
          </ol>
        )}
        <p className="mt-2 text-sm text-slate-300">
          主控排序：
          {document.alternatives.chair_ranked
            ? document.alternatives.chair_ranked.join(' › ')
            : '无'}
        </p>
        <p className="mt-1 text-sm text-slate-300">
          聚合规则：{document.alternatives.aggregation_rule}
        </p>
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>关键证据</SectionTitle>
          <ProvenanceBadge provenance={document.key_evidence.provenance} />
        </div>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
          {document.key_evidence.items.map((item, index) => (
            <li key={index}>
              {item.text}（来源：{item.source_models.join(', ')}）
            </li>
          ))}
        </ul>
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>叫停标准</SectionTitle>
          <ProvenanceBadge provenance={document.kill_criteria.provenance} />
        </div>
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-300">
          {document.kill_criteria.items.map((item, index) => (
            <li key={index}>
              {item.text}（来源：{item.source_models.join(', ')}）
            </li>
          ))}
        </ul>
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>少数派报告（逐字保留）</SectionTitle>
          <ProvenanceBadge provenance={document.minority_report.provenance} />
        </div>
        <p className="whitespace-pre-wrap text-sm text-slate-200">{document.minority_report.text}</p>
      </div>

      <div>
        <SectionTitle>轮次演变（各模型终裁中的轮次小结，逐字）</SectionTitle>
        <div className="space-y-2">
          {document.rounds_evolution.map((entry) => (
            <div key={entry.model_id}>
              <p className="text-xs text-slate-400">
                {entry.model_id} · board 快照 seq {entry.board_snapshot_seq}
              </p>
              <p className="whitespace-pre-wrap text-sm text-slate-300">{entry.rounds_summary}</p>
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>开放问题</SectionTitle>
          <ProvenanceBadge provenance={document.open_questions.provenance} />
        </div>
        <StringList items={document.open_questions.items} empty="无" />
        {document.open_questions.note && (
          <p className="mt-1 text-xs text-slate-500">{document.open_questions.note}</p>
        )}
      </div>

      <div>
        <div className="flex items-center gap-2">
          <SectionTitle>主控备注</SectionTitle>
          <ProvenanceBadge provenance={document.chair_notes.provenance} />
        </div>
        <p className="whitespace-pre-wrap text-sm text-slate-300">{document.chair_notes.text}</p>
      </div>

      <div>
        <SectionTitle>计算指标</SectionTitle>
        <ComputedMetricsView metrics={document.computed_metrics} />
      </div>

      <div>
        <SectionTitle>审计附录</SectionTitle>
        <div className="space-y-1 text-xs text-slate-400">
          <p>案例快照哈希：{formatHash(document.audit_appendix.case_snapshot_hash)}</p>
          <p>
            board 序号范围：
            {document.audit_appendix.board_seq_range.length === 2
              ? `${document.audit_appendix.board_seq_range[0]}–${document.audit_appendix.board_seq_range[1]}`
              : '—'}
            · 发布 {document.audit_appendix.board_publications} 条
          </p>
          <p>
            每模型阶段数：
            {Object.entries(document.audit_appendix.round_stage_counts)
              .map(([modelId, count]) => `${modelId}: ${count}`)
              .join(', ') || '—'}
          </p>
          {document.audit_appendix.verdict_stages.map((stage) => (
            <p key={stage.model_id}>
              终裁阶段 {stage.model_id}：{stage.template_id} v{stage.template_version} · 契约 v
              {stage.contract_version}
              {stage.model ? ` · ${stage.model}` : ''}
            </p>
          ))}
          {typeof document.audit_appendix.token_usage === 'string' ? (
            <p>Token 用量：{document.audit_appendix.token_usage}</p>
          ) : (
            <JsonBlock value={document.audit_appendix.token_usage} label="Token 用量汇总" />
          )}
          <JsonBlock value={document.audit_appendix.cluster_stage} label="聚类阶段记录" />
          <JsonBlock value={document.audit_appendix.synthesis_stage} label="综合阶段记录" />
          <JsonBlock value={document.audit_appendix.model_configs} label="模型配置（端点名，无 key）" />
          <JsonBlock value={document.audit_appendix.chair_config} label="主控配置" />
        </div>
      </div>

      {document.chair_synthesis && (
        <div>
          <SectionTitle>主控综合原文（契约载荷）</SectionTitle>
          <JsonBlock value={document.chair_synthesis} label="SeminarSynthesis 载荷" />
        </div>
      )}
    </div>
  )
}

export function AuditLogView({ events }: { events: AuditEventRead[] }) {
  if (events.length === 0) {
    return <p className="text-sm text-slate-500">没有符合筛选的审计事件。推进、定稿、合成或被拒绝的请求都会在这里留下一行。</p>
  }
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-700/50 text-xs text-slate-400">
          <th className="py-2 pr-3 font-medium">seq</th>
          <th className="py-2 pr-3 font-medium">种类</th>
          <th className="py-2 pr-3 font-medium">模型</th>
          <th className="py-2 pr-3 font-medium">阶段</th>
          <th className="py-2 pr-3 font-medium">轮次</th>
          <th className="py-2 font-medium">详情</th>
        </tr>
      </thead>
      <tbody>
        {events.map((event) => (
          <tr key={event.id} className="border-b border-slate-800/60 align-top">
            <td className="py-2 pr-3 font-mono text-xs text-slate-300">{event.seq}</td>
            <td className="py-2 pr-3 font-mono text-xs text-slate-100">{event.kind}</td>
            <td className="py-2 pr-3 text-slate-300">{event.model_id ?? '—'}</td>
            <td className="py-2 pr-3 font-mono text-xs text-slate-400">{event.stage ?? '—'}</td>
            <td className="py-2 pr-3 text-slate-300">{event.round_no ?? '—'}</td>
            <td className="py-2">
              <ul className="space-y-0.5 text-xs text-slate-300">
                {auditDetailLines(event.kind, event.detail).map((line, index) => (
                  <li key={index}>{line}</li>
                ))}
              </ul>
              <p className="mt-1 text-[11px] text-slate-500">
                {event.created_at}
                {event.stage_call_id ? ` · 调用 ${event.stage_call_id.slice(0, 8)}` : ''}
              </p>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function ChairBriefView({ brief }: { brief: ChairBriefRead }) {
  const itemsById = new Map(brief.prepass.items.map((item) => [item.item_id, item]))
  return (
    <div className="space-y-6">
      <div className="space-y-1 text-sm text-slate-300">
        <p>
          简报 v{brief.brief_version} · 哈希 {formatHash(brief.brief_hash)} · 终裁{' '}
          {brief.finals_used} / 名册 {brief.roster_size}
          {brief.partial ? ' · 部分（终裁数少于名册）' : ''}
        </p>
        <p>提交端点：{brief.submit_endpoint}</p>
        <p className="text-xs text-slate-400">{brief.participation_note}</p>
        {brief.absent_models.length > 0 && (
          <ul className="list-disc space-y-1 pl-5 text-xs text-slate-400">
            {brief.absent_models.map((absent) => (
              <li key={absent.model_id}>
                缺席 {absent.model_id}（{absent.status}）：{absent.reason}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <SectionTitle>
          预处理：{brief.prepass.item_count} 个主张项 · {brief.prepass.exact_duplicate_groups}{' '}
          个精确重复组 · {brief.prepass.near_duplicate_group_count} 个近似重复组（阈值{' '}
          {formatNumber(brief.prepass.near_duplicate_threshold)}）
          {brief.prepass.excluded_dissent_placeholders
            ? ` · 排除 ${brief.prepass.excluded_dissent_placeholders} 个异议占位符`
            : ''}
        </SectionTitle>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-700/50 text-xs text-slate-400">
              <th className="py-2 pr-3 font-medium">项</th>
              <th className="py-2 pr-3 font-medium">模型</th>
              <th className="py-2 pr-3 font-medium">轮次</th>
              <th className="py-2 pr-3 font-medium">字段</th>
              <th className="py-2 font-medium">原文</th>
            </tr>
          </thead>
          <tbody>
            {brief.prepass.items.map((item) => (
              <tr key={item.item_id} className="border-b border-slate-800/60 align-top">
                <td className="py-2 pr-3 font-mono text-xs text-slate-100">{item.item_id}</td>
                <td className="py-2 pr-3 text-slate-300">{item.model_id}</td>
                <td className="py-2 pr-3 text-slate-300">{item.round_no}</td>
                <td className="py-2 pr-3 text-slate-300">{item.field}</td>
                <td className="py-2 text-slate-300">“{item.text}”</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-slate-500">
          精确组：{brief.prepass.exact_groups.map((group) => `[${group.join(', ')}]`).join(' ')}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          近似重复组（候选合并，主控裁决）：{' '}
          {brief.prepass.near_duplicate_groups
            .filter((group) => group.length > 1)
            .map(
              (group) =>
                `[${group.map((itemId) => itemsById.get(itemId)?.text ?? itemId).join(' | ')}]`,
            )
            .join(' ') || '—'}
        </p>
      </div>

      <div>
        <SectionTitle>确定性聚类（每精确组一条主张，全 support 立场）</SectionTitle>
        <ClaimsView
          claims={brief.deterministic_clusters.claims}
          mergeMap={brief.deterministic_clusters.merge_map}
        />
      </div>

      <div>
        <SectionTitle>分歧</SectionTitle>
        <DisagreementsView items={brief.disagreements} />
      </div>

      <div>
        <SectionTitle>计算指标</SectionTitle>
        <ComputedMetricsView metrics={brief.computed_metrics} />
      </div>

      <div>
        <SectionTitle>终裁原文（逐字引用）</SectionTitle>
        <div className="space-y-4">
          {brief.verdicts.map((entry) => (
            <VerdictCard
              key={entry.model_id}
              modelId={entry.model_id}
              verdict={entry.verdict}
              stage={entry.stage}
              boardSeq={entry.board_snapshot_seq}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
