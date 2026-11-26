import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ChevronDown, ChevronRight, Play } from 'lucide-react'

import { simulationApi } from '../api/endpoints'
import { nullOn404, skillsApi } from '../api/engine'
import type { SkillDeliberationRecord } from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import { DeliberationRecordView } from '../components/cockpit/DeliberationResults'
import { LlmStatusBanner } from '../components/cockpit/LlmStatusBanner'
import { RunPicker } from '../components/cockpit/RunPicker'
import type { CockpitRun } from '../components/cockpit/RunPicker'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { modeLabel, statusLabel } from '../components/ui/dataSurfaceUtils'
import { useApi } from '../hooks/useApi'

// 事前验尸失败日期：界面显示中文，提交仍传后端提示词里的英文相对日期。
const FAILURE_DATE_DISPLAY = '一年后'
const FAILURE_DATE_SUBMIT = 'one year from now'

function splitLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function inputClassName() {
  return 'w-full rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none'
}

type Pipeline = 'strategy_team' | 'advisory_board'

export default function Deliberation() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: runs, loading, error, reload } = useApi(() => simulationApi.listRuns())
  const [selectedRunId, setSelectedRunId] = useState<string | null>(searchParams.get('run'))

  const [pipeline, setPipeline] = useState<Pipeline>('strategy_team')
  const [topic, setTopic] = useState('')
  const [decisionQuestion, setDecisionQuestion] = useState('')
  const [optionsText, setOptionsText] = useState('')
  const [contextText, setContextText] = useState('')
  const [strategyMode, setStrategyMode] = useState<'standard' | 'deep'>('standard')
  const [advisoryMode, setAdvisoryMode] = useState<'quick' | 'standard'>('standard')
  const [outputLanguage, setOutputLanguage] = useState('中文')
  const [includePremortem, setIncludePremortem] = useState(true)
  const [failureDate, setFailureDate] = useState(FAILURE_DATE_DISPLAY)

  const [launching, setLaunching] = useState(false)
  const [launchError, setLaunchError] = useState<unknown>(null)
  const [latestRecord, setLatestRecord] = useState<SkillDeliberationRecord | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const {
    data: history,
    loading: historyLoading,
    error: historyError,
    reload: reloadHistory,
  } = useApi(
    () =>
      selectedRunId
        ? nullOn404(skillsApi.listDeliberations(selectedRunId))
        : Promise.resolve(null),
    selectedRunId,
  )

  function selectRun(runId: string) {
    setSelectedRunId(runId)
    setLatestRecord(null)
    setLaunchError(null)
    setExpandedId(null)
    setSearchParams({ run: runId })
  }

  async function launch() {
    if (!selectedRunId) return
    setLaunching(true)
    setLaunchError(null)
    try {
      const record =
        pipeline === 'strategy_team'
          ? await skillsApi.runStrategyTeam(selectedRunId, {
              topic: topic.trim(),
              decision_question: decisionQuestion.trim(),
              context_lines: splitLines(contextText),
              mode: strategyMode,
              output_language: outputLanguage.trim() || '中文',
              include_premortem: includePremortem,
              failure_date: failureDate.trim() === FAILURE_DATE_DISPLAY ? FAILURE_DATE_SUBMIT : failureDate.trim() || FAILURE_DATE_SUBMIT,
            })
          : await skillsApi.runAdvisoryBoard(selectedRunId, {
              decision: topic.trim(),
              options: splitLines(optionsText),
              context_lines: splitLines(contextText),
              mode: advisoryMode,
              output_language: outputLanguage.trim() || '中文',
            })
      setLatestRecord(record)
      setExpandedId(record.id)
      reloadHistory()
    } catch (caught) {
      setLaunchError(caught)
    } finally {
      setLaunching(false)
    }
  }

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />

  const runList = (runs || []) as CockpitRun[]
  const selectedRun = runList.find((run) => run.id === selectedRunId) ?? null
  const runCompleted = selectedRun?.status === 'COMPLETED'
  const deliberations = [...(history?.deliberations ?? [])].reverse()

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">商议</h1>
        <p className="mt-1 text-sm text-slate-500">
          在已完成的推演上启动策略团队或顾问团商议；结果读自该推演已存储的数值工件
        </p>
      </div>

      <CockpitNav />

      <RunPicker runs={runList} selectedId={selectedRunId} onSelect={selectRun} />

      {selectedRun && !runCompleted && (
        <div role="note" className="rounded-[20px] border border-amber-500/20 bg-amber-500/5 px-4 py-3">
          <p className="text-sm text-amber-300">
            该推演尚未完成（状态 {statusLabel(selectedRun.status)}）：商议只能在已完成的推演上启动。历史记录仍可查看。
          </p>
        </div>
      )}

      {launchError ? <LlmStatusBanner error={launchError} /> : null}

      <Card>
        <CardHeader title="启动商议" />
        <CardBody className="space-y-4">
          <div className="flex flex-wrap gap-2" role="group" aria-label="管线">
            <button
              onClick={() => setPipeline('strategy_team')}
              className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
                pipeline === 'strategy_team'
                  ? 'border-blue-500/30 bg-blue-500/10 font-medium text-blue-300'
                  : 'border-slate-700/50 bg-slate-800/30 text-slate-400 hover:bg-slate-800/50'
              }`}
            >
              策略团队（麦肯锡管线）
            </button>
            <button
              onClick={() => setPipeline('advisory_board')}
              className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
                pipeline === 'advisory_board'
                  ? 'border-blue-500/30 bg-blue-500/10 font-medium text-blue-300'
                  : 'border-slate-700/50 bg-slate-800/30 text-slate-400 hover:bg-slate-800/50'
              }`}
            >
              顾问团（5 人）
            </button>
          </div>

          <div>
            <label htmlFor="delib-topic" className="mb-1.5 block text-xs text-slate-500">
              {pipeline === 'strategy_team' ? '决策主题' : '决策'}
            </label>
            <input
              id="delib-topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="例如：我们是否应该推出 AI 客服产品线？"
              className={inputClassName()}
            />
          </div>

          {pipeline === 'strategy_team' ? (
            <>
              <div>
                <label htmlFor="delib-question" className="mb-1.5 block text-xs text-slate-500">
                  决策问题（可选）
                </label>
                <input
                  id="delib-question"
                  value={decisionQuestion}
                  onChange={(event) => setDecisionQuestion(event.target.value)}
                  className={inputClassName()}
                />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <label htmlFor="delib-strategy-mode" className="mb-1.5 block text-xs text-slate-500">
                    模式
                  </label>
                  <select
                    id="delib-strategy-mode"
                    value={strategyMode}
                    onChange={(event) => setStrategyMode(event.target.value as 'standard' | 'deep')}
                    className={inputClassName()}
                  >
                    <option value="standard">标准（11 个阶段）</option>
                    <option value="deep">深度（17 个阶段，含对决评判与兵棋推演循环）</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="delib-failure-date" className="mb-1.5 block text-xs text-slate-500">
                    事前验尸的失败日期
                  </label>
                  <input
                    id="delib-failure-date"
                    value={failureDate}
                    onChange={(event) => setFailureDate(event.target.value)}
                    className={inputClassName()}
                  />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={includePremortem}
                  onChange={(event) => setIncludePremortem(event.target.checked)}
                />
                包含事前验尸视角（第四个验证视角）
              </label>
            </>
          ) : (
            <>
              <div>
                <label htmlFor="delib-options" className="mb-1.5 block text-xs text-slate-500">
                  候选选项（每行一个，可留空）
                </label>
                <textarea
                  id="delib-options"
                  value={optionsText}
                  onChange={(event) => setOptionsText(event.target.value)}
                  placeholder={'分阶段上线\n全面上线\n合作方主导'}
                  rows={3}
                  className={inputClassName()}
                />
              </div>
              <div>
                <label htmlFor="delib-advisory-mode" className="mb-1.5 block text-xs text-slate-500">
                  模式
                </label>
                <select
                  id="delib-advisory-mode"
                  value={advisoryMode}
                  onChange={(event) => setAdvisoryMode(event.target.value as 'quick' | 'standard')}
                  className={inputClassName()}
                >
                  <option value="standard">标准（13 个阶段，含强制辩论与修订）</option>
                  <option value="quick">快速（7 个阶段，无强制辩论）</option>
                </select>
              </div>
            </>
          )}

          <div>
            <label htmlFor="delib-context" className="mb-1.5 block text-xs text-slate-500">
              补充上下文（每行一条；数值上下文自动取自该 Run 的工件）
            </label>
            <textarea
              id="delib-context"
              value={contextText}
              onChange={(event) => setContextText(event.target.value)}
              rows={3}
              className={inputClassName()}
            />
          </div>

          <div>
            <label htmlFor="delib-language" className="mb-1.5 block text-xs text-slate-500">
              输出语言
            </label>
            <input
              id="delib-language"
              value={outputLanguage}
              onChange={(event) => setOutputLanguage(event.target.value)}
              className={inputClassName()}
            />
          </div>

          <button
            onClick={() => void launch()}
            disabled={launching || !selectedRun || !runCompleted || topic.trim().length === 0}
            className="flex items-center gap-2 rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-600 disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            {launching ? '运行中…（深度模式最多 17 次 LLM 调用）' : '启动商议'}
          </button>
          {!selectedRun && <p className="text-xs text-slate-500">请先选择一个推演。</p>}
        </CardBody>
      </Card>

      {latestRecord && (
        <Card>
          <CardHeader title="最新结果" />
          <CardBody>
            <DeliberationRecordView record={latestRecord} />
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="历史记录（只追加，最新在前）" />
        {historyLoading && <LoadingSpinner />}
        {historyError && !historyLoading && <ErrorBanner message={historyError} onRetry={reloadHistory} />}
        {!historyLoading && !historyError && selectedRun && deliberations.length === 0 && (
          <EmptyState icon="💬" title="暂无商议记录" description="启动一次商议，结果会追加到这里" />
        )}
        {!historyLoading && !historyError && !selectedRun && (
          <EmptyState icon="💬" title="请选择一个推演" description="历史记录按推演存储" />
        )}
        {!historyLoading && !historyError && deliberations.length > 0 && (
          <div className="divide-y divide-slate-800/60">
            {deliberations.map((record) => (
              <div key={record.id}>
                <button
                  onClick={() => setExpandedId(expandedId === record.id ? null : record.id)}
                  className="flex w-full items-center justify-between px-6 py-4 text-left transition-colors hover:bg-slate-800/30"
                >
                  <div className="flex items-center gap-3">
                    <span className="rounded-full border border-slate-700/60 bg-slate-800/40 px-2 py-0.5 text-[11px] text-slate-300">
                      {record.pipeline === 'strategy_team' ? '策略团队' : '顾问团'}
                    </span>
                    <span className="text-sm text-slate-300">
                      {modeLabel(record.mode)} · {record.created_at}
                    </span>
                  </div>
                  {expandedId === record.id ? (
                    <ChevronDown className="h-4 w-4 text-slate-500" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-slate-500" />
                  )}
                </button>
                {expandedId === record.id && (
                  <div className="border-t border-slate-800/40 px-6 py-5">
                    <DeliberationRecordView record={record} />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
