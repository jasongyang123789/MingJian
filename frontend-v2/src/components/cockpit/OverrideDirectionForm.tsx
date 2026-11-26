import { useState } from 'react'

import { directionsApi, nullOn404, parseApiError, variablesApi } from '../../api/engine'
import type {
  DirectionOverrideRead,
  DirectionOverrideRequest,
  DirectionOverrideSpec,
  VariableDefinition,
} from '../../api/engineTypes'
import { distributionSummary } from './format'
import { statusLabel } from '../ui/dataSurfaceUtils'
import { Card, CardBody, CardHeader } from '../ui/Card'
import { ErrorBanner } from '../ui/ErrorBanner'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { useApi } from '../../hooks/useApi'

/** Mirrors the backend's MAX_DIRECTIONS: one override request holds 1–4 specs. */
const MAX_SPECS = 4
/** Mirrors the backend's DirectionOverrideSpec name length bound. */
const MAX_NAME_LENGTH = 120

function inputClassName() {
  return 'w-full rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none'
}

interface OverrideRowDraft {
  variableId: string
  value: string
  /** Picker filter text (draft-only, never sent): substring match on id/description. */
  filter: string
}

interface OverrideSpecDraft {
  name: string
  arm: 'baseline' | 'strategy'
  meceBranches: string[]
  forkStep: string
  rows: OverrideRowDraft[]
}

function blankSpec(): OverrideSpecDraft {
  return { name: '', arm: 'baseline', meceBranches: [], forkStep: '', rows: [{ variableId: '', value: '', filter: '' }] }
}

function variableOptionLabel(variable: VariableDefinition): string {
  return [variable.id, variable.unit, distributionSummary(variable)]
    .filter((part) => part.length > 0)
    .join(' · ')
}

/**
 * Picker filter: case-insensitive substring match against the
 * variable's id, description, unit, and distribution summary —
 * the identifying text the picker shows. An empty query matches
 * everything, so clearing the filter restores all options.
 */
function variableMatchesFilter(variable: VariableDefinition, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (needle === '') return true
  const haystack = [
    variable.id,
    variable.description,
    variable.unit,
    distributionSummary(variable),
  ]
    .join(' ')
    .toLowerCase()
  return haystack.includes(needle)
}

/**
 * Client-side validation mirroring the backend contract
 * (DirectionOverrideSpec/DirectionOverrideRequest): names stripped,
 * non-empty, ≤120 chars, unique; ≥1 override per spec, each naming a
 * bound variable with a finite numeric value; fork_step blank or an
 * integer ≥ 1. Returns the first problem, or null when the request
 * is well-shaped. The backend still re-validates everything
 * server-side; its refusals surface with code + message.
 */
function validateSpecs(specs: OverrideSpecDraft[], boundIds: string[]): string | null {
  const names = specs.map((spec) => spec.name.trim())
  if (names.some((name) => name.length === 0)) return '每个覆盖方向都需要填写名称。'
  if (names.some((name) => name.length > MAX_NAME_LENGTH)) {
    return `方向名称不能超过 ${MAX_NAME_LENGTH} 个字符。`
  }
  if (new Set(names).size !== names.length) return '覆盖方向名称不能重复。'
  for (let i = 0; i < specs.length; i += 1) {
    const spec = specs[i]
    const label = `方向「${names[i]}」`
    if (spec.rows.length === 0) return `${label}至少需要一个变量覆盖。`
    const seen = new Set<string>()
    for (const row of spec.rows) {
      if (!row.variableId) return `${label}有未选择变量的覆盖行。`
      if (seen.has(row.variableId)) return `${label}重复选择了变量 ${row.variableId}。`
      seen.add(row.variableId)
      if (!boundIds.includes(row.variableId)) return `${label}选择了未绑定的变量 ${row.variableId}。`
      const raw = row.value.trim()
      if (raw === '') return `${label}变量 ${row.variableId} 需要填写固定值。`
      if (!Number.isFinite(Number(raw))) return `${label}变量 ${row.variableId} 的固定值必须是有限数字。`
    }
    const fork = spec.forkStep.trim()
    if (fork !== '') {
      const step = Number(fork)
      if (!Number.isInteger(step) || step < 1) return `${label}的分叉步必须是 ≥ 1 的整数，留空则用默认中点。`
    }
  }
  return null
}

