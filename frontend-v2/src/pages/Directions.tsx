import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { simulationApi } from '../api/endpoints'
import { meceApi, narrativesApi, nullOn404, parseApiError } from '../api/engine'
import type {
  DecisionNarrativeRead,
  DecompositionTree,
  NarrativeDirectionDefinition,
} from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import { NarrativeView } from '../components/cockpit/DirectionViews'
import { RunPicker } from '../components/cockpit/RunPicker'
import type { CockpitRun } from '../components/cockpit/RunPicker'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useApi } from '../hooks/useApi'

function inputClassName() {
  return 'w-full rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none'
}

function collectBranchNames(tree: DecompositionTree): string[] {
  const names: string[] = []
  const walk = (branch: DecompositionTree['root']) => {
    if (!names.includes(branch.name)) names.push(branch.name)
    branch.children.forEach(walk)
  }
  walk(tree.root)
  return names
}

interface DirectionDraft {
  name: string
  sourceRunId: string
  arm: 'baseline' | 'strategy'
  meceBranches: string[]
}

function blankDraft(sourceRunId: string): DirectionDraft {
  return { name: '', sourceRunId, arm: 'baseline', meceBranches: [] }
}

export default function Directions() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: runs, loading, error, reload } = useApi(() => simulationApi.listRuns())
  const [selectedRunId, setSelectedRunId] = useState<string | null>(searchParams.get('run'))

  const [topic, setTopic] = useState('')
  const [drafts, setDrafts] = useState<DirectionDraft[]>([blankDraft('')])
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [selectedNarrativeId, setSelectedNarrativeId] = useState<string | null>(null)
  const [polishing, setPolishing] = useState(false)
  const [polishError, setPolishError] = useState<string | null>(null)

  const {
    data: history,
    loading: historyLoading,
    error: historyError,
    reload: reloadHistory,
  } = useApi(
    () => (selectedRunId ? narrativesApi.list(selectedRunId) : Promise.resolve(null)),
    selectedRunId,
  )

  const { data: mece } = useApi(
    () =>
      selectedRunId
        ? nullOn404(meceApi.getForRun(selectedRunId))
        : Promise.resolve(null),
    selectedRunId,
  )

  const runList = (runs ?? []) as CockpitRun[]
  const branchNames = mece ? collectBranchNames(mece.decomposition) : []
  const narratives = history?.narratives ?? []
  const selected: DecisionNarrativeRead | null =
    narratives.find((item) => item.id === selectedNarrativeId) ?? narratives[0] ?? null

  function selectRun(runId: string) {
    setSelectedRunId(runId)
    setSearchParams({ run: runId })
    setSelectedNarrativeId(null)
    setGenerateError(null)
    setDrafts([blankDraft(runId)])
  }

  function updateDraft(index: number, patch: Partial<DirectionDraft>) {
    setDrafts((current) => current.map((draft, i) => (i === index ? { ...draft, ...patch } : draft)))
  }

  function toggleBranch(index: number, branch: string) {
    const draft = drafts[index]
    const next = draft.meceBranches.includes(branch)
      ? draft.meceBranches.filter((name) => name !== branch)
      : [...draft.meceBranches, branch]
    updateDraft(index, { meceBranches: next })
  }

  function validateDrafts(): string | null {
    const names = drafts.map((draft) => draft.name.trim())
    if (names.some((name) => name.length === 0)) return '每个方向都需要填写名称。'
    if (new Set(names).size !== names.length) return '方向名称不能重复。'
    if (drafts.some((draft) => !draft.sourceRunId)) return '每个方向都需要选择来源 Run。'
    return null
  }

  async function handleGenerate() {
    if (!selectedRunId) return
    const problem = validateDrafts()
    if (problem) {
      setGenerateError(problem)
      return
    }
    setGenerating(true)
    setGenerateError(null)
    const payload = {
      topic: topic.trim() || null,
      directions: drafts.map(
        (draft): NarrativeDirectionDefinition => ({
          name: draft.name.trim(),
          source_run_id: draft.sourceRunId,
          arm: draft.arm,
          mece_branches: draft.meceBranches,
          deliberation_id: null,
        }),
      ),
      loop_id: null,
    }
    try {
      const created = await narrativesApi.generate(selectedRunId, payload)
      setSelectedNarrativeId(created.id)
      reloadHistory()
    } catch (e: unknown) {
      const info = parseApiError(e)
      setGenerateError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setGenerating(false)
    }
  }

  async function handlePolish() {
    if (!selectedRunId || !selected) return
    setPolishing(true)
    setPolishError(null)
    try {
      await narrativesApi.polish(selectedRunId, selected.id)
      reloadHistory()
    } catch (e: unknown) {
      const info = parseApiError(e)
      setPolishError(
        info.status === 503
          ? 'LLM 未配置，无法润色；确定性简报不受影响。'
          : info.code
            ? `${info.code}：${info.message}`
            : info.message,
      )
    } finally {
      setPolishing(false)
    }
  }

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-slate-100">决策方向简报</h2>
        <p className="text-sm text-slate-400">
          从已存储的数值结果与商议输出确定性地组合决策方向：每个方向带结果分布、关键驱动、调头信号、事前验尸与
          48 小时第一步，并标注出处。简报不凭空产生方向——方向定义由你显式给出。
        </p>
        <CockpitNav />
      </div>

      <Card>
        <CardBody>
          <RunPicker runs={runList} selectedId={selectedRunId} onSelect={selectRun} label="锚定 Run" />
        </CardBody>
      </Card>

      {!selectedRunId ? (
        <EmptyState title="请选择一个锚定 Run" description="简报围绕锚定 Run 的 MECE 结构与领域组织；各方向可引用其他 Run 的 ensemble。" />
      ) : (
        <>
          <Card>
            <CardHeader title="生成简报" />
            <CardBody className="space-y-4">
              <div>
                <label htmlFor="narrative-topic" className="mb-1 block text-xs text-slate-500">
                  主题（留空则使用 MECE 主题或 Run id）
                </label>
                <input
                  id="narrative-topic"
                  value={topic}
                  onChange={(event) => setTopic(event.target.value)}
                  placeholder="例如：是否上线 AI 客服线"
                  className={inputClassName()}
                />
              </div>

              {drafts.map((draft, index) => (
                <div key={index} className="space-y-3 rounded-lg border border-slate-700/50 p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-200">方向 {index + 1}</span>
                    {drafts.length > 1 && (
                      <button
                        type="button"
                        onClick={() => setDrafts(drafts.filter((_, i) => i !== index))}
                        className="text-xs text-slate-400 hover:text-red-300"
                      >
                        移除
                      </button>
                    )}
                  </div>
                  <div>
                    <label htmlFor={`direction-name-${index}`} className="mb-1 block text-xs text-slate-500">
                      方向名称
                    </label>
                    <input
                      id={`direction-name-${index}`}
                      value={draft.name}
                      onChange={(event) => updateDraft(index, { name: event.target.value })}
                      placeholder="例如：全力投入"
                      className={inputClassName()}
                    />
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label htmlFor={`direction-run-${index}`} className="mb-1 block text-xs text-slate-500">
                        来源 Run（提供 ensemble 分布）
                      </label>
                      <select
                        id={`direction-run-${index}`}
                        value={draft.sourceRunId}
                        onChange={(event) => updateDraft(index, { sourceRunId: event.target.value })}
                        className={inputClassName()}
                      >
                        <option value="" disabled>
                          请选择
                        </option>
                        {runList.map((run) => (
                          <option key={run.id} value={run.id}>
                            {run.id}（{run.status}）
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label htmlFor={`direction-arm-${index}`} className="mb-1 block text-xs text-slate-500">
                        Arm
                      </label>
                      <select
                        id={`direction-arm-${index}`}
                        value={draft.arm}
                        onChange={(event) =>
                          updateDraft(index, { arm: event.target.value as 'baseline' | 'strategy' })
                        }
                        className={inputClassName()}
                      >
                        <option value="baseline">baseline</option>
                        <option value="strategy">strategy</option>
                      </select>
                    </div>
                  </div>
                  {branchNames.length > 0 && (
                    <fieldset>
                      <legend className="mb-1 text-xs text-slate-500">回溯的 MECE 分支</legend>
                      <div className="flex flex-wrap gap-3">
                        {branchNames.map((branch) => (
                          <label key={branch} className="flex items-center gap-1.5 text-sm text-slate-300">
                            <input
                              type="checkbox"
                              checked={draft.meceBranches.includes(branch)}
                              onChange={() => toggleBranch(index, branch)}
                            />
                            {branch}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  )}
                </div>
              ))}

              {drafts.length < 4 && (
                <button
                  type="button"
                  onClick={() => setDrafts([...drafts, blankDraft(selectedRunId)])}
                  className="text-sm text-blue-300 hover:text-blue-200"
                >
                  + 添加方向（最多 4 个）
                </button>
              )}

              {generateError && <ErrorBanner message={generateError} />}
              <button
                type="button"
                onClick={() => void handleGenerate()}
                disabled={generating}
                className="rounded-full bg-blue-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-400 disabled:opacity-50"
              >
                {generating ? '生成中…' : '生成简报'}
              </button>
              <p className="text-xs text-slate-500">
                生成是确定性的：相同输入产生字节相同的简报；重新生成会产生新版本，永不覆盖。来源
                Run 必须已完成且存有 ensemble，否则生成会被拒绝并指明先运行的接口。
              </p>
            </CardBody>
          </Card>

          {historyError && !historyLoading && (
            <ErrorBanner message={historyError} onRetry={reloadHistory} />
          )}
          {historyLoading ? (
            <LoadingSpinner />
          ) : narratives.length === 0 ? (
            <EmptyState
              title="尚无简报"
              description="为这个 Run 生成第一份简报；历史版本会在这里按最新优先列出。"
            />
          ) : (
            <>
              <div className="flex flex-wrap gap-2" aria-label="简报版本">
                {narratives.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSelectedNarrativeId(item.id)}
                    className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
                      selected?.id === item.id
                        ? 'border-blue-500/30 bg-blue-500/10 font-medium text-blue-300'
                        : 'border-slate-700/50 bg-slate-800/30 text-slate-400 hover:bg-slate-800/50 hover:text-slate-200'
                    }`}
                  >
                    v{item.version} · {item.topic}
                  </button>
                ))}
              </div>
              {selected && (
                <NarrativeView
                  narrative={selected}
                  onPolish={() => void handlePolish()}
                  polishing={polishing}
                  polishError={polishError}
                />
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
