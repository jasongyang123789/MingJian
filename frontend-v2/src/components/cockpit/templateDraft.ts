// Draft state for the variable-template editor, and the conversions
// between drafts and the backend payloads. Pure data shaping only: no
// validation lives here — the backend validator is the arbiter, and
// the editor sends exactly what the author entered (including empty
// fields) so the backend's structured issues are what the author sees.

import type {
  DistributionType,
  FormulaDefinition,
  FormulaOperator,
  VariableDefinition,
  VariableDistribution,
  VariableSet,
  VariableTemplate,
  VariableTemplateCreate,
  VariableTemplateUpdate,
} from '../../api/engineTypes'

export const DISTRIBUTION_TYPES: DistributionType[] = [
  'fixed',
  'normal',
  'triangular',
  'beta_pert',
  'bernoulli',
]

export const FORMULA_OPERATORS: FormulaOperator[] = [
  'add',
  'subtract',
  'multiply',
  'divide',
  'min',
  'max',
]

/** Numeric distribution parameters (every key of the distribution except `type`). */
export type DistributionParamKey = Exclude<keyof VariableDistribution, 'type'>

/** Distribution parameters relevant to each type (backend vocabulary). */
export const DISTRIBUTION_PARAMS: Record<DistributionType, DistributionParamKey[]> = {
  fixed: ['value'],
  normal: ['mean', 'std'],
  triangular: ['min', 'mode', 'max'],
  beta_pert: ['min', 'mode', 'max'],
  bernoulli: ['p'],
}

export const DISTRIBUTION_PARAM_LABELS: Record<string, string> = {
  value: '值',
  mean: '均值',
  std: '标准差',
  min: '最小值',
  mode: '众数',
  max: '最大值',
  p: '概率 p',
}

export interface StateFieldDraft {
  name: string
  description: string
  default: number | null
}

export interface PolicyDraft {
  metric: string
  preferred_direction: string
  alert_threshold: number | null
  critical_threshold: number | null
}

export interface InternalDraft {
  key: string
  value: string
}

export interface TemplateDraft {
  name: string
  domain_id: string
  description: string
  state_fields: StateFieldDraft[]
  policies: PolicyDraft[]
  variables: VariableDefinition[]
  formulas: FormulaDefinition[]
  internal: InternalDraft[]
}

export function emptyDistribution(type: DistributionType): VariableDistribution {
  return { type, value: null, mean: null, std: null, min: null, mode: null, max: null, p: null }
}

export function newVariable(): VariableDefinition {
  return {
    id: '',
    unit: '',
    distribution: emptyDistribution('fixed'),
    evidence_ref: '',
    description: '',
    scope_tags: [],
  }
}

export function newStateField(): StateFieldDraft {
  return { name: '', description: '', default: null }
}

export function newPolicy(): PolicyDraft {
  return { metric: '', preferred_direction: 'increase', alert_threshold: null, critical_threshold: null }
}

export function newFormula(): FormulaDefinition {
  return { output: '', expression: 0, description: '' }
}

export function newInternalRow(): InternalDraft {
  return { key: '', value: '' }
}

export function emptyDraft(domainId: string): TemplateDraft {
  return {
    name: '',
    domain_id: domainId,
    description: '',
    state_fields: [],
    policies: [],
    variables: [],
    formulas: [],
    internal: [],
  }
}

export function draftFromTemplate(template: VariableTemplate): TemplateDraft {
  return {
    name: template.name,
    domain_id: template.domain_id,
    description: template.description,
    state_fields: template.state_fields.map((field) => ({ ...field })),
    policies: Object.entries(template.policies)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([metric, spec]) => ({ metric, ...spec })),
    variables: template.variables.map((variable) => ({
      ...variable,
      distribution: { ...variable.distribution },
      scope_tags: [...variable.scope_tags],
    })),
    formulas: template.formulas.map((formula) => ({ ...formula })),
    internal: Object.entries(template.internal).map(([key, value]) => ({ key, value })),
  }
}

function internalToRecord(rows: InternalDraft[]): Record<string, string> {
  const record: Record<string, string> = {}
  for (const row of rows) record[row.key] = row.value
  return record
}

