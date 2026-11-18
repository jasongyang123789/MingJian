import { describe, expect, it } from 'vitest'

import {
  ORIGIN_LABELS,
  STATUS_LABELS,
  originLabel,
  parseOverrideRecord,
  parseProposalRecord,
  shortHash,
  statusLabel,
} from './directionMappingDisplay'

describe('mapping origin labels', () => {
  it('labels every backend origin distinctly, never manual for a proposal', () => {
    expect(ORIGIN_LABELS).toEqual({
      derived: '推导',
      authored: '手动',
      llm_proposal: 'LLM 提案',
      override: '变量覆盖',
    })
    expect(originLabel('llm_proposal')).toBe('LLM 提案')
    expect(originLabel('llm_proposal')).not.toBe('手动')
    expect(originLabel('override')).toBe('变量覆盖')
    expect(originLabel('derived')).toBe('推导')
    expect(originLabel('authored')).toBe('手动')
  })

  it('falls back to the raw value for unknown origins instead of mislabeling', () => {
    expect(originLabel('something_new')).toBe('something_new')
    expect(originLabel(null)).toBe('')
    expect(originLabel(undefined)).toBe('')
    expect(originLabel('')).toBe('')
  })
})

describe('mapping status labels', () => {
  it('labels every backend status distinctly', () => {
    expect(STATUS_LABELS).toEqual({
      active: '可用',
      proposed: '待评审',
      rejected: '已拒绝',
    })
    expect(statusLabel('proposed')).toBe('待评审')
    expect(statusLabel('rejected')).toBe('已拒绝')
    expect(statusLabel('active')).toBe('可用')
  })

  it('falls back to the raw value for unknown statuses', () => {
    expect(statusLabel('archived')).toBe('archived')
    expect(statusLabel(null)).toBe('')
    expect(statusLabel(undefined)).toBe('')
  })
})

describe('parseProposalRecord', () => {
  it('reads the full record the backend pins on proposal rows', () => {
    const summary = parseProposalRecord({
      rationale: 'Cash is the binding constraint.',
      key_variables: ['cash', 'burn'],
      model: 'gpt-6.1-sol',
      template_id: 'direction.propose',
      template_version: '1',
      proposal_hash: 'sha256:abcdef1234567890',
    })
    expect(summary).toEqual({
      rationale: 'Cash is the binding constraint.',
      keyVariables: ['cash', 'burn'],
      model: 'gpt-6.1-sol',
      templateId: 'direction.propose',
      templateVersion: '1',
      proposalHash: 'sha256:abcdef1234567890',
    })
  })

  it('returns null when the row carries no proposal record', () => {
    expect(parseProposalRecord(null)).toBeNull()
    expect(parseProposalRecord(undefined)).toBeNull()
  })

  it('drops malformed fields instead of rendering them raw', () => {
    const summary = parseProposalRecord({
      rationale: 42,
      key_variables: ['cash', 7, null],
      model: '',
      proposal_hash: ['not', 'a', 'string'],
    })
    expect(summary).toEqual({
      rationale: null,
      keyVariables: ['cash'],
      model: null,
      templateId: null,
      templateVersion: null,
      proposalHash: null,
    })
  })
})

describe('parseOverrideRecord', () => {
  it('reads overrides in variable-id order with branch and fork step', () => {
    const summary = parseOverrideRecord({
      overrides: { burn: 20, cash: 80 },
      branch_id: 'branch-1',
      fork_step: 2,
      override_hash: 'sha256:overridehash',
    })
    expect(summary).toEqual({
      overrides: [
        { variableId: 'burn', value: 20 },
        { variableId: 'cash', value: 80 },
      ],
      branchId: 'branch-1',
      forkStep: 2,
      overrideHash: 'sha256:overridehash',
    })
  })

  it('returns null when the row carries no override record', () => {
    expect(parseOverrideRecord(null)).toBeNull()
    expect(parseOverrideRecord(undefined)).toBeNull()
  })

  it('drops non-finite override values', () => {
    const summary = parseOverrideRecord({
      overrides: { cash: 80, junk: 'eighty', nan: Number.NaN, inf: Number.POSITIVE_INFINITY },
      fork_step: 'two',
    })
    expect(summary?.overrides).toEqual([{ variableId: 'cash', value: 80 }])
    expect(summary?.forkStep).toBeNull()
  })
})

describe('shortHash', () => {
  it('truncates long hashes and passes short values through', () => {
    expect(shortHash('sha256:abcdef1234567890abcdef')).toBe('sha256:abcdef1234567…')
    expect(shortHash('abc')).toBe('abc')
  })
})
