import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { simulationApi } from '../api/endpoints'
import { directionsApi, meceApi, narrativesApi, nullOn404, parseApiError } from '../api/engine'
import type {
  DecisionNarrativeRead,
  DecompositionTree,
  DerivationRead,
  DerivationRuleOutcome,
  DirectionMappingRead,
  NarrativeDirectionDefinition,
  NarrativeGenerateRequest,
} from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import {
  originLabel,
  parseOverrideRecord,
  parseProposalRecord,
  shortHash,
  statusLabel,
} from '../components/cockpit/directionMappingDisplay'
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

const RULE_LABELS: Record<DerivationRuleOutcome['rule_id'], string> = {
  highest_p50: '最高 P50',
  most_robust: '最稳健',
  baseline_control: '基线对照',
}

function outcomeText(outcome: DerivationRuleOutcome): string {
  if (outcome.status === 'produced') {
    return `已选 ${outcome.source_run_id} / ${outcome.arm}（P50 ${outcome.p50}，亏损概率 ${outcome.p_loss}）`
  }
  if (outcome.status === 'duplicate') {
    return `与规则 ${RULE_LABELS[outcome.duplicate_of_rule as DerivationRuleOutcome['rule_id']] ?? outcome.duplicate_of_rule} 重复，未重复写入`
  }
  if (outcome.status === 'skipped') {
    return `已跳过：${outcome.reason}`
  }
  return `未产生：${outcome.reason}`
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

  const [useStoredMappings, setUseStoredMappings] = useState(false)
  const [derivation, setDerivation] = useState<DerivationRead | null>(null)
  const [deriving, setDeriving] = useState(false)
  const [deriveError, setDeriveError] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editSourceRunId, setEditSourceRunId] = useState('')
  const [editArm, setEditArm] = useState<'baseline' | 'strategy'>('baseline')
  const [savingMapping, setSavingMapping] = useState(false)
  const [mappingError, setMappingError] = useState<string | null>(null)
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [reviewing, setReviewing] = useState<{ id: string; action: 'accept' | 'reject' } | null>(
    null,
  )
  const [confirmingRejectId, setConfirmingRejectId] = useState<string | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)

  const {
    data: history,
    loading: historyLoading,
    error: historyError,
    reload: reloadHistory,
  } = useApi(
    () => (selectedRunId ? narrativesApi.list(selectedRunId) : Promise.resolve(null)),
    selectedRunId,
  )

  const {
    data: mappingsData,
    loading: mappingsLoading,
    error: mappingsError,
    reload: reloadMappings,
  } = useApi(
    () => (selectedRunId ? directionsApi.listMappings(selectedRunId) : Promise.resolve(null)),
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
  const mappings = mappingsData?.mappings ?? []
  // The backend is the source of truth for review state: only `active`
  // rows resolve into generation; `proposed` rows await review here.
  const proposedMappings = mappings.filter((mapping) => mapping.status === 'proposed')
  const activeMappings = mappings.filter((mapping) => mapping.status === 'active')
  const selected: DecisionNarrativeRead | null =
    narratives.find((item) => item.id === selectedNarrativeId) ?? narratives[0] ?? null

  function selectRun(runId: string) {
    setSelectedRunId(runId)
    setSearchParams({ run: runId })
    setSelectedNarrativeId(null)
    setGenerateError(null)
    setDrafts([blankDraft(runId)])
    setUseStoredMappings(false)
    setDerivation(null)
    setDeriveError(null)
    setEditingId(null)
    setMappingError(null)
    setConfirmingDeleteId(null)
    setReviewing(null)
    setConfirmingRejectId(null)
    setReviewError(null)
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
    let payload: NarrativeGenerateRequest
    if (useStoredMappings) {
      payload = { topic: topic.trim() || null, loop_id: null }
    } else {
      const problem = validateDrafts()
      if (problem) {
        setGenerateError(problem)
        return
      }
      payload = {
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
    }
    setGenerating(true)
    setGenerateError(null)
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

  async function handleDerive() {
    if (!selectedRunId) return
    setDeriving(true)
    setDeriveError(null)
    try {
      const result = await directionsApi.derive(selectedRunId)
      setDerivation(result)
      reloadMappings()
    } catch (e: unknown) {
      const info = parseApiError(e)
      setDeriveError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setDeriving(false)
    }
  }

  function startEditing(mapping: DirectionMappingRead) {
    setEditingId(mapping.id)
    setEditName(mapping.name)
    setEditSourceRunId(mapping.source_run_id)
    setEditArm(mapping.arm)
    setMappingError(null)
    setConfirmingDeleteId(null)
  }

  async function handleSaveMapping(mapping: DirectionMappingRead) {
    if (!selectedRunId) return
    if (!editName.trim()) {
      setMappingError('映射名称不能为空。')
      return
    }
    if (!editSourceRunId) {
      setMappingError('映射需要选择来源 Run。')
      return
    }
    setSavingMapping(true)
    setMappingError(null)
    try {
      await directionsApi.updateMapping(selectedRunId, mapping.id, {
        name: editName.trim(),
        source_run_id: editSourceRunId,
        arm: editArm,
      })
      setEditingId(null)
      reloadMappings()
    } catch (e: unknown) {
      const info = parseApiError(e)
      setMappingError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setSavingMapping(false)
    }
  }

  async function handleDeleteMapping(mapping: DirectionMappingRead) {
    if (!selectedRunId) return
    setDeleting(true)
    setMappingError(null)
    try {
      await directionsApi.deleteMapping(selectedRunId, mapping.id)
      setConfirmingDeleteId(null)
      reloadMappings()
    } catch (e: unknown) {
      const info = parseApiError(e)
      if (info.status === 404) {
        // Already gone: reload the list back to the truth.
        setConfirmingDeleteId(null)
        reloadMappings()
      } else {
        setMappingError(info.code ? `${info.code}：${info.message}` : info.message)
      }
    } finally {
      setDeleting(false)
    }
  }

  async function handleReview(mapping: DirectionMappingRead, action: 'accept' | 'reject') {
    if (!selectedRunId) return
    setReviewing({ id: mapping.id, action })
    setReviewError(null)
    try {
      if (action === 'accept') {
        await directionsApi.acceptMapping(selectedRunId, mapping.id)
      } else {
        await directionsApi.rejectMapping(selectedRunId, mapping.id)
      }
      setConfirmingRejectId(null)
      reloadMappings()
    } catch (e: unknown) {
      const info = parseApiError(e)
      if (info.status === 404) {
        // Already gone: reload the list back to the truth.
        setConfirmingRejectId(null)
        reloadMappings()
      } else {
        setReviewError(info.code ? `${info.code}：${info.message}` : info.message)
      }
    } finally {
      setReviewing(null)
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

  const usedMappingNames =
    selected && selected.direction_mapping_ids.length > 0
      ? selected.direction_mapping_ids.map((id) => {
          const found = mappings.find((mapping) => mapping.id === id)
          return found ? found.name : `已删除的映射 ${id.slice(0, 8)}…`
        })
      : []

  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <h2 className="text-xl font-semibold text-slate-100">决策方向简报</h2>
        <p className="text-sm text-slate-400">
          从已存储的数值结果与商议输出确定性地组合决策方向：每个方向带结果分布、关键驱动、调头信号、事前验尸与
          48 小时第一步，并标注出处。方向定义由你显式给出，或由确定性规则推导、LLM
          提案（须经你评审接受）、变量覆盖（新建分支 Run）存为映射——简报只用「可用」状态的映射，不凭空产生方向。
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
            <CardHeader title="推导方向" />
            <CardBody className="space-y-4">
              <p className="text-sm text-slate-400">
                确定性规则（最高 P50、最稳健、基线对照）在锚定 Run 的场景家族中挑选方向并存为映射；不新建任何
                Run，也不调用 LLM。每条规则的结果都会如实列出：选了什么、没选到、重复了，还是因你改过而跳过。
              </p>
              {deriveError && <ErrorBanner message={deriveError} />}
              <button
                type="button"
                onClick={() => void handleDerive()}
                disabled={deriving}
                className="rounded-full bg-blue-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-400 disabled:opacity-50"
              >
                {deriving ? '推导中…' : '推导方向'}
              </button>
              {derivation && (
                <div className="space-y-2">
                  <p className="text-xs text-slate-500">
                    规则版本 {derivation.rules_version} · 场景家族 {derivation.family_size} 个 Run ·{' '}
                    {derivation.candidates_considered} 个候选 · 哈希{' '}
                    <span className="break-all font-mono">{derivation.derivation_hash}</span>
                  </p>
                  <ul className="space-y-1.5">
                    {derivation.outcomes.map((outcome) => (
                      <li key={outcome.rule_id} className="text-sm text-slate-300">
                        <span className="font-medium text-slate-200">{RULE_LABELS[outcome.rule_id]}</span>
                        {' — '}
                        {outcomeText(outcome)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="待评审提案" />
            <CardBody className="space-y-4">
              <p className="text-sm text-slate-400">
                LLM 提案先存为「待评审」映射：只有你显式接受后才能用于生成简报；拒绝后保留为审计记录，不再进入简报。评审只改状态，不改提案内容；接受时会由后端重新校验提案的引用，过期引用会被拒绝并留在这里。
              </p>
              {reviewError && <ErrorBanner message={reviewError} />}
              {mappingsLoading ? (
                <LoadingSpinner />
              ) : proposedMappings.length === 0 ? (
                <p className="text-sm text-slate-400">暂无待评审提案。</p>
              ) : (
                <ul className="space-y-3">
                  {proposedMappings.map((mapping) => {
                    const proposal = parseProposalRecord(mapping.proposal_record)
                    const provenance = [
                      proposal?.model ? `模型 ${proposal.model}` : null,
                      proposal?.templateId
                        ? `模板 ${proposal.templateId}${proposal.templateVersion ? ` v${proposal.templateVersion}` : ''}`
                        : null,
                      proposal?.proposalHash ? `提案哈希 ${shortHash(proposal.proposalHash)}` : null,
                    ].filter((part): part is string => part !== null)
                    const isReviewing = reviewing?.id === mapping.id
                    return (
                      <li
                        key={mapping.id}
                        className="space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3"
                      >
                        <div>
                          <span className="text-sm font-medium text-slate-200">{mapping.name}</span>{' '}
                          <span className="text-xs text-slate-500">
                            {mapping.source_run_id} / {mapping.arm}
                          </span>{' '}
                          <span className="text-xs text-slate-500">
                            {[originLabel(mapping.origin), statusLabel(mapping.status)]
                              .filter(Boolean)
                              .join(' · ')}
                          </span>
                        </div>
                        {mapping.mece_branches.length > 0 && (
                          <p className="text-xs text-slate-400">
                            回溯分支：{mapping.mece_branches.join('、')}
                          </p>
                        )}
                        {proposal && proposal.keyVariables.length > 0 && (
                          <p className="text-xs text-slate-400">
                            关键变量：{proposal.keyVariables.join('、')}
                          </p>
                        )}
                        {proposal?.rationale && (
                          <p className="text-sm text-slate-300">理由：{proposal.rationale}</p>
                        )}
                        {provenance.length > 0 && (
                          <p className="text-xs text-slate-500">{provenance.join(' · ')}</p>
                        )}
                        <div className="flex flex-wrap items-center gap-2">
                          {confirmingRejectId === mapping.id ? (
                            <>
                              <span className="text-xs text-amber-300">
                                确认拒绝「{mapping.name}」？拒绝后该提案只保留为审计记录。
                              </span>
                              <button
                                type="button"
                                aria-label={`确认拒绝提案「${mapping.name}」`}
                                onClick={() => void handleReview(mapping, 'reject')}
                                disabled={reviewing !== null}
                                className="rounded-lg bg-red-500 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
                              >
                                {isReviewing && reviewing?.action === 'reject'
                                  ? '拒绝中…'
                                  : '确认拒绝'}
                              </button>
                              <button
                                type="button"
                                onClick={() => setConfirmingRejectId(null)}
                                disabled={reviewing !== null}
                                className="text-xs text-slate-400 hover:text-slate-300 disabled:opacity-50"
                              >
                                取消
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                aria-label={`接受提案「${mapping.name}」`}
                                onClick={() => void handleReview(mapping, 'accept')}
                                disabled={reviewing !== null}
                                className="rounded-full bg-blue-500 px-3.5 py-1.5 text-sm font-medium text-white transition hover:bg-blue-400 disabled:opacity-50"
                              >
                                {isReviewing && reviewing?.action === 'accept' ? '接受中…' : '接受'}
                              </button>
                              <button
                                type="button"
                                aria-label={`拒绝提案「${mapping.name}」`}
                                onClick={() => setConfirmingRejectId(mapping.id)}
                                disabled={reviewing !== null}
                                className="rounded-full border border-slate-600 px-3.5 py-1.5 text-sm text-slate-300 transition hover:border-red-400/50 hover:text-red-300 disabled:opacity-50"
                              >
                                拒绝
                              </button>
                            </>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="已存方向映射" />
            <CardBody className="space-y-4">
              {mappingsError && !mappingsLoading && (
                <ErrorBanner message={mappingsError} onRetry={reloadMappings} />
              )}
              {mappingError && <ErrorBanner message={mappingError} />}
              {mappingsLoading ? (
                <LoadingSpinner />
              ) : mappings.length === 0 ? (
                <EmptyState
                  title="尚无已存方向映射"
                  description="用上面的「推导方向」生成映射，或在生成表单里显式定义方向；映射可改名、改来源，改过后推导不会覆盖它。"
                />
              ) : (
                <ul className="space-y-3">
                  {mappings.map((mapping) => {
                    const overrideSummary = parseOverrideRecord(mapping.override_record)
                    return (
                    <li
                      key={mapping.id}
                      className="space-y-3 rounded-lg border border-slate-700/50 p-3"
                    >
                      {editingId === mapping.id ? (
                        <div className="space-y-3">
                          <div>
                            <label
                              htmlFor={`mapping-name-${mapping.id}`}
                              className="mb-1 block text-xs text-slate-500"
                            >
                              映射名称
                            </label>
                            <input
                              id={`mapping-name-${mapping.id}`}
                              value={editName}
                              onChange={(event) => setEditName(event.target.value)}
                              className={inputClassName()}
                            />
                          </div>
                          <div className="grid gap-3 sm:grid-cols-2">
                            <div>
                              <label
                                htmlFor={`mapping-run-${mapping.id}`}
                                className="mb-1 block text-xs text-slate-500"
                              >
                                来源 Run
                              </label>
                              <select
                                id={`mapping-run-${mapping.id}`}
                                value={editSourceRunId}
                                onChange={(event) => setEditSourceRunId(event.target.value)}
                                className={inputClassName()}
                              >
                                {runList.map((run) => (
                                  <option key={run.id} value={run.id}>
                                    {run.id}（{run.status}）
                                  </option>
                                ))}
                              </select>
                            </div>
                            <div>
                              <label
                                htmlFor={`mapping-arm-${mapping.id}`}
                                className="mb-1 block text-xs text-slate-500"
                              >
                                Arm
                              </label>
                              <select
                                id={`mapping-arm-${mapping.id}`}
                                value={editArm}
                                onChange={(event) =>
                                  setEditArm(event.target.value as 'baseline' | 'strategy')
                                }
                                className={inputClassName()}
                              >
                                <option value="baseline">baseline</option>
                                <option value="strategy">strategy</option>
                              </select>
                            </div>
                          </div>
                          <div className="flex gap-2">
                            <button
                              type="button"
                              onClick={() => void handleSaveMapping(mapping)}
                              disabled={savingMapping}
                              className="rounded-full bg-blue-500 px-3.5 py-1.5 text-sm font-medium text-white transition hover:bg-blue-400 disabled:opacity-50"
                            >
                              {savingMapping ? '保存中…' : '保存'}
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingId(null)}
                              disabled={savingMapping}
                              className="text-sm text-slate-400 hover:text-slate-300 disabled:opacity-50"
                            >
                              取消
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div>
                            <span className="text-sm font-medium text-slate-200">{mapping.name}</span>{' '}
                            <span className="text-xs text-slate-500">
                              {mapping.source_run_id} / {mapping.arm}
                            </span>{' '}
                            <span className="text-xs text-slate-500">
                              {[
                                originLabel(mapping.origin),
                                statusLabel(mapping.status),
                                mapping.user_edited ? '已编辑' : '',
                              ]
                                .filter(Boolean)
                                .join(' · ')}
                            </span>
                            {overrideSummary && overrideSummary.overrides.length > 0 && (
                              <span className="block text-xs text-slate-500">
                                覆盖：
                                {overrideSummary.overrides
                                  .map((item) => `${item.variableId}=${item.value}`)
                                  .join('、')}
                                {overrideSummary.forkStep !== null &&
                                  ` · 分支步骤 ${overrideSummary.forkStep}`}
                              </span>
                            )}
                          </div>
                          <span className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => startEditing(mapping)}
                              className="text-xs text-slate-400 hover:text-slate-200"
                            >
                              编辑
                            </button>
                            {confirmingDeleteId === mapping.id ? (
                              <span className="flex flex-wrap items-center gap-2">
                                <span className="text-xs text-amber-300">
                                  确认删除「{mapping.name}」？
                                </span>
                                <button
                                  type="button"
                                  onClick={() => void handleDeleteMapping(mapping)}
                                  disabled={deleting}
                                  className="rounded-lg bg-red-500 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
                                >
                                  {deleting ? '删除中…' : '确认删除'}
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setConfirmingDeleteId(null)}
                                  disabled={deleting}
                                  className="text-xs text-slate-400 hover:text-slate-300 disabled:opacity-50"
                                >
                                  取消
                                </button>
                              </span>
                            ) : (
                              <button
                                type="button"
                                onClick={() => setConfirmingDeleteId(mapping.id)}
                                className="text-xs text-slate-400 hover:text-red-300"
                              >
                                删除
                              </button>
                            )}
                          </span>
                        </div>
                      )}
                    </li>
                    )
                  })}
                </ul>
              )}
              <p className="text-xs text-slate-500">
                删除映射只影响以后生成简报，已生成的简报版本不受影响。改过名称或来源的映射会被标记为「已编辑」，推导不会覆盖它。
              </p>
            </CardBody>
          </Card>

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

              <label className="flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={useStoredMappings}
                  onChange={(event) => setUseStoredMappings(event.target.checked)}
                />
                使用已存方向映射生成（按顺序取前 4 个）
              </label>

              {useStoredMappings ? (
                activeMappings.length === 0 ? (
                  <p className="text-sm text-slate-400">
                    {mappings.length === 0
                      ? '这个 Run 还没有已存方向映射——先推导方向，或取消勾选显式定义方向。'
                      : '这个 Run 的已存映射都不在可用状态——先在上方评审接受提案，或取消勾选显式定义方向。'}
                  </p>
                ) : (
                  <div className="space-y-1.5">
                    <p className="text-sm text-slate-300">
                      将使用的映射：
                      {activeMappings.slice(0, 4).map((mapping) => mapping.name).join('、')}
                    </p>
                    {activeMappings.length > 4 && (
                      <p className="text-xs text-slate-500">
                        共有 {activeMappings.length} 个可用映射，超出 4 个的部分本次不会使用。
                      </p>
                    )}
                  </div>
                )
              ) : (
                <>
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
                </>
              )}

              {generateError && <ErrorBanner message={generateError} />}
              <button
                type="button"
                onClick={() => void handleGenerate()}
                disabled={generating || (useStoredMappings && (mappingsLoading || activeMappings.length === 0))}
                className="rounded-full bg-blue-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-400 disabled:opacity-50"
              >
                {generating ? '生成中…' : '生成简报'}
              </button>
              <p className="text-xs text-slate-500">
                生成是确定性的：相同输入产生字节相同的简报；重新生成会产生新版本，永不覆盖。来源
                Run 必须已完成且存有 ensemble，否则生成会被拒绝并指明先运行的接口。只有「可用」状态的映射会用于生成；待评审与已拒绝的映射不会进入简报。
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
              {usedMappingNames.length > 0 && (
                <p className="text-sm text-slate-400">
                  本简报使用了已存映射：{usedMappingNames.join('、')}
                </p>
              )}
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
