// Seminar detail page (Sprint 20): one seminar's stored state —
// roster progress, budgets + diagnosis, board timeline, rounds,
// finals, versioned reports, the audit log, and (agent-chair mode)
// the chair brief + submission form. Every progression is an
// explicit button: advance, finalize, synthesize. No auto-refresh,
// no polling (Sprint 9 boundary). Failed actions show the backend's
// own error inline and never leave a phantom state.

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { seminarApi } from '../api/engine'
import type {
  ChairBriefRead,
  SeminarDetailRead,
  SynthesizeRead,
} from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import {
  AuditLogView,
  BoardTimeline,
  BudgetsPanel,
  ChairBriefView,
  DiagnosisPanel,
  FinalsList,
  ReportDocumentView,
  RoundsComparison,
  RosterProgressTable,
} from '../components/cockpit/SeminarViews'
import {
  SEMINAR_AUDIT_EVENT_KINDS,
  clustersPrefillFromBrief,
  isChairBrief,
  parseJsonTextarea,
  synthesisTemplate,
} from '../components/cockpit/seminarUtils'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useApi } from '../hooks/useApi'

const INPUT_CLASS =
  'rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 focus:border-blue-500/50 focus:outline-none'
const BUTTON_CLASS =
  'rounded-full border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-medium text-blue-300 transition hover:bg-blue-500/20 disabled:opacity-50'

function BoardSection({ seminarId, refreshKey }: { seminarId: string; refreshKey: number }) {
  const { data, loading, error, reload } = useApi(
    () => seminarApi.listBoard(seminarId),
    `${seminarId}:${refreshKey}`,
  )
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  return <BoardTimeline rows={data ?? []} />
}

function RoundsSection({ seminarId, refreshKey }: { seminarId: string; refreshKey: number }) {
  const { data, loading, error, reload } = useApi(
    () => seminarApi.listRounds(seminarId),
    `${seminarId}:${refreshKey}`,
  )
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  return <RoundsComparison rows={data ?? []} />
}

function FinalsSection({ seminarId, refreshKey }: { seminarId: string; refreshKey: number }) {
  const { data, loading, error, reload } = useApi(
    () => seminarApi.listFinals(seminarId),
    `${seminarId}:${refreshKey}`,
  )
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  return <FinalsList rows={data ?? []} />
}

function ReportReader({ seminarId, version }: { seminarId: string; version: number }) {
  const { data, loading, error, reload } = useApi(
    () => seminarApi.getReport(seminarId, version),
    `${seminarId}:${version}`,
  )
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  if (!data) return <EmptyState title="报告不存在" description="该版本没有已存报告。" />
  return <ReportDocumentView document={data.document} />
}

function ReportsSection({
  seminarId,
  detail,
  refreshKey,
}: {
  seminarId: string
  detail: SeminarDetailRead
  refreshKey: number
}) {
  const [selected, setSelected] = useState<number | null>(null)
  const versions = detail.reports.map((report) => report.version)
  const latest = versions.length > 0 ? Math.max(...versions) : null
  const effective = selected !== null && versions.includes(selected) ? selected : latest
  if (detail.reports.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        还没有报告。终裁后点「合成」：模型主控模式写版本化报告，agent 主控模式先产出主控简报。
      </p>
    )
  }
  return (
    <div className="space-y-4" key={refreshKey}>
      <div className="flex flex-wrap gap-2">
        {[...detail.reports]
          .sort((a, b) => a.version - b.version)
          .map((report) => (
            <button
              key={report.version}
              type="button"
              onClick={() => setSelected(report.version)}
              className={`rounded-full border px-3 py-1.5 text-xs ${
                effective === report.version
                  ? 'border-blue-500/30 bg-blue-500/10 font-medium text-blue-300'
                  : 'border-slate-700/50 bg-slate-800/30 text-slate-400 hover:text-slate-200'
              }`}
            >
              v{report.version}
              {report.partial ? '（部分）' : ''} · {report.production_path}
            </button>
          ))}
      </div>
      {effective !== null && <ReportReader seminarId={seminarId} version={effective} />}
    </div>
  )
}