function policiesToRecord(rows: PolicyDraft[]): Record<string, { preferred_direction: string; alert_threshold: number | null; critical_threshold: number | null }> {
  const record: Record<string, { preferred_direction: string; alert_threshold: number | null; critical_threshold: number | null }> = {}
  for (const row of rows) {
    record[row.metric] = {
      preferred_direction: row.preferred_direction,
      alert_threshold: row.alert_threshold,
      critical_threshold: row.critical_threshold,
    }
  }
  return record
}

/**
 * The variable set the pre-save check validates. Covers variables +
 * formulas + internal only — template-level checks (state fields,
 * policy ordering) run on save, through the same backend validator.
 */
export function draftToVariableSet(draft: TemplateDraft): VariableSet {
  return {
    name: draft.name,
    variables: draft.variables,
    formulas: draft.formulas,
    internal: internalToRecord(draft.internal),
  }
}

// The create/update payloads are assembled from the draft verbatim,
// including nulls for cleared required numbers: the backend reports
// those as 422 shape errors naming the field, which the editor shows
// inline. The cast marks the one place where the draft's nullable
// numbers cross into the backend's non-nullable payload types —
// deliberately, so nothing is silently defaulted client-side.
export function draftToCreate(draft: TemplateDraft): VariableTemplateCreate {
  return {
    name: draft.name,
    domain_id: draft.domain_id,
    description: draft.description,
    state_fields: draft.state_fields,
    policies: policiesToRecord(draft.policies),
    variables: draft.variables,
    formulas: draft.formulas,
    internal: internalToRecord(draft.internal),
  } as VariableTemplateCreate
}

export function draftToUpdate(draft: TemplateDraft): VariableTemplateUpdate {
  return {
    name: draft.name,
    description: draft.description,
    state_fields: draft.state_fields,
    policies: policiesToRecord(draft.policies),
    variables: draft.variables,
    formulas: draft.formulas,
    internal: internalToRecord(draft.internal),
  } as VariableTemplateUpdate
}

/** Stable serialization for dirty-state comparison. */
export function draftKey(draft: TemplateDraft): string {
  return JSON.stringify(draft)
}

// ---------------------------------------------------------------------------
// Formula expressions: the constrained vocabulary as an editable tree.
// ---------------------------------------------------------------------------

export type ExpressionNode =
  | { kind: 'literal'; value: number | null }
  | { kind: 'ref'; ref: string }
  | { kind: 'op'; op: FormulaOperator; args: [ExpressionNode, ExpressionNode] }

export function expressionToJson(node: ExpressionNode): unknown {
  switch (node.kind) {
    case 'literal':
      return node.value
    case 'ref':
      return { ref: node.ref }
    case 'op':
      return { op: node.op, args: [expressionToJson(node.args[0]), expressionToJson(node.args[1])] }
  }
}

/**
 * Parse stored JSON into the editable tree. Returns null for anything
 * outside the vocabulary (wrong arity, unknown operator, non-number
 * literal, extra keys) — the editor then shows the raw JSON read-only
 * and round-trips it untouched, since the backend can never have
 * stored such an expression through validation.
 */
export function expressionFromJson(value: unknown): ExpressionNode | null {
  if (typeof value === 'number') return { kind: 'literal', value }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, unknown>
  const keys = Object.keys(record)
  if (keys.length === 1 && keys[0] === 'ref' && typeof record.ref === 'string') {
    return { kind: 'ref', ref: record.ref }
  }
  if (keys.length === 2 && 'op' in record && 'args' in record) {
    const op = record.op
    const args = record.args
    if (
      typeof op === 'string' &&
      (FORMULA_OPERATORS as string[]).includes(op) &&
      Array.isArray(args) &&
      args.length === 2
    ) {
      const left = expressionFromJson(args[0])
      const right = expressionFromJson(args[1])
      if (left && right) {
        return { kind: 'op', op: op as FormulaOperator, args: [left, right] }
      }
    }
  }
  return null
}

/**
 * Ids a formula may reference: sampled variable ids plus the outputs
 * of EARLIER formulas only (list order is the topological order, so
 * forward references — and therefore cycles — are impossible).
 */
export function knownRefsForFormula(draft: TemplateDraft, formulaIndex: number): string[] {
  const refs = draft.variables.map((variable) => variable.id).filter((id) => id.length > 0)
  for (let index = 0; index < formulaIndex; index += 1) {
    const output = draft.formulas[index].output
    if (output.length > 0) refs.push(output)
  }
  return refs
}
