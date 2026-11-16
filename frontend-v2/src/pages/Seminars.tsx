// Seminar list + creation page (Sprint 20): pick a completed run,
// list its seminars, and create a new one. Creation freezes the case
// snapshot (the backend refuses non-COMPLETED runs, rosters under
// two models, and unconfigured chair endpoints before writing any
// row); the form mirrors the backend request shape exactly, and
// endpoint configuration carries environment-variable NAMES only —
// keys never appear in a request body, a stored row, or a log line.

import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { simulationApi } from '../api/endpoints'
import { seminarApi } from '../api/engine'
import type {
  SeminarCreateRead,
  SeminarCreateRequest,
  SeminarEndpointConfig,
  SeminarModelPortConfigInput,
  SeminarPipeline,
  SeminarRosterEntryInput,
} from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import { RunPicker } from '../components/cockpit/RunPicker'
import type { CockpitRun } from '../components/cockpit/RunPicker'
import { SEMINAR_TARGET_NAMES } from '../components/cockpit/seminarUtils'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { StatusBadge } from '../components/ui/StatusBadge'
import { useApi } from '../hooks/useApi'

const INPUT_CLASS =
  'rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 focus:border-blue-500/50 focus:outline-none'
const BUTTON_CLASS =
  'rounded-full border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-medium text-blue-300 transition hover:bg-blue-500/20 disabled:opacity-50'

const MODES: Record<SeminarPipeline, string[]> = {
  strategy_team: ['standard', 'deep'],
  advisory_board: ['quick', 'standard'],
}

interface EndpointDraft {
  form: 'target' | 'inline'
  target: string
  baseUrlEnv: string
  apiKeyEnv: string
  model: string
}

function defaultEndpoint(): EndpointDraft {
  return { form: 'target', target: 'primary', baseUrlEnv: '', apiKeyEnv: '', model: '' }
}

function endpointPayload(draft: EndpointDraft): SeminarEndpointConfig {
  if (draft.form === 'target') return { target: draft.target }
  return {
    base_url_env: draft.baseUrlEnv.trim() || null,
    api_key_env: draft.apiKeyEnv.trim() || null,
    model: draft.model.trim() || null,
  }
}