function AuditSection({ seminarId, refreshKey }: { seminarId: string; refreshKey: number }) {
  const [kind, setKind] = useState('')
  const [modelId, setModelId] = useState('')
  const [applied, setApplied] = useState<{ kind: string; modelId: string }>({
    kind: '',
    modelId: '',
  })
  const { data, loading, error, reload } = useApi(
    () =>
      seminarApi.listAudit(seminarId, {
        kind: applied.kind || undefined,
        model_id: applied.modelId.trim() || undefined,
      }),
    `${seminarId}:${refreshKey}:${applied.kind}:${applied.modelId}`,
  )
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          事件种类
          <select
            aria-label="事件种类"
            className={INPUT_CLASS}
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          >
            <option value="">全部种类</option>
            {SEMINAR_AUDIT_EVENT_KINDS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          模型 id（精确匹配）
          <input
            aria-label="审计筛选模型 id"
            className={INPUT_CLASS}
            value={modelId}
            onChange={(event) => setModelId(event.target.value)}
            placeholder="model-a"
          />
        </label>
        <button
          type="button"
          className={BUTTON_CLASS}
          onClick={() => setApplied({ kind, modelId })}
        >
          应用筛选
        </button>
      </div>
      {loading && <LoadingSpinner />}
      {error && <ErrorBanner message={error} onRetry={reload} />}
      {!loading && !error && <AuditLogView events={data ?? []} />}
    </div>
  )
}