function buildPayload(specs: OverrideSpecDraft[]): DirectionOverrideRequest {
  return {
    directions: specs.map((spec): DirectionOverrideSpec => {
      const overrides: Record<string, number> = {}
      for (const row of spec.rows) {
        overrides[row.variableId] = Number(row.value.trim())
      }
      const out: DirectionOverrideSpec = {
        name: spec.name.trim(),
        overrides,
        arm: spec.arm,
        mece_branches: spec.meceBranches,
      }
      // Blank means "backend midpoint default": omit the key entirely
      // rather than sending null.
      const fork = spec.forkStep.trim()
      if (fork !== '') out.fork_step = Number(fork)
      return out
    }),
  }
}

const OUTCOME_LABELS: Record<DirectionOverrideRead['outcomes'][number]['status'], string> = {
  stored: '已存入',
  skipped: '已跳过',
  failed: '创建失败',
}

interface OverrideDirectionFormProps {
  runId: string
  branchNames: string[]
  tickCount: number | null
  onMappingsChanged: () => void
}

export function OverrideDirectionForm({
  runId,
  branchNames,
  tickCount,
  onMappingsChanged,
}: OverrideDirectionFormProps) {
  const {
    data: variablesData,
    loading: variablesLoading,
    error: variablesError,
    reload: reloadVariables,
  } = useApi(() => nullOn404(variablesApi.getForRun(runId)), runId)

  const [expanded, setExpanded] = useState(false)
  const [specs, setSpecs] = useState<OverrideSpecDraft[]>([blankSpec()])
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<DirectionOverrideRead | null>(null)

  const boundVariables = variablesData?.bindings?.variables ?? []
  const boundIds = boundVariables.map((variable) => variable.id)
  const hasBindings = boundVariables.length > 0

  function updateSpec(index: number, patch: Partial<OverrideSpecDraft>) {
    setSpecs((current) => current.map((spec, i) => (i === index ? { ...spec, ...patch } : spec)))
  }

  function toggleBranch(index: number, branch: string) {
    const spec = specs[index]
    const next = spec.meceBranches.includes(branch)
      ? spec.meceBranches.filter((name) => name !== branch)
      : [...spec.meceBranches, branch]
    updateSpec(index, { meceBranches: next })
  }

  function updateRow(specIndex: number, rowIndex: number, patch: Partial<OverrideRowDraft>) {
    const spec = specs[specIndex]
    const rows = spec.rows.map((row, i) => (i === rowIndex ? { ...row, ...patch } : row))
    updateSpec(specIndex, { rows })
  }

  function addRow(specIndex: number) {
    const spec = specs[specIndex]
    const used = new Set(spec.rows.map((row) => row.variableId))
    const next = boundVariables.find((variable) => !used.has(variable.id))
    updateSpec(specIndex, {
      rows: [...spec.rows, { variableId: next?.id ?? '', value: '', filter: '' }],
    })
  }

  async function handleSubmit() {
    const problem = validateSpecs(specs, boundIds)
    if (problem) {
      setSubmitError(problem)
      return
    }
    setSubmitting(true)
    setSubmitError(null)
    setResult(null)
    try {
      const created = await directionsApi.createOverrides(runId, buildPayload(specs))
      setResult(created)
      onMappingsChanged()
    } catch (e: unknown) {
      const info = parseApiError(e)
      setSubmitError(info.code ? `${info.code}：${info.message}` : info.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardHeader title="新建变量覆盖方向" />
      <CardBody className="space-y-4">
        <p className="text-sm text-slate-400">
          给锚定 Run 的绑定变量指定固定值，每个覆盖方向都会新建一个从锚定快照分叉出来的
          Run：分叉点之前的历史继承锚定，分叉点之后按固定值采样。固定值可以超出原分布的采样范围——问「如果它是这个值」正是覆盖的用途。覆盖方向存为「变量覆盖」映射；新建的
          Run 还没有 ensemble，生成简报前先给它跑 monte-carlo。
        </p>
        {variablesError && !variablesLoading && (
          <ErrorBanner message={variablesError} onRetry={reloadVariables} />
        )}
        {variablesLoading ? (
          <LoadingSpinner />
        ) : !hasBindings ? (
          <p className="text-sm text-slate-400">
            锚定 Run 没有绑定变量，无法创建覆盖方向——覆盖只能指定锚定上已绑定的变量（后端会以
            direction_override_requires_bindings 拒绝无绑定锚定）。
          </p>
        ) : !expanded ? (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="rounded-full bg-blue-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-400"
          >
            新建变量覆盖方向
          </button>
        ) : (
          <>
            {specs.map((spec, specIndex) => (
              <div key={specIndex} className="space-y-3 rounded-lg border border-slate-700/50 p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-200">覆盖方向 {specIndex + 1}</span>
                  {specs.length > 1 && (
                    <button
                      type="button"
                      onClick={() => setSpecs(specs.filter((_, i) => i !== specIndex))}
                      className="text-xs text-slate-400 hover:text-red-300"
                    >
                      移除
                    </button>
                  )}
                </div>
                <div>
                  <label
                    htmlFor={`override-name-${specIndex}`}
                    className="mb-1 block text-xs text-slate-500"
                  >
                    覆盖方向名称
                  </label>
                  <input
                    id={`override-name-${specIndex}`}
                    value={spec.name}
                    onChange={(event) => updateSpec(specIndex, { name: event.target.value })}
                    placeholder="例如：现金提到 80"
                    className={inputClassName()}
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label
                      htmlFor={`override-arm-${specIndex}`}
                      className="mb-1 block text-xs text-slate-500"
                    >
                      方向 Arm
                    </label>
                    <select
                      id={`override-arm-${specIndex}`}
                      value={spec.arm}
                      onChange={(event) =>
                        updateSpec(specIndex, { arm: event.target.value as 'baseline' | 'strategy' })
                      }
                      className={inputClassName()}
                    >
                      <option value="baseline">baseline</option>
                      <option value="strategy">strategy</option>
                    </select>
                  </div>
                  <div>
                    <label
                      htmlFor={`override-fork-${specIndex}`}
                      className="mb-1 block text-xs text-slate-500"
                    >
                      分叉步（留空用默认中点）
                    </label>
                    <input
                      id={`override-fork-${specIndex}`}
                      value={spec.forkStep}
                      onChange={(event) => updateSpec(specIndex, { forkStep: event.target.value })}
                      inputMode="numeric"
                      placeholder="留空"
                      className={inputClassName()}
                    />
                  </div>
                </div>
                <p className="text-xs text-slate-500">
                  分叉步必须是 ≥ 1 的整数；后端会校验该步是否有快照。
                  {tickCount !== null && `锚定推演共 ${tickCount} 步。`}
                </p>
                <div className="space-y-3">
                  <span className="block text-xs text-slate-500">变量覆盖（至少一个）</span>
                  {spec.rows.map((row, rowIndex) => {
                    const variable = boundVariables.find((item) => item.id === row.variableId)
                    // The selected variable always stays listed even
                    // when it does not match the filter, so the
                    // select never shows a blank invalid state.
                    const visibleVariables = boundVariables.filter(
                      (candidate) =>
                        candidate.id === row.variableId ||
                        variableMatchesFilter(candidate, row.filter),
                    )
                    return (
                      <div key={rowIndex} className="space-y-1">
                        <div>
                          <label
                            htmlFor={`override-variable-filter-${specIndex}-${rowIndex}`}
                            className="mb-1 block text-xs text-slate-500"
                          >
                            筛选变量
                          </label>
                          <input
                            id={`override-variable-filter-${specIndex}-${rowIndex}`}
                            value={row.filter}
                            onChange={(event) =>
                              updateRow(specIndex, rowIndex, { filter: event.target.value })
                            }
                            placeholder="输入变量 id 或描述筛选…"
                            className={inputClassName()}
                          />
                        </div>
                        <div className="grid gap-3 sm:grid-cols-[1fr_160px_auto]">
                          <div>
                            <label
                              htmlFor={`override-variable-${specIndex}-${rowIndex}`}
                              className="mb-1 block text-xs text-slate-500"
                            >
                              变量
                            </label>
                            <select
                              id={`override-variable-${specIndex}-${rowIndex}`}
                              value={row.variableId}
                              onChange={(event) =>
                                updateRow(specIndex, rowIndex, { variableId: event.target.value })
                              }
                              className={inputClassName()}
                            >
                              <option value="" disabled>
                                请选择变量
                              </option>
                              {visibleVariables.map((candidate) => (
                                <option
                                  key={candidate.id}
                                  value={candidate.id}
                                  disabled={
                                    candidate.id !== row.variableId &&
                                    spec.rows.some((other) => other.variableId === candidate.id)
                                  }
                                >
                                  {variableOptionLabel(candidate)}
                                </option>
                              ))}
                            </select>
                            {visibleVariables.length === 0 && (
                              <p className="mt-1 text-xs text-slate-500">
                                没有匹配的变量，换个筛选词或清空筛选。
                              </p>
                            )}
                          </div>
                          <div>
                            <label
                              htmlFor={`override-value-${specIndex}-${rowIndex}`}
                              className="mb-1 block text-xs text-slate-500"
                            >
                              固定值
                            </label>
                            <input
                              id={`override-value-${specIndex}-${rowIndex}`}
                              value={row.value}
                              onChange={(event) =>
                                updateRow(specIndex, rowIndex, { value: event.target.value })
                              }
                              inputMode="decimal"
                              placeholder="例如：80"
                              className={inputClassName()}
                            />
                          </div>
                          <div className="flex items-end pb-2">
                            {spec.rows.length > 1 && (
                              <button
                                type="button"
                                onClick={() =>
                                  updateSpec(specIndex, {
                                    rows: spec.rows.filter((_, i) => i !== rowIndex),
                                  })
                                }
                                aria-label={`移除变量行 ${rowIndex + 1}`}
                                className="text-xs text-slate-400 hover:text-red-300"
                              >
                                移除
                              </button>
                            )}
                          </div>
                        </div>
                        {variable && (variable.description || variable.evidence_ref) && (
                          <p className="text-xs text-slate-500">
                            {variable.description}
                            {variable.description && variable.evidence_ref ? ' ' : ''}
                            {variable.evidence_ref ? `证据：${variable.evidence_ref}` : ''}
                          </p>
                        )}
                      </div>
                    )
                  })}
                  {spec.rows.length < boundVariables.length && (
                    <button
                      type="button"
                      onClick={() => addRow(specIndex)}
                      className="text-sm text-blue-300 hover:text-blue-200"
                    >
                      ＋ 添加变量
                    </button>
                  )}
                </div>
                {branchNames.length > 0 && (
                  <fieldset>
                    <legend className="mb-1 text-xs text-slate-500">覆盖回溯的 MECE 分支</legend>
                    <div className="flex flex-wrap gap-3">
                      {branchNames.map((branch) => (
                        <label key={branch} className="flex items-center gap-1.5 text-sm text-slate-300">
                          <input
                            type="checkbox"
                            aria-label={`覆盖分支 ${branch}`}
                            checked={spec.meceBranches.includes(branch)}
                            onChange={() => toggleBranch(specIndex, branch)}
                          />
                          {branch}
                        </label>
                      ))}
                    </div>
                  </fieldset>
                )}
              </div>
            ))}

            {specs.length < MAX_SPECS && (
              <button
                type="button"
                onClick={() => setSpecs([...specs, blankSpec()])}
                className="text-sm text-blue-300 hover:text-blue-200"
              >
                ＋ 添加覆盖方向（最多 {MAX_SPECS} 个）
              </button>
            )}

            {submitError && <ErrorBanner message={submitError} />}
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={submitting}
                className="rounded-full bg-blue-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-400 disabled:opacity-50"
              >
                {submitting ? '创建中…' : '创建覆盖方向'}
              </button>
              <button
                type="button"
                onClick={() => setExpanded(false)}
                disabled={submitting}
                className="text-sm text-slate-400 hover:text-slate-300 disabled:opacity-50"
              >
                收起
              </button>
            </div>
            <p className="text-xs text-slate-500">
              提交即显式创建分支 Run：每个方向一个新 Run，不建 ensemble、不触发任何后台任务。已存在同名映射的方向会被跳过，原映射不受影响。
            </p>
            {result && (
              <div className="space-y-2">
                <p className="text-xs text-slate-500">
                  已处理 {result.directions_considered} 个方向 · 请求哈希{' '}
                  <span className="break-all font-mono">{result.override_hash}</span>
                </p>
                <ul className="space-y-1.5">
                  {result.outcomes.map((outcome) => (
                    <li key={outcome.name} className="text-sm text-slate-300">
                      <span className="font-medium text-slate-200">{outcome.name}</span>
                      {' — '}
                      {OUTCOME_LABELS[outcome.status]}：{outcome.reason}
                      {outcome.status === 'stored' && outcome.child_run_id && (
                        <span className="block text-xs text-slate-500">
                          子推演 {outcome.child_run_id}
                          {outcome.branch_id ? ` · 分支 ${outcome.branch_id}` : ''}
                          {outcome.fork_step !== null ? ` · 分叉步 ${outcome.fork_step}` : ''}
                          {outcome.child_status ? ` · 状态 ${statusLabel(outcome.child_status)}` : ''}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </CardBody>
    </Card>
  )
}