function EndpointForm({
  draft,
  onChange,
  label,
}: {
  draft: EndpointDraft
  onChange: (next: EndpointDraft) => void
  label: string
}) {
  return (
    <div className="space-y-2 rounded-lg border border-slate-700/50 bg-slate-800/20 p-3">
      <p className="text-xs text-slate-400">
        {label}端点（只填环境变量名，绝不填 key 本身）
      </p>
      <div className="flex gap-3 text-xs text-slate-300">
        <label className="flex items-center gap-1">
          <input
            type="radio"
            checked={draft.form === 'target'}
            onChange={() => onChange({ ...draft, form: 'target' })}
          />
          已配置 target
        </label>
        <label className="flex items-center gap-1">
          <input
            type="radio"
            checked={draft.form === 'inline'}
            onChange={() => onChange({ ...draft, form: 'inline' })}
          />
          内联端点
        </label>
      </div>
      {draft.form === 'target' ? (
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          target
          <select
            aria-label={`${label} target`}
            className={INPUT_CLASS}
            value={draft.target}
            onChange={(event) => onChange({ ...draft, target: event.target.value })}
          >
            {SEMINAR_TARGET_NAMES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <div className="flex flex-wrap gap-3">
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            base_url_env（变量名）
            <input
              aria-label={`${label} base_url_env`}
              className={INPUT_CLASS}
              value={draft.baseUrlEnv}
              onChange={(event) => onChange({ ...draft, baseUrlEnv: event.target.value })}
              placeholder="MY_BASE_URL_ENV"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            api_key_env（变量名）
            <input
              aria-label={`${label} api_key_env`}
              className={INPUT_CLASS}
              value={draft.apiKeyEnv}
              onChange={(event) => onChange({ ...draft, apiKeyEnv: event.target.value })}
              placeholder="MY_API_KEY_ENV"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            model
            <input
              aria-label={`${label} model`}
              className={INPUT_CLASS}
              value={draft.model}
              onChange={(event) => onChange({ ...draft, model: event.target.value })}
              placeholder="gpt-6.1-sol"
            />
          </label>
        </div>
      )}
    </div>
  )
}

interface RosterRowDraft {
  key: number
  modelId: string
  endpoint: EndpointDraft
  temperature: string
  timeoutSeconds: string
  maxRounds: string
}

let rosterKeyCounter = 0

function defaultRosterRow(modelId: string): RosterRowDraft {
  rosterKeyCounter += 1
  return {
    key: rosterKeyCounter,
    modelId,
    endpoint: defaultEndpoint(),
    temperature: '0.3',
    timeoutSeconds: '180',
    maxRounds: '',
  }
}

function CreateSeminarForm({
  runId,
  onCreated,
}: {
  runId: string
  onCreated: () => void
}) {
  const [topic, setTopic] = useState('')
  const [decisionQuestion, setDecisionQuestion] = useState('')
  const [optionsText, setOptionsText] = useState('')
  const [pipeline, setPipeline] = useState<SeminarPipeline>('strategy_team')
  const [mode, setMode] = useState('standard')
  const [maxRounds, setMaxRounds] = useState('3')
  const [quietRounds, setQuietRounds] = useState('2')
  const [maxConcurrency, setMaxConcurrency] = useState('3')
  const [outputLanguage, setOutputLanguage] = useState('English')
  const [includePremortem, setIncludePremortem] = useState(true)
  const [failureDate, setFailureDate] = useState('one year from now')
  const [contextLines, setContextLines] = useState('')
  const [chairMode, setChairMode] = useState<'model' | 'agent'>('model')
  const [maxStageCalls, setMaxStageCalls] = useState('200')
  const [maxTokens, setMaxTokens] = useState('1000000')
  const [maxRetries, setMaxRetries] = useState('2')
  const [retryBackoff, setRetryBackoff] = useState('1')
  const [nearDupThreshold, setNearDupThreshold] = useState('0.8')
  const [roster, setRoster] = useState<RosterRowDraft[]>([
    defaultRosterRow('model-a'),
    defaultRosterRow('model-b'),
  ])
  const [chairModelId, setChairModelId] = useState('chair')
  const [chairEndpoint, setChairEndpoint] = useState<EndpointDraft>(defaultEndpoint())
  const [chairTemperature, setChairTemperature] = useState('0.3')
  const [chairTimeout, setChairTimeout] = useState('180')
  const [creating, setCreating] = useState(false)
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<SeminarCreateRead | null>(null)

  function changePipeline(next: SeminarPipeline) {
    setPipeline(next)
    setMode(MODES[next][0])
  }

  function validate(): string[] {
    const found: string[] = []
    if (topic.trim() === '') found.push('主题不能为空。')
    const ids = roster.map((row) => row.modelId.trim()).filter((id) => id !== '')
    if (ids.length < 2) found.push('名册至少需要 2 个模型（每个模型 id 不能为空）。')
    if (new Set(ids).size !== ids.length) found.push('名册模型 id 不能重复。')
    for (const row of roster) {
      if (row.endpoint.form === 'inline') {
        if (row.endpoint.apiKeyEnv.trim() === '' || row.endpoint.model.trim() === '') {
          found.push(`模型 ${row.modelId || '（未命名）'} 的内联端点需要 api_key_env 与 model。`)
        }
      }
      if (Number.isNaN(Number(row.temperature))) found.push(`模型 ${row.modelId} 的温度不是数字。`)
      if (Number.isNaN(Number(row.timeoutSeconds))) {
        found.push(`模型 ${row.modelId} 的超时不是数字。`)
      }
    }
    if (chairMode === 'model' && chairModelId.trim() === '') {
      found.push('主控模型 id 不能为空。')
    }
    for (const [label, value] of [
      ['最多轮次', maxRounds],
      ['quiet 轮次', quietRounds],
      ['最大并发', maxConcurrency],
      ['调用预算', maxStageCalls],
      ['Token 预算', maxTokens],
      ['重试上限', maxRetries],
      ['重试退避', retryBackoff],
      ['近似重复阈值', nearDupThreshold],
    ]) {
      if (Number.isNaN(Number(value)) || value.trim() === '') found.push(`${label}不是数字。`)
    }
    return found
  }

  async function handleCreate() {
    setError(null)
    setCreated(null)
    const found = validate()
    setProblems(found)
    if (found.length > 0) return
    const rosterPayload: SeminarRosterEntryInput[] = roster.map((row) => ({
      model_id: row.modelId.trim(),
      endpoint: endpointPayload(row.endpoint),
      temperature: Number(row.temperature),
      timeout_seconds: Number(row.timeoutSeconds),
      max_rounds: row.maxRounds.trim() === '' ? null : Number(row.maxRounds),
    }))
    // Agent mode: the stored chair_model is kept for shape stability
    // only and never called; the form still sends one (the backend
    // requires the field), defaulting the id to glint-agent.
    const chairPayload: SeminarModelPortConfigInput =
      chairMode === 'agent'
        ? {
            model_id: 'glint-agent',
            endpoint: { target: 'primary' },
            temperature: 0.3,
            timeout_seconds: 180,
          }
        : {
            model_id: chairModelId.trim(),
            endpoint: endpointPayload(chairEndpoint),
            temperature: Number(chairTemperature),
            timeout_seconds: Number(chairTimeout),
          }
    const payload: SeminarCreateRequest = {
      topic: topic.trim(),
      decision_question: decisionQuestion.trim(),
      options: optionsText
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== ''),
      roster: rosterPayload,
      pipeline,
      mode,
      max_rounds: Number(maxRounds),
      quiet_rounds: Number(quietRounds),
      max_concurrency: Number(maxConcurrency),
      output_language: outputLanguage.trim() || 'English',
      include_premortem: includePremortem,
      failure_date: failureDate,
      chair_model: chairPayload,
      context_lines: contextLines
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== ''),
      chair_mode: chairMode,
      max_stage_calls: Number(maxStageCalls),
      max_tokens: Number(maxTokens),
      max_retries: Number(maxRetries),
      retry_backoff_seconds: Number(retryBackoff),
      near_duplicate_threshold: Number(nearDupThreshold),
    }
    setCreating(true)
    try {
      const result = await seminarApi.createSeminar(runId, payload)
      setCreated(result)
      onCreated()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-64 flex-1 flex-col gap-1 text-xs text-slate-400">
          主题（必填）
          <input
            aria-label="主题"
            className={INPUT_CLASS}
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="本次研讨要回答的决策问题"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          管线
          <select
            aria-label="管线"
            className={INPUT_CLASS}
            value={pipeline}
            onChange={(event) => changePipeline(event.target.value as SeminarPipeline)}
          >
            <option value="strategy_team">strategy_team（麦肯锡团队）</option>
            <option value="advisory_board">advisory_board（顾问团）</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          模式
          <select
            aria-label="模式"
            className={INPUT_CLASS}
            value={mode}
            onChange={(event) => setMode(event.target.value)}
          >
            {MODES[pipeline].map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          主控模式
          <select
            aria-label="主控模式"
            className={INPUT_CLASS}
            value={chairMode}
            onChange={(event) => setChairMode(event.target.value as 'model' | 'agent')}
          >
            <option value="model">model（模型主控）</option>
            <option value="agent">agent（Glint 主控）</option>
          </select>
        </label>
      </div>

      <label className="flex flex-col gap-1 text-xs text-slate-400">
        决策问题
        <input
          aria-label="决策问题"
          className={INPUT_CLASS}
          value={decisionQuestion}
          onChange={(event) => setDecisionQuestion(event.target.value)}
        />
      </label>

      <div className="flex flex-wrap gap-3">
        <label className="flex flex-1 flex-col gap-1 text-xs text-slate-400">
          备选方案（每行一个）
          <textarea
            aria-label="备选方案"
            className={`${INPUT_CLASS} min-h-16`}
            value={optionsText}
            onChange={(event) => setOptionsText(event.target.value)}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1 text-xs text-slate-400">
          上下文行（每行一条，写入快照）
          <textarea
            aria-label="上下文行"
            className={`${INPUT_CLASS} min-h-16`}
            value={contextLines}
            onChange={(event) => setContextLines(event.target.value)}
          />
        </label>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        {(
          [
            ['最多轮次', maxRounds, setMaxRounds],
            ['quiet 轮次', quietRounds, setQuietRounds],
            ['最大并发', maxConcurrency, setMaxConcurrency],
            ['输出语言', outputLanguage, setOutputLanguage],
            ['失败日期', failureDate, setFailureDate],
            ['调用预算', maxStageCalls, setMaxStageCalls],
            ['Token 预算', maxTokens, setMaxTokens],
            ['重试上限', maxRetries, setMaxRetries],
            ['重试退避（秒）', retryBackoff, setRetryBackoff],
            ['近似重复阈值', nearDupThreshold, setNearDupThreshold],
          ] as const
        ).map(([label, value, setter]) => (
          <label key={label} className="flex flex-col gap-1 text-xs text-slate-400">
            {label}
            <input
              aria-label={label}
              className={INPUT_CLASS}
              value={value}
              onChange={(event) => setter(event.target.value)}
            />
          </label>
        ))}
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={includePremortem}
            onChange={(event) => setIncludePremortem(event.target.checked)}
          />
          包含事前验尸
        </label>
      </div>

      <div className="space-y-3">
        <h4 className="text-sm font-medium text-slate-200">名册（至少 2 个模型）</h4>
        {roster.map((row, index) => (
          <div key={row.key} className="space-y-2 rounded-lg border border-slate-700/50 p-3">
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                模型 id
                <input
                  aria-label={`模型 ${index + 1} id`}
                  className={INPUT_CLASS}
                  value={row.modelId}
                  onChange={(event) =>
                    setRoster((prev) =>
                      prev.map((item) =>
                        item.key === row.key ? { ...item, modelId: event.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                温度
                <input
                  aria-label={`模型 ${index + 1} 温度`}
                  className={INPUT_CLASS}
                  value={row.temperature}
                  onChange={(event) =>
                    setRoster((prev) =>
                      prev.map((item) =>
                        item.key === row.key ? { ...item, temperature: event.target.value } : item,
                      ),
                    )
                  }
                  inputMode="decimal"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                超时（秒）
                <input
                  aria-label={`模型 ${index + 1} 超时`}
                  className={INPUT_CLASS}
                  value={row.timeoutSeconds}
                  onChange={(event) =>
                    setRoster((prev) =>
                      prev.map((item) =>
                        item.key === row.key
                          ? { ...item, timeoutSeconds: event.target.value }
                          : item,
                      ),
                    )
                  }
                  inputMode="decimal"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-slate-400">
                最多轮次（留空 = 研讨默认值）
                <input
                  aria-label={`模型 ${index + 1} 最多轮次`}
                  className={INPUT_CLASS}
                  value={row.maxRounds}
                  onChange={(event) =>
                    setRoster((prev) =>
                      prev.map((item) =>
                        item.key === row.key ? { ...item, maxRounds: event.target.value } : item,
                      ),
                    )
                  }
                  inputMode="numeric"
                />
              </label>
              <button
                type="button"
                className="rounded-full border border-slate-600/50 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800/50 disabled:opacity-50"
                onClick={() =>
                  setRoster((prev) => prev.filter((item) => item.key !== row.key))
                }
                disabled={roster.length <= 1}
              >
                移除
              </button>
            </div>
            <EndpointForm
              draft={row.endpoint}
              onChange={(next) =>
                setRoster((prev) =>
                  prev.map((item) => (item.key === row.key ? { ...item, endpoint: next } : item)),
                )
              }
              label={`模型 ${index + 1}`}
            />
          </div>
        ))}
        <button
          type="button"
          className="rounded-full border border-slate-600/50 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800/50"
          onClick={() => setRoster((prev) => [...prev, defaultRosterRow(`model-${prev.length + 1}`)])}
        >
          + 添加模型
        </button>
      </div>

      {chairMode === 'model' ? (
        <div className="space-y-2">
          <h4 className="text-sm font-medium text-slate-200">主控模型</h4>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              主控模型 id（与名册 id 相同即主控同时参会）
              <input
                aria-label="主控模型 id"
                className={INPUT_CLASS}
                value={chairModelId}
                onChange={(event) => setChairModelId(event.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              温度
              <input
                aria-label="主控温度"
                className={INPUT_CLASS}
                value={chairTemperature}
                onChange={(event) => setChairTemperature(event.target.value)}
                inputMode="decimal"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              超时（秒）
              <input
                aria-label="主控超时"
                className={INPUT_CLASS}
                value={chairTimeout}
                onChange={(event) => setChairTimeout(event.target.value)}
                inputMode="decimal"
              />
            </label>
          </div>
          <EndpointForm draft={chairEndpoint} onChange={setChairEndpoint} label="主控" />
        </div>
      ) : (
        <p className="text-xs text-slate-400">
          agent 主控模式：合成时不调用模型主控，系统产出主控简报，由 Glint 提交聚类与综合（主控模型配置仅为形状保留，存为
          glint-agent，永不调用）。
        </p>
      )}

      {problems.length > 0 && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3">
          <ul className="list-disc space-y-1 pl-5 text-sm text-amber-200">
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}
      {error && <ErrorBanner message={error} />}
      {created && (
        <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-200">
          研讨已创建：{created.seminar_id}（快照 {created.case_snapshot_hash.slice(0, 18)}…）。{' '}
          <Link className="underline" to={`/cockpit/seminars/${created.seminar_id}`}>
            打开研讨详情
          </Link>
        </div>
      )}

      <button
        type="button"
        className={BUTTON_CLASS}
        onClick={() => void handleCreate()}
        disabled={creating}
      >
        {creating ? '创建中…' : '创建研讨（冻结案例快照）'}
      </button>
    </div>
  )
}

function SeminarListSection({ runId }: { runId: string }) {
  const { data, loading, error, reload } = useApi(() => seminarApi.listRunSeminars(runId), runId)
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  if (!data || data.length === 0) {
    return (
      <EmptyState
        title="该 Run 还没有研讨"
        description="用上方表单创建一个研讨：创建时会冻结该 Run 的案例快照，之后追加的 Run 产物不会进入研讨。"
      />
    )
  }
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-slate-700/50 text-xs text-slate-400">
          <th className="py-2 pr-3 font-medium">主题</th>
          <th className="py-2 pr-3 font-medium">状态</th>
          <th className="py-2 pr-3 font-medium">名册</th>
          <th className="py-2 pr-3 font-medium">终裁</th>
          <th className="py-2 pr-3 font-medium">报告版本</th>
          <th className="py-2 font-medium">研讨 id</th>
        </tr>
      </thead>
      <tbody>
        {data.map((seminar) => (
          <tr key={seminar.seminar_id} className="border-b border-slate-800/60">
            <td className="py-2 pr-3">
              <Link
                className="text-blue-300 underline"
                to={`/cockpit/seminars/${seminar.seminar_id}`}
              >
                {seminar.topic}
              </Link>
            </td>
            <td className="py-2 pr-3">
              <StatusBadge status={seminar.status} />
            </td>
            <td className="py-2 pr-3 text-slate-300">{seminar.roster_size}</td>
            <td className="py-2 pr-3 text-slate-300">{seminar.finals_count}</td>
            <td className="py-2 pr-3 text-slate-300">{seminar.report_versions}</td>
            <td className="py-2 font-mono text-xs text-slate-500">{seminar.seminar_id}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function Seminars() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: runs, loading, error, reload } = useApi(() => simulationApi.listRuns())
  const [selectedRunId, setSelectedRunId] = useState<string | null>(searchParams.get('run'))
  const [listVersion, setListVersion] = useState(0)

  function selectRun(runId: string) {
    setSelectedRunId(runId)
    setSearchParams({ run: runId })
  }

  return (
    <div className="space-y-6">
      <CockpitNav />
      <div>
        <h2 className="text-2xl font-bold text-slate-100">多模型研讨</h2>
        <p className="mt-1 text-sm text-slate-400">
          多个模型围绕一份冻结的案例快照异步研讨：每轮分析 + 反思、board 上交换摘要、终裁后由主控聚类去重并汇总成报告。所有推进都是显式按钮，没有后台自动进行。
        </p>
      </div>

      {loading && <LoadingSpinner />}
      {error && <ErrorBanner message={error} onRetry={reload} />}
      {runs && (
        <RunPicker
          runs={runs as CockpitRun[]}
          selectedId={selectedRunId}
          onSelect={selectRun}
          label="选择模拟 Run"
        />
      )}

      {!selectedRunId && (
        <EmptyState title="请选择一个 Run" description="研讨建立在已完成的 Run 之上；创建时会冻结该 Run 的案例快照。" />
      )}

      {selectedRunId && (
        <Card>
          <CardHeader title="该 Run 的研讨" />
          <CardBody>
            <SeminarListSection key={`${selectedRunId}:${listVersion}`} runId={selectedRunId} />
          </CardBody>
        </Card>
      )}

      {selectedRunId && (
        <Card>
          <CardHeader title="创建研讨" />
          <CardBody>
            <CreateSeminarForm
              runId={selectedRunId}
              onCreated={() => setListVersion((version) => version + 1)}
            />
          </CardBody>
        </Card>
      )}
    </div>
  )
}