function ChairSubmissionForm({
  seminarId,
  brief,
  onSubmitted,
}: {
  seminarId: string
  brief: ChairBriefRead
  onSubmitted: () => void
}) {
  const [briefVersion, setBriefVersion] = useState(String(brief.brief_version))
  const [clustersText, setClustersText] = useState('')
  const [synthesisText, setSynthesisText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [serverError, setServerError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<SynthesizeRead | null>(null)

  const hasPlaceholders = synthesisText.includes('【')

  async function handleSubmit() {
    setFormError(null)
    setServerError(null)
    setSubmitted(null)
    const clusters = parseJsonTextarea(clustersText, '聚类载荷')
    if (!clusters.ok) {
      setFormError(clusters.error)
      return
    }
    const synthesis = parseJsonTextarea(synthesisText, '综合载荷')
    if (!synthesis.ok) {
      setFormError(synthesis.error)
      return
    }
    if (hasPlaceholders) {
      setFormError('综合载荷仍含占位符【…】：请替换为真实的主控判断后再提交。')
      return
    }
    const parsedVersion = briefVersion.trim() === '' ? null : Number(briefVersion)
    if (parsedVersion !== null && !Number.isInteger(parsedVersion)) {
      setFormError('简报版本须为整数（留空则回答最新简报）。')
      return
    }
    setSubmitting(true)
    try {
      const result = await seminarApi.submitChairSynthesis(seminarId, {
        clusters: clusters.value as Record<string, unknown>,
        synthesis: synthesis.value as Record<string, unknown>,
        brief_version: parsedVersion,
      })
      setSubmitted(result)
      onSubmitted()
    } catch (e: unknown) {
      // Server contract/coverage errors are shown verbatim: the
      // message carries the backend's code + detail.
      setServerError(e instanceof Error ? e.message : String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-slate-200">主控提交（回答简报 v{brief.brief_version}）</h4>
      <p className="text-xs text-slate-400">
        两个载荷都用与模型主控相同的契约校验，聚类走同一条 merge-map 覆盖规则：每个预处理主张项必须恰好出现在一条主张的来源里。提交前校验全部在写行之前完成——被拒绝的提交零行写入。
      </p>
      <label className="flex flex-col gap-1 text-xs text-slate-400">
        简报版本（留空 = 最新简报）
        <input
          aria-label="简报版本"
          className={`${INPUT_CLASS} w-40`}
          value={briefVersion}
          onChange={(event) => setBriefVersion(event.target.value)}
          inputMode="numeric"
        />
      </label>
      <div>
        <div className="mb-1 flex items-center gap-3">
          <label htmlFor="chair-clusters" className="text-xs text-slate-400">
            聚类载荷 JSON（ClaimClusters：claims[].claim + sources[].item_id/stance）
          </label>
          <button
            type="button"
            className="rounded-full border border-slate-600/50 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800/50"
            onClick={() =>
              setClustersText(JSON.stringify(clustersPrefillFromBrief(brief), null, 2))
            }
          >
            填入确定性聚类作为起点
          </button>
        </div>
        <textarea
          id="chair-clusters"
          aria-label="聚类载荷 JSON"
          className={`${INPUT_CLASS} min-h-40 w-full font-mono text-xs`}
          value={clustersText}
          onChange={(event) => setClustersText(event.target.value)}
          placeholder='{"claims": [{"claim": "...", "sources": [{"item_id": "I1", "stance": "support"}]}]}'
        />
      </div>
      <div>
        <div className="mb-1 flex items-center gap-3">
          <label htmlFor="chair-synthesis" className="text-xs text-slate-400">
            综合载荷 JSON（SeminarSynthesis）
          </label>
          <button
            type="button"
            className="rounded-full border border-slate-600/50 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800/50"
            onClick={() => setSynthesisText(JSON.stringify(synthesisTemplate(), null, 2))}
          >
            填入综合模板
          </button>
        </div>
        <textarea
          id="chair-synthesis"
          aria-label="综合载荷 JSON"
          className={`${INPUT_CLASS} min-h-40 w-full font-mono text-xs`}
          value={synthesisText}
          onChange={(event) => setSynthesisText(event.target.value)}
          placeholder='{"unified_recommendation": "...", "recommendation_basis": "chair_judgment", ...}'
        />
      </div>
      {hasPlaceholders && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">
          综合载荷仍含占位符【…】：提交前请全部替换为真实判断，占位文字一旦提交就会写入版本化报告。
        </p>
      )}
      {formError && <ErrorBanner message={formError} />}
      {serverError && <ErrorBanner message={serverError} />}
      {submitted && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-200">
          已写入报告 v{submitted.version}（{submitted.production_path} · 主控{' '}
          {submitted.chair_model_id} · {submitted.partial ? '部分报告' : '完整报告'}）。
        </div>
      )}
      <button
        type="button"
        className={BUTTON_CLASS}
        onClick={() => void handleSubmit()}
        disabled={submitting || hasPlaceholders}
      >
        {submitting ? '提交中…' : '提交主控综合'}
      </button>
    </div>
  )
}

export default function SeminarDetail() {
  const { id: seminarId } = useParams<{ id: string }>()
  const { data: detail, loading, error, reload } = useApi(
    () => seminarApi.getDetail(seminarId ?? ''),
    seminarId,
  )
  const [dataVersion, setDataVersion] = useState(0)
  const [allowPartial, setAllowPartial] = useState(false)
  const [deterministicFallback, setDeterministicFallback] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionResult, setActionResult] = useState<string | null>(null)
  const [acting, setActing] = useState<string | null>(null)
  const [brief, setBrief] = useState<ChairBriefRead | null>(null)

  if (!seminarId) {
    return (
      <div className="space-y-6">
        <CockpitNav />
        <EmptyState title="未指定研讨" description="请从研讨列表打开一个研讨。" />
      </div>
    )
  }

  async function runAction(kind: 'advance' | 'finalize' | 'synthesize') {
    if (!seminarId) return
    setActionError(null)
    setActionResult(null)
    setActing(kind)
    try {
      if (kind === 'advance') {
        const result = await seminarApi.advance(seminarId)
        setActionResult(
          `第 ${result.wave_no} 波完成，状态 ${result.status}：` +
            result.per_model
              .map((row) => `${row.model_id} 第${row.round_no}轮 ${row.status}`)
              .join('；'),
        )
      } else if (kind === 'finalize') {
        const result = await seminarApi.finalize(seminarId)
        setActionResult(
          `定稿完成，状态 ${result.status}：` +
            result.finals.map((row) => `${row.model_id} ${row.status}`).join('；'),
        )
      } else {
        const result = await seminarApi.synthesize(seminarId, {
          allow_partial: allowPartial,
          deterministic_fallback: deterministicFallback,
        })
        if (isChairBrief(result)) {
          setBrief(result)
          setActionResult(
            `已产出主控简报 v${result.brief_version}（${result.finals_used}/${result.roster_size} 个终裁，${result.prepass.item_count} 个主张项）；未写报告行，研讨仍在 ${result.status}。简报见下方「主控简报」一节。`,
          )
        } else {
          setActionResult(
            `已写入报告 v${result.version}（${result.production_path} / ${result.cluster_production} · ${result.partial ? '部分报告' : '完整报告'} · 一致程度 ${result.agreement_level ?? '无'}）。`,
          )
        }
      }
      setDataVersion((version) => version + 1)
      reload()
    } catch (e: unknown) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setActing(null)
    }
  }

  const isAgentMode = detail?.config.chair_mode === 'agent'

  return (
    <div className="space-y-6">
      <CockpitNav />
      <div>
        <Link className="text-sm text-blue-300 underline" to="/cockpit/seminars">
          ← 返回研讨列表
        </Link>
        <h2 className="mt-1 text-2xl font-bold text-slate-100">
          {detail ? detail.topic : '研讨详情'}
        </h2>
        <p className="mt-1 font-mono text-xs text-slate-500">{seminarId}</p>
      </div>

      {loading && <LoadingSpinner />}
      {error && <ErrorBanner message={error} onRetry={reload} />}

      {detail && (
        <>
          <Card>
            <CardHeader title="推进（显式按钮，无自动进行）" />
            <CardBody className="space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  className={BUTTON_CLASS}
                  onClick={() => void runAction('advance')}
                  disabled={acting !== null}
                >
                  {acting === 'advance' ? '推进中…' : '推进一波'}
                </button>
                <button
                  type="button"
                  className={BUTTON_CLASS}
                  onClick={() => void runAction('finalize')}
                  disabled={acting !== null}
                >
                  {acting === 'finalize' ? '定稿中…' : '定稿（终裁）'}
                </button>
                <button
                  type="button"
                  className={BUTTON_CLASS}
                  onClick={() => void runAction('synthesize')}
                  disabled={acting !== null}
                >
                  {acting === 'synthesize'
                    ? '合成中…'
                    : isAgentMode
                      ? '合成（产出主控简报）'
                      : '合成报告'}
                </button>
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  <input
                    type="checkbox"
                    checked={allowPartial}
                    onChange={(event) => setAllowPartial(event.target.checked)}
                  />
                  allow_partial（1 个终裁也可合成；0 个终裁恒拒绝）
                </label>
                <label className="flex items-center gap-2 text-xs text-slate-400">
                  <input
                    type="checkbox"
                    checked={deterministicFallback}
                    onChange={(event) => setDeterministicFallback(event.target.checked)}
                  />
                  deterministic_fallback（跳过主控阶段，写确定性报告
                  {isAgentMode ? '，不产简报' : ''}）
                </label>
                <span className="text-xs text-slate-400">
                  主控模式：{isAgentMode ? 'agent（Glint）' : 'model'}
                </span>
              </div>
              {actionError && <ErrorBanner message={actionError} />}
              {actionResult && (
                <p className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-200">
                  {actionResult}
                </p>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="概览：名册 · 预算 · 诊断" />
            <CardBody className="space-y-5">
              <RosterProgressTable detail={detail} />
              <div>
                <h4 className="mb-2 text-sm font-semibold text-slate-200">预算（审计账本为准）</h4>
                <BudgetsPanel budgets={detail.budgets} />
              </div>
              <div>
                <h4 className="mb-2 text-sm font-semibold text-slate-200">诊断汇总</h4>
                <DiagnosisPanel diagnosis={detail.diagnosis} />
              </div>
            </CardBody>
          </Card>

          {isAgentMode && (
            <Card>
              <CardHeader title="主控简报与提交" />
              <CardBody>
                {brief ? (
                  <div className="space-y-6">
                    <ChairBriefView brief={brief} />
                    <ChairSubmissionForm
                      key={`${seminarId}:${brief.brief_version}`}
                      seminarId={seminarId}
                      brief={brief}
                      onSubmitted={() => {
                        setDataVersion((version) => version + 1)
                        reload()
                      }}
                    />
                  </div>
                ) : (
                  <EmptyState
                    title="还没有主控简报"
                    description="点「合成（产出主控简报）」：系统会把预处理聚类、分歧、计算指标与终裁原文存为一版简报（不写报告行），简报会在这里出现，之后用下方表单提交主控综合。后端没有按版本读取简报的端点——简报只在合成当次返回，刷新页面后需重新合成一版。"
                  />
                )}
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader title="报告（版本化，只追加不覆盖）" />
            <CardBody>
              <ReportsSection seminarId={seminarId} detail={detail} refreshKey={dataVersion} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Board 时间线（引述，非指令）" />
            <CardBody>
              <BoardSection seminarId={seminarId} refreshKey={dataVersion} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="轮次对比（按模型）" />
            <CardBody>
              <RoundsSection seminarId={seminarId} refreshKey={dataVersion} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="终裁（逐字）" />
            <CardBody>
              <FinalsSection seminarId={seminarId} refreshKey={dataVersion} />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="审计日志（追加式，seq 顺序）" />
            <CardBody>
              <AuditSection seminarId={seminarId} refreshKey={dataVersion} />
            </CardBody>
          </Card>
        </>
      )}
    </div>
  )
}
