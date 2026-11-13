import { describe, expect, it } from 'vitest'

import { customTemplate } from '../../test/engineFixtures'
import {
  draftFromTemplate,
  draftToCreate,
  draftToUpdate,
  draftToVariableSet,
  emptyDraft,
  expressionFromJson,
  expressionToJson,
  knownRefsForFormula,
} from './templateDraft'

describe('templateDraft', () => {
  it('round-trips a stored template through draft and create payload', () => {
    const draft = draftFromTemplate(customTemplate)
    expect(draft.name).toBe('AI line case')
    expect(draft.domain_id).toBe('corporate')
    expect(draft.variables).toHaveLength(2)
    expect(draft.formulas).toHaveLength(1)
    expect(draft.policies).toEqual([
      { metric: 'cash', preferred_direction: 'increase', alert_threshold: 50, critical_threshold: 25 },
    ])
    expect(draft.internal).toEqual([
      { key: 'runway', value: '9 months of cash' },
      { key: 'team', value: '20 people, no ML hire' },
    ])

    const created = draftToCreate(draft)
    expect(created).toMatchObject({
      name: 'AI line case',
      domain_id: 'corporate',
      variables: customTemplate.variables,
      formulas: customTemplate.formulas,
      internal: customTemplate.internal,
    })
    expect(created.policies).toEqual(customTemplate.policies)
    expect(created.state_fields).toEqual(customTemplate.state_fields)
  })

  it('never sends domain_id in an update payload (backend forbids it)', () => {
    const draft = draftFromTemplate(customTemplate)
    const update = draftToUpdate(draft)
    expect('domain_id' in update).toBe(false)
    expect(update.name).toBe('AI line case')
  })

  it('builds a variable set for the pre-save check from the draft', () => {
    const draft = draftFromTemplate(customTemplate)
    const set = draftToVariableSet(draft)
    expect(set.name).toBe('AI line case')
    expect(set.variables).toHaveLength(2)
    expect(set.formulas).toHaveLength(1)
    expect(set.internal).toEqual(customTemplate.internal)
  })

  it('passes cleared required numbers through as null for the backend to report', () => {
    const draft = emptyDraft('corporate')
    draft.state_fields = [{ name: 'cash', description: '', default: null }]
    draft.policies = [{ metric: 'cash', preferred_direction: 'increase', alert_threshold: null, critical_threshold: 25 }]
    const created = draftToCreate(draft)
    expect(created.state_fields[0].default).toBeNull()
    expect(created.policies.cash.alert_threshold).toBeNull()
  })

  it('round-trips expressions through the constrained vocabulary', () => {
    const json = { op: 'divide', args: [{ ref: 'cash' }, 12] }
    const node = expressionFromJson(json)
    expect(node).toEqual({
      kind: 'op',
      op: 'divide',
      args: [
        { kind: 'ref', ref: 'cash' },
        { kind: 'literal', value: 12 },
      ],
    })
    expect(node).not.toBeNull()
    if (node) expect(expressionToJson(node)).toEqual(json)

    expect(expressionFromJson(42)).toEqual({ kind: 'literal', value: 42 })
    expect(expressionToJson({ kind: 'literal', value: null })).toBeNull()
  })

  it('rejects expressions outside the vocabulary', () => {
    expect(expressionFromJson({ op: 'power', args: [1, 2] })).toBeNull()
    expect(expressionFromJson({ op: 'add', args: [1] })).toBeNull()
    expect(expressionFromJson({ op: 'add', args: [1, 2, 3] })).toBeNull()
    expect(expressionFromJson({ op: 'add', args: [1, 2], extra: true })).toBeNull()
    expect(expressionFromJson({ ref: 'cash', extra: 1 })).toBeNull()
    expect(expressionFromJson({ ref: 7 })).toBeNull()
    expect(expressionFromJson('cash')).toBeNull()
    expect(expressionFromJson(true)).toBeNull()
    expect(expressionFromJson([1, 2])).toBeNull()
    expect(expressionFromJson(null)).toBeNull()
    expect(expressionFromJson({ op: 'add', args: [{ ref: 'cash' }, 'nope'] })).toBeNull()
  })

  it('offers only sampled variables and earlier formulas as refs', () => {
    const draft = draftFromTemplate(customTemplate)
    draft.formulas = [
      { output: 'runway_months', expression: 0, description: '' },
      { output: 'runway_years', expression: 0, description: '' },
    ]
    expect(knownRefsForFormula(draft, 0)).toEqual(['cash', 'cac'])
    expect(knownRefsForFormula(draft, 1)).toEqual(['cash', 'cac', 'runway_months'])
  })
})
