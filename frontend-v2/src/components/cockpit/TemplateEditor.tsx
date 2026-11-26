// Variable-template editing surfaces. The form edits a TemplateDraft
// and sends it verbatim to the backend: the backend validator is the
// only arbiter, and its issues render inline. The one place the UI
// constrains construction is the formula expression editor, whose
// node vocabulary (literals / refs / six binary ops, exactly two
// args, refs only to sampled variables or earlier formulas) matches
// the backend formula graph by construction.

import type {
  CalibrationFitRead,
  DistributionType,
  FormulaOperator,
  MetricPolicySpec,
  ThresholdChange,
  VariableDefinition,
  VariableTemplateRead,
  VariableValidationResult,
} from '../../api/engineTypes'
import { distributionSummary, formatHash, formatNumber } from './format'
import { domainLabel } from '../ui/dataSurfaceUtils'
import {
  DISTRIBUTION_PARAMS,
  DISTRIBUTION_PARAM_LABELS,
  DISTRIBUTION_TYPES,
  FORMULA_OPERATORS,
  expressionFromJson,
  expressionToJson,
  knownRefsForFormula,
  newFormula,
  newInternalRow,
  newPolicy,
  newStateField,
  newVariable,
} from './templateDraft'
import type { ExpressionNode, TemplateDraft } from './templateDraft'

function inputClassName() {
  return 'w-full rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none'
}

function selectClassName() {
  return 'w-full rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 focus:border-blue-500/50 focus:outline-none'
}

function removeButtonClassName() {
  return 'rounded-lg border border-red-500/20 bg-red-500/5 px-2.5 py-1.5 text-xs text-red-300 transition-colors hover:bg-red-500/10'
}

function addButtonClassName() {
  return 'rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:bg-slate-800/60'
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-400">{children}</h4>
  )
}

function TextField({
  label,
  value,
  onChange,
  placeholder,
  ariaLabel,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  ariaLabel?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-slate-500">{label}</span>
      <input
        aria-label={ariaLabel ?? label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={inputClassName()}
      />
    </label>
  )
}

function NumberField({
  label,
  value,
  onChange,
  ariaLabel,
}: {
  label: string
  value: number | null
  onChange: (value: number | null) => void
  ariaLabel?: string
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-slate-500">{label}</span>
      <input
        type="number"
        step="any"
        aria-label={ariaLabel ?? label}
        value={value ?? ''}
        onChange={(event) => {
          const text = event.target.value
          if (text === '') {
            onChange(null)
            return
          }
          const parsed = Number(text)
          onChange(Number.isNaN(parsed) ? null : parsed)
        }}
        className={inputClassName()}
      />
    </label>
  )
}

// ---------------------------------------------------------------------------
// Formula expression editor (constrained vocabulary)
// ---------------------------------------------------------------------------

function NodeEditor({
  node,
  onChange,
  knownRefs,
  depth,
}: {
  node: ExpressionNode
  onChange: (node: ExpressionNode) => void
  knownRefs: string[]
  depth: number
}) {
  const kindLabel = depth === 0 ? '表达式' : `参数（第 ${depth} 层）`
  return (
    <div className={depth > 0 ? 'rounded-lg border border-slate-800/60 p-3' : ''}>
      <label className="block">
        <span className="mb-1 block text-xs text-slate-500">{kindLabel} · 节点类型</span>
        <select
          aria-label={kindLabel}
          value={node.kind}
          onChange={(event) => {
            const kind = event.target.value as ExpressionNode['kind']
            if (kind === 'literal') onChange({ kind: 'literal', value: 0 })
            else if (kind === 'ref') onChange({ kind: 'ref', ref: knownRefs[0] ?? '' })
            else
              onChange({
                kind: 'op',
                op: 'add',
                args: [
                  { kind: 'literal', value: 0 },
                  { kind: 'literal', value: 0 },
                ],
              })
          }}
          className={selectClassName()}
        >
          <option value="literal">数字字面量</option>
          <option value="ref">引用变量 / 公式</option>
          <option value="op">二元运算</option>
        </select>
      </label>

      {node.kind === 'literal' && (
        <div className="mt-2">
          <NumberField
            label="字面量"
            ariaLabel="字面量"
            value={node.value}
            onChange={(value) => onChange({ kind: 'literal', value })}
          />
        </div>
      )}

      {node.kind === 'ref' && (
        <label className="mt-2 block">
          <span className="mb-1 block text-xs text-slate-500">引用</span>
          <select
            aria-label="引用"
            value={node.ref}
            onChange={(event) => onChange({ kind: 'ref', ref: event.target.value })}
            className={selectClassName()}
          >
            {knownRefs.length === 0 && node.ref === '' && <option value="">暂无可引用的变量 / 公式</option>}
            {node.ref !== '' && !knownRefs.includes(node.ref) && (
              <option value={node.ref}>{node.ref}（不在已知 id 中，后端校验会拒绝）</option>
            )}
            {knownRefs.map((ref) => (
              <option key={ref} value={ref}>
                {ref}
              </option>
            ))}
          </select>
        </label>
      )}

      {node.kind === 'op' && (
        <div className="mt-2 space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">运算符</span>
            <select
              aria-label="运算符"
              value={node.op}
              onChange={(event) => onChange({ ...node, op: event.target.value as FormulaOperator })}
              className={selectClassName()}
            >
              {FORMULA_OPERATORS.map((op) => (
                <option key={op} value={op}>
                  {op}
                </option>
              ))}
            </select>
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="mb-1.5 text-xs text-slate-500">参数 1</p>
              <NodeEditor
                node={node.args[0]}
                onChange={(arg) => onChange({ ...node, args: [arg, node.args[1]] })}
                knownRefs={knownRefs}
                depth={depth + 1}
              />
            </div>
            <div>
              <p className="mb-1.5 text-xs text-slate-500">参数 2</p>
              <NodeEditor
                node={node.args[1]}
                onChange={(arg) => onChange({ ...node, args: [node.args[0], arg] })}
                knownRefs={knownRefs}
                depth={depth + 1}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ExpressionEditor({
  value,
  onChange,
  knownRefs,
}: {
  value: unknown
  onChange: (json: unknown) => void
  knownRefs: string[]
}) {
  const node = expressionFromJson(value)
  if (!node) {
    return (
      <div>
        <p className="text-xs leading-5 text-amber-300">
          该表达式超出编辑器词汇表（只读显示，保存时原样回传，不会被改写）。
        </p>
        <pre className="mt-1 overflow-x-auto rounded-lg border border-slate-800/60 p-2 font-mono text-[11px] text-slate-300">
          {JSON.stringify(value)}
        </pre>
      </div>
    )
  }
  return (
    <NodeEditor node={node} onChange={(next) => onChange(expressionToJson(next))} knownRefs={knownRefs} depth={0} />
  )
}

// ---------------------------------------------------------------------------
// Validation result rendering (backend verdict, shown inline)
// ---------------------------------------------------------------------------

export function ValidationIssuesView({
  result,
  title,
}: {
  result: VariableValidationResult
  title: string
}) {
  return (
    <div className="rounded-lg border border-slate-800/60 p-3">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
            result.is_valid
              ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400'
              : 'border-red-500/20 bg-red-500/10 text-red-400'
          }`}
        >
          {title}：{result.is_valid ? '通过' : '未通过'}
        </span>
        <span className="text-xs text-slate-500">{result.variable_count} 个变量</span>
      </div>
      {result.issues.length > 0 && (
        <ul className="mt-2 space-y-1">
          {result.issues.map((issue, index) => (
            <li key={index} className="text-xs leading-5 text-red-300">
              <span className="font-mono">{issue.kind}</span>
              {issue.variable && <span className="font-mono"> · {issue.variable}</span>} · {issue.message}
            </li>
          ))}
        </ul>
      )}
      {result.checks.length > 0 && (
        <ul className="mt-2 space-y-1">
          {result.checks.map((check, index) => (
            <li key={index} className="font-mono text-[11px] text-slate-500">
              {check.status === 'pass' ? 'PASS' : 'FAIL'} · {check.check}
              {check.variable && ` · ${check.variable}`}
              {check.detail && ` · ${check.detail}`}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// The editing form
// ---------------------------------------------------------------------------

export function TemplateForm({
  draft,
  onChange,
  domains,
  domainLocked,
  validation,
  onValidate,
  validating,
  saveError,
  saveValidation,
  onSave,
  saving,
  saveLabel,
  dirty,
}: {
  draft: TemplateDraft
  onChange: (draft: TemplateDraft) => void
  domains: string[]
  domainLocked: boolean
  validation: VariableValidationResult | null
  onValidate: () => void
  validating: boolean
  saveError: string | null
  saveValidation: VariableValidationResult | null
  onSave: () => void
  saving: boolean
  saveLabel: string
  dirty: boolean
}) {
  const update = (patch: Partial<TemplateDraft>) => onChange({ ...draft, ...patch })

  const updateVariable = (index: number, patch: Partial<VariableDefinition>) => {
    const variables = draft.variables.map((variable, i) => (i === index ? { ...variable, ...patch } : variable))
    update({ variables })
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="模板名称" value={draft.name} onChange={(name) => update({ name })} />
        {domainLocked ? (
          <div>
            <span className="mb-1 block text-xs text-slate-500">领域（创建后不可改）</span>
            <p className="rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-300">
              {domainLabel(draft.domain_id) || draft.domain_id}
            </p>
          </div>
        ) : domains.length > 0 ? (
          <label className="block">
            <span className="mb-1 block text-xs text-slate-500">领域</span>
            <select
              aria-label="领域"
              value={draft.domain_id}
              onChange={(event) => update({ domain_id: event.target.value })}
              className={selectClassName()}
            >
              {domains.map((domain) => (
                <option key={domain} value={domain}>
                  {domainLabel(domain) || domain}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <TextField label="领域" value={draft.domain_id} onChange={(domain_id) => update({ domain_id })} />
        )}
      </div>
      <div>
        <label htmlFor="template-description" className="mb-1.5 block text-xs text-slate-500">
          描述
        </label>
        <textarea
          id="template-description"
          value={draft.description}
          onChange={(event) => update({ description: event.target.value })}
          rows={2}
          className={inputClassName()}
        />
      </div>

      <div>
        <SectionTitle>变量表（{draft.variables.length} 个变量，最多 100 个）</SectionTitle>
        {draft.variables.length === 0 && (
          <p className="mb-2 text-sm text-slate-500">模板可以不带变量（只含状态默认值与策略）。</p>
        )}
        <div className="space-y-4">
          {draft.variables.map((variable, index) => (
            <div key={index} className="rounded-lg border border-slate-800/60 p-3">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <TextField
                  label="变量 id"
                  ariaLabel={`变量 ${index + 1} id`}
                  value={variable.id}
                  onChange={(id) => updateVariable(index, { id })}
                />
                <TextField
                  label="单位"
                  ariaLabel={`变量 ${index + 1} 单位`}
                  value={variable.unit}
                  onChange={(unit) => updateVariable(index, { unit })}
                />
                <label className="block">
                  <span className="mb-1 block text-xs text-slate-500">分布类型</span>
                  <select
                    aria-label={`变量 ${index + 1} 分布类型`}
                    value={variable.distribution.type}
                    onChange={(event) => {
                      const type = event.target.value as DistributionType
                      updateVariable(index, { distribution: { ...variable.distribution, type } })
                    }}
                    className={selectClassName()}
                  >
                    {DISTRIBUTION_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </label>
                <TextField
                  label="出处（evidence_ref）"
                  ariaLabel={`变量 ${index + 1} 出处`}
                  value={variable.evidence_ref}
                  onChange={(evidence_ref) => updateVariable(index, { evidence_ref })}
                  placeholder="evidence:… 或 estimate:…"
                />
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                {DISTRIBUTION_PARAMS[variable.distribution.type].map((param) => (
                  <NumberField
                    key={param}
                    label={DISTRIBUTION_PARAM_LABELS[param] ?? param}
                    ariaLabel={`变量 ${index + 1} ${DISTRIBUTION_PARAM_LABELS[param] ?? param}`}
                    value={variable.distribution[param] ?? null}
                    onChange={(value) => {
                      const distribution = { ...variable.distribution }
                      distribution[param] = value
                      updateVariable(index, { distribution })
                    }}
                  />
                ))}
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <TextField
                  label="描述"
                  ariaLabel={`变量 ${index + 1} 描述`}
                  value={variable.description}
                  onChange={(description) => updateVariable(index, { description })}
                />
                <TextField
                  label="Scope 标签（逗号分隔）"
                  ariaLabel={`变量 ${index + 1} Scope 标签`}
                  value={variable.scope_tags.join(', ')}
                  onChange={(text) =>
                    updateVariable(index, {
                      scope_tags: text
                        .split(',')
                        .map((tag) => tag.trim())
                        .filter((tag) => tag.length > 0),
                    })
                  }
                />
              </div>
              <div className="mt-3 flex justify-end">
                <button
                  onClick={() => update({ variables: draft.variables.filter((_, i) => i !== index) })}
                  className={removeButtonClassName()}
                >
                  删除该变量
                </button>
              </div>
            </div>
          ))}
        </div>
        <button
          onClick={() => update({ variables: [...draft.variables, newVariable()] })}
          className={addButtonClassName()}
        >
          + 添加变量
        </button>
      </div>

      <div>
        <SectionTitle>公式图（派生变量，最多 40 个公式）</SectionTitle>
        <p className="mb-2 text-xs leading-5 text-slate-500">
          表达式只能用数字字面量、引用与六种二元运算（add / subtract / multiply / divide / min / max），每个运算恰好两个参数；引用只能指向采样变量或排在前面的公式（列表顺序即求值顺序，前向引用不可能成环）。后端校验器是最终裁决。
        </p>
        <div className="space-y-4">
          {draft.formulas.map((formula, index) => (
            <div key={index} className="rounded-lg border border-slate-800/60 p-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                  label="输出 id"
                  ariaLabel={`公式 ${index + 1} 输出 id`}
                  value={formula.output}
                  onChange={(output) =>
                    update({ formulas: draft.formulas.map((f, i) => (i === index ? { ...f, output } : f)) })
                  }
                />
                <TextField
                  label="描述"
                  ariaLabel={`公式 ${index + 1} 描述`}
                  value={formula.description}
                  onChange={(description) =>
                    update({ formulas: draft.formulas.map((f, i) => (i === index ? { ...f, description } : f)) })
                  }
                />
              </div>
              <div className="mt-3">
                <ExpressionEditor
                  value={formula.expression}
                  onChange={(expression) =>
                    update({ formulas: draft.formulas.map((f, i) => (i === index ? { ...f, expression } : f)) })
                  }
                  knownRefs={knownRefsForFormula(draft, index)}
                />
              </div>
              <div className="mt-3 flex justify-end">
                <button
                  onClick={() => update({ formulas: draft.formulas.filter((_, i) => i !== index) })}
                  className={removeButtonClassName()}
                >
                  删除该公式
                </button>
              </div>
            </div>
          ))}
        </div>
        <button
          onClick={() => update({ formulas: [...draft.formulas, newFormula()] })}
          className={addButtonClassName()}
        >
          + 添加公式
        </button>
      </div>

      <div>
        <SectionTitle>状态默认值</SectionTitle>
        <div className="space-y-3">
          {draft.state_fields.map((field, index) => (
            <div key={index} className="grid items-end gap-3 sm:grid-cols-[1fr_2fr_120px_auto]">
              <TextField
                label="字段名"
                ariaLabel={`状态字段 ${index + 1} 字段名`}
                value={field.name}
                onChange={(name) =>
                  update({ state_fields: draft.state_fields.map((f, i) => (i === index ? { ...f, name } : f)) })
                }
              />
              <TextField
                label="描述"
                ariaLabel={`状态字段 ${index + 1} 描述`}
                value={field.description}
                onChange={(description) =>
                  update({ state_fields: draft.state_fields.map((f, i) => (i === index ? { ...f, description } : f)) })
                }
              />
              <NumberField
                label="默认值"
                ariaLabel={`状态字段 ${index + 1} 默认值`}
                value={field.default}
                onChange={(value) =>
                  update({ state_fields: draft.state_fields.map((f, i) => (i === index ? { ...f, default: value } : f)) })
                }
              />
              <button
                onClick={() => update({ state_fields: draft.state_fields.filter((_, i) => i !== index) })}
                className={removeButtonClassName()}
              >
                删除
              </button>
            </div>
          ))}
        </div>
        <button
          onClick={() => update({ state_fields: [...draft.state_fields, newStateField()] })}
          className={addButtonClassName()}
        >
          + 添加状态字段
        </button>
      </div>

      <div>
        <SectionTitle>策略阈值（Metric Policies）</SectionTitle>
        <p className="mb-2 text-xs leading-5 text-slate-500">
          阈值顺序由方向决定：increase 要求 alert &gt; critical，decrease 要求 alert &lt; critical——后端校验器裁决。
        </p>
        <div className="space-y-3">
          {draft.policies.map((policy, index) => (
            <div key={index} className="grid items-end gap-3 sm:grid-cols-[1fr_130px_120px_120px_auto]">
              <TextField
                label="指标"
                ariaLabel={`策略 ${index + 1} 指标`}
                value={policy.metric}
                onChange={(metric) =>
                  update({ policies: draft.policies.map((p, i) => (i === index ? { ...p, metric } : p)) })
                }
              />
              <label className="block">
                <span className="mb-1 block text-xs text-slate-500">方向</span>
                <select
                  aria-label={`策略 ${index + 1} 方向`}
                  value={policy.preferred_direction}
                  onChange={(event) =>
                    update({
                      policies: draft.policies.map((p, i) =>
                        i === index ? { ...p, preferred_direction: event.target.value } : p,
                      ),
                    })
                  }
                  className={selectClassName()}
                >
                  <option value="increase">increase</option>
                  <option value="decrease">decrease</option>
                </select>
              </label>
              <NumberField
                label="alert 阈值"
                ariaLabel={`策略 ${index + 1} alert 阈值`}
                value={policy.alert_threshold}
                onChange={(value) =>
                  update({ policies: draft.policies.map((p, i) => (i === index ? { ...p, alert_threshold: value } : p)) })
                }
              />
              <NumberField
                label="critical 阈值"
                ariaLabel={`策略 ${index + 1} critical 阈值`}
                value={policy.critical_threshold}
                onChange={(value) =>
                  update({
                    policies: draft.policies.map((p, i) => (i === index ? { ...p, critical_threshold: value } : p)),
                  })
                }
              />
              <button
                onClick={() => update({ policies: draft.policies.filter((_, i) => i !== index) })}
                className={removeButtonClassName()}
              >
                删除
              </button>
            </div>
          ))}
        </div>
        <button
          onClick={() => update({ policies: [...draft.policies, newPolicy()] })}
          className={addButtonClassName()}
        >
          + 添加策略
        </button>
      </div>

      <div>
        <SectionTitle>内部情况表</SectionTitle>
        <p className="mb-2 text-xs leading-5 text-slate-500">同名 key 以最后一行为准（JSON 对象语义）。</p>
        <div className="space-y-3">
          {draft.internal.map((row, index) => (
            <div key={index} className="grid items-end gap-3 sm:grid-cols-[200px_1fr_auto]">
              <TextField
                label="key"
                ariaLabel={`内部情况 ${index + 1} key`}
                value={row.key}
                onChange={(key) =>
                  update({ internal: draft.internal.map((r, i) => (i === index ? { ...r, key } : r)) })
                }
              />
              <TextField
                label="value"
                ariaLabel={`内部情况 ${index + 1} value`}
                value={row.value}
                onChange={(value) =>
                  update({ internal: draft.internal.map((r, i) => (i === index ? { ...r, value } : r)) })
                }
              />
              <button
                onClick={() => update({ internal: draft.internal.filter((_, i) => i !== index) })}
                className={removeButtonClassName()}
              >
                删除
              </button>
            </div>
          ))}
        </div>
        <button
          onClick={() => update({ internal: [...draft.internal, newInternalRow()] })}
          className={addButtonClassName()}
        >
          + 添加条目
        </button>
      </div>

      {validation && <ValidationIssuesView result={validation} title="变量表校验（后端）" />}
      {saveValidation && <ValidationIssuesView result={saveValidation} title="保存被拒（后端）" />}
      {saveError && (
        <div role="alert" className="rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2">
          <p className="text-sm text-red-300">{saveError}</p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={onSave}
          disabled={saving}
          className="rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-600 disabled:opacity-50"
        >
          {saving ? '保存中…' : saveLabel}
        </button>
        <button
          onClick={onValidate}
          disabled={validating}
          className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-4 py-2 text-sm font-medium text-blue-400 transition-colors hover:bg-blue-500/20 disabled:opacity-50"
        >
          {validating ? '校验中…' : '校验变量表（后端）'}
        </button>
        {dirty && <span className="text-xs text-amber-300">有未保存的更改</span>}
        <span className="text-xs text-slate-500">
          校验只覆盖变量表与公式图；状态字段与策略阈值的检查在保存时由同一后端校验器执行。
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Read-only detail (built-ins) + calibrated provenance
// ---------------------------------------------------------------------------

function isThresholdChange(value: unknown): value is ThresholdChange {
  return (
    typeof value === 'object' &&
    value !== null &&
    'fitted_alert_threshold' in value &&
    'prior_alert_threshold' in value
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

export function TemplateReadView({
  template,
  fit,
}: {
  template: VariableTemplateRead
  fit: CalibrationFitRead | null
}) {
  const metricChanges = fit
    ? Object.values((fit.changes.metrics ?? {}) as Record<string, unknown>).filter(isThresholdChange)
    : []
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
        <KeyValue label="领域" value={domainLabel(template.domain_id) || template.domain_id} />
        <KeyValue label="内置预设" value={template.is_builtin ? '是（只读）' : '否'} />
        <KeyValue label="创建时间" value={template.created_at ?? '—'} />
      </div>
      {template.description && <p className="text-sm leading-6 text-slate-400">{template.description}</p>}

      {fit && (
        <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-3">
          <SectionTitle>校准来源（该版本由拟合生成，源模板未被修改）</SectionTitle>
          <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
            <KeyValue label="拟合记录" value={fit.id} />
            <KeyValue label="源模板" value={fit.source_template_id ?? '—'} />
            <KeyValue label="λ / 种子" value={`${formatNumber(fit.ridge_strength)} / ${fit.seed}`} />
            <KeyValue label="观测数" value={fit.n_observations} />
            <KeyValue label="inputs_hash" value={formatHash(fit.inputs_hash)} />
            <KeyValue label="拟合时间" value={fit.created_at} />
          </div>
          {metricChanges.map((change) => (
            <p key={change.metric} className="mt-1 font-mono text-xs text-slate-300">
              {change.metric}（{change.preferred_direction}）：alert {formatNumber(change.prior_alert_threshold)} →{' '}
              {formatNumber(change.fitted_alert_threshold)}；critical {formatNumber(change.prior_critical_threshold)} →{' '}
              {formatNumber(change.fitted_critical_threshold)}
            </p>
          ))}
        </div>
      )}

      {template.state_fields.length > 0 && (
        <div>
          <SectionTitle>状态默认值</SectionTitle>
          <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
            {template.state_fields.map((field) => (
              <KeyValue key={field.name} label={field.name} value={formatNumber(field.default)} />
            ))}
          </div>
        </div>
      )}

      {Object.keys(template.policies).length > 0 && (
        <div>
          <SectionTitle>策略阈值</SectionTitle>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-3 font-medium">指标</th>
                <th className="py-2 pr-3 font-medium">方向</th>
                <th className="py-2 pr-3 font-medium">alert</th>
                <th className="py-2 font-medium">critical</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {Object.entries(template.policies).map(([metric, spec]: [string, MetricPolicySpec]) => (
                <tr key={metric}>
                  <td className="py-2 pr-3 font-mono text-xs">{metric}</td>
                  <td className="py-2 pr-3 text-xs">{spec.preferred_direction}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{formatNumber(spec.alert_threshold)}</td>
                  <td className="py-2 font-mono text-xs">{formatNumber(spec.critical_threshold)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {template.variables.length > 0 && (
        <div>
          <SectionTitle>变量表</SectionTitle>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-3 font-medium">变量</th>
                <th className="py-2 pr-3 font-medium">单位</th>
                <th className="py-2 pr-3 font-medium">分布</th>
                <th className="py-2 font-medium">出处</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 text-slate-300">
              {template.variables.map((variable) => (
                <tr key={variable.id}>
                  <td className="py-2 pr-3 font-mono text-xs text-slate-200">{variable.id}</td>
                  <td className="py-2 pr-3 text-slate-400">{variable.unit || '—'}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{distributionSummary(variable)}</td>
                  <td className="py-2 text-xs text-slate-400">{variable.evidence_ref || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {template.formulas.length > 0 && (
        <div>
          <SectionTitle>公式图</SectionTitle>
          <div className="space-y-1">
            {template.formulas.map((formula) => (
              <div key={formula.output} className="font-mono text-xs text-slate-300">
                {formula.output} = {JSON.stringify(formula.expression)}
                {formula.description && <span className="ml-2 font-sans text-slate-500">{formula.description}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {Object.keys(template.internal).length > 0 && (
        <div>
          <SectionTitle>内部情况表</SectionTitle>
          <div className="space-y-1">
            {Object.entries(template.internal).map(([key, value]) => (
              <div key={key} className="flex gap-3 text-sm">
                <span className="shrink-0 font-mono text-xs text-slate-500">{key}</span>
                <span className="text-xs leading-5 text-slate-300">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
