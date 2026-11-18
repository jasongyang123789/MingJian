import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  derivationRead,
  directionMappingAuthored,
  directionMappingDerived,
  directionMappingOverride,
  directionMappingProposed,
  directionMappingRejected,
  narrativeRead,
} from '../test/engineFixtures'
import Directions from './Directions'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const RUNS = [
  { id: 'run-anchor', status: 'COMPLETED', domain_id: 'corporate', company_id: 'acme', created_at: '2026-01-01T00:00:00Z', tick_count: 2 },
  { id: 'run-other', status: 'COMPLETED', domain_id: 'corporate', company_id: 'acme', created_at: '2026-01-02T00:00:00Z', tick_count: 2 },
]

const MECE = {
  run_id: 'run-anchor',
  decomposition: {
    topic: 'Should we launch?',
    root: {
      name: 'Should we launch?',
      scope: ['demand', 'cost'],
      children: [
        { name: 'Demand', scope: ['demand'], children: [] },
        { name: 'Cost', scope: ['cost'], children: [] },
      ],
    },
  },
  validation: { is_mece: true, checks: [], issues: [], scope_tag_count: 2, branch_count: 3 },
}

const VARIABLES = {
  run_id: 'run-anchor',
  template: null,
  bindings: {
    name: 'anchor-bindings',
    variables: [
      { id: 'cash', unit: 'USD', distribution: { type: 'normal', value: null, mean: 10, std: 2, min: null, mode: null, max: null, p: null }, evidence_ref: 'finance-2026', description: 'Cash on hand', scope_tags: ['demand'] },
      { id: 'burn', unit: 'USD/mo', distribution: { type: 'fixed', value: 20, mean: null, std: null, min: null, mode: null, max: null, p: null }, evidence_ref: 'finance-2026', description: 'Monthly burn', scope_tags: ['cost'] },
    ],
    formulas: [],
    internal: {},
  },
  validation: { is_valid: true, variable_count: 2, checks: [], issues: [] },
}

describe('Directions', () => {
  let narratives: unknown[]
  let mappings: unknown[]
  let generateResponse: { status: number; body: unknown } | null
  let polishResponse: { status: number; body: unknown } | null
  let deriveResponse: { status: number; body: unknown } | null
  let reviewResponse: { status: number; body: unknown } | null
  let variablesResponse: { status: number; body: unknown } | null
  let overrideResponse: { status: number; body: unknown } | null
  let reforkResponse: { status: number; body: unknown } | null
  const posted: { url: string; body: unknown }[] = []

  beforeEach(() => {
    vi.restoreAllMocks()
    narratives = []
    mappings = []
    generateResponse = null
    polishResponse = null
    deriveResponse = null
    reviewResponse = null
    variablesResponse = null
    overrideResponse = null
    reforkResponse = null
    posted.length = 0
    vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/simulation/runs') return jsonResponse(RUNS)
      if (url === '/api/runs/run-anchor/mece') return jsonResponse(MECE)
      if (url === '/api/runs/run-other/mece') return jsonResponse({ detail: 'not found' }, 404)
      if (url === '/api/runs/run-anchor/variables' && method === 'GET') {
        if (variablesResponse) return jsonResponse(variablesResponse.body, variablesResponse.status)
        return jsonResponse(VARIABLES)
      }
      if (method === 'POST' && url === '/api/runs/run-anchor/directions/override') {
        const body = init?.body ? JSON.parse(String(init.body)) : null
        posted.push({ url, body })
        if (overrideResponse) return jsonResponse(overrideResponse.body, overrideResponse.status)
        const directions = (body?.directions ?? []) as Array<Record<string, unknown>>
        const outcomes = directions.map((spec, i) => ({
          name: spec.name,
          status: 'stored',
          reason: `Child run run-child-${i + 1} created (branch branch-${i + 1}, fork step ${(spec.fork_step as number) ?? 1}, status COMPLETED). No ensemble yet: run POST /runs/run-child-${i + 1}/monte-carlo before generating from this direction.`,
          mapping_id: `mapping-new-${i}`,
          branch_id: `branch-${i + 1}`,
          child_run_id: `run-child-${i + 1}`,
          fork_step: (spec.fork_step as number) ?? 1,
          child_status: 'COMPLETED',
          arm: spec.arm,
          mece_branches: spec.mece_branches,
        }))
        const newMappings = directions.map((spec, i) => ({
          id: `mapping-new-${i}`,
          anchor_run_id: 'run-anchor',
          name: spec.name,
          source_run_id: `run-child-${i + 1}`,
          arm: spec.arm,
          mece_branches: spec.mece_branches,
          deliberation_id: null,
          origin: 'override',
          rule_id: null,
          rules_version: null,
          rule_record: null,
          status: 'active',
          proposal_record: null,
          override_record: {
            overrides: spec.overrides,
            branch_id: `branch-${i + 1}`,
            fork_step: (spec.fork_step as number) ?? 1,
            override_hash: 'sha256:override-test',
          },
          user_edited: false,
          position: mappings.length + i,
          created_at: '2026-11-18T00:00:00Z',
          updated_at: '2026-11-18T00:00:00Z',
        }))
        mappings = [...mappings, ...newMappings]
        return jsonResponse(
          { anchor_run_id: 'run-anchor', override_hash: 'sha256:override-test', directions_considered: directions.length, outcomes, mappings },
          201,
        )
      }
      if (url === '/api/runs/run-anchor/directions/mappings' && method === 'GET') {
        return jsonResponse({ run_id: 'run-anchor', mappings })
      }
      if (method === 'POST' && url === '/api/runs/run-anchor/directions/derive') {
        if (deriveResponse) return jsonResponse(deriveResponse.body, deriveResponse.status)
        mappings = [...derivationRead.mappings]
        return jsonResponse(derivationRead)
      }
      if (method === 'PUT' && url.startsWith('/api/runs/run-anchor/directions/mappings/')) {
        const body = init?.body ? JSON.parse(String(init.body)) : null
        posted.push({ url, body })
        const id = url.split('/').pop()
        mappings = (mappings as Record<string, unknown>[]).map((mapping) =>
          mapping.id === id ? { ...mapping, ...body, user_edited: true } : mapping,
        )
        const updated = (mappings as Record<string, unknown>[]).find(
          (mapping) => mapping.id === id,
        )
        return updated ? jsonResponse(updated) : jsonResponse({ detail: 'not found' }, 404)
      }
      if (method === 'DELETE' && url.startsWith('/api/runs/run-anchor/directions/mappings/')) {
        posted.push({ url, body: null })
        const id = url.split('/').pop()
        mappings = (mappings as Record<string, unknown>[]).filter(
          (mapping) => mapping.id !== id,
        )
        return new Response(null, { status: 204 })
      }
      if (
        method === 'POST' &&
        /^\/api\/runs\/run-anchor\/directions\/mappings\/[^/]+\/(accept|reject)$/.test(url)
      ) {
        posted.push({ url, body: null })
        if (reviewResponse) return jsonResponse(reviewResponse.body, reviewResponse.status)
        const parts = url.split('/')
        const id = parts[parts.length - 2]
        const action = parts[parts.length - 1]
        mappings = (mappings as Record<string, unknown>[]).map((mapping) =>
          mapping.id === id
            ? { ...mapping, status: action === 'accept' ? 'active' : 'rejected' }
            : mapping,
        )
        const updated = (mappings as Record<string, unknown>[]).find(
          (mapping) => mapping.id === id,
        )
        return updated ? jsonResponse(updated) : jsonResponse({ detail: 'not found' }, 404)
      }
      if (
        method === 'POST' &&
        /^\/api\/runs\/run-anchor\/directions\/mappings\/[^/]+\/refork$/.test(url)
      ) {
        const body = init?.body ? JSON.parse(String(init.body)) : null
        posted.push({ url, body })
        if (reforkResponse) return jsonResponse(reforkResponse.body, reforkResponse.status)
        const parts = url.split('/')
        const id = parts[parts.length - 2]
        const existing = (mappings as Record<string, unknown>[]).find(
          (mapping) => mapping.id === id,
        )
        if (!existing) return jsonResponse({ detail: 'not found' }, 404)
        const record = {
          overrides: (body as Record<string, unknown>).overrides,
          branch_id: 'branch-refork',
          fork_step: (body as Record<string, unknown>).fork_step ?? 1,
          override_hash: 'sha256:refork-test',
        }
        mappings = (mappings as Record<string, unknown>[]).map((mapping) =>
          mapping.id === id
            ? {
                ...mapping,
                source_run_id: 'run-child-refork',
                override_record: record,
                user_edited: true,
              }
            : mapping,
        )
        const updated = (mappings as Record<string, unknown>[]).find(
          (mapping) => mapping.id === id,
        )
        return jsonResponse(
          {
            mapping: updated,
            branch_id: 'branch-refork',
            child_run_id: 'run-child-refork',
            fork_step: (body as Record<string, unknown>).fork_step ?? 1,
            child_status: 'COMPLETED',
            override_hash: 'sha256:refork-test',
            reason: 'Child run run-child-refork created. No ensemble yet.',
          },
          201,
        )
      }
      if (url === '/api/runs/run-anchor/narratives' && method === 'GET') {
        return jsonResponse({ run_id: 'run-anchor', narratives })
      }
      if (url === '/api/runs/run-other/narratives' && method === 'GET') {
        return jsonResponse({ run_id: 'run-other', narratives: [] })
      }
      if (method === 'POST' && url === '/api/runs/run-anchor/narratives') {
        posted.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        if (generateResponse) {
          if (generateResponse.status === 201) {
            narratives = [generateResponse.body, ...narratives]
          }
          return jsonResponse(generateResponse.body, generateResponse.status)
        }
        const created = { ...narrativeRead, version: narratives.length + 1 }
        narratives = [created, ...narratives]
        return jsonResponse(created, 201)
      }
      if (method === 'POST' && url.endsWith('/polish')) {
        posted.push({ url, body: null })
        if (polishResponse) return jsonResponse(polishResponse.body, polishResponse.status)
        return jsonResponse(
          { id: 'polish-1', narrative_id: 'narrative-1', model: 'fixture', template_id: 'narrative.polish', template_version: '1', polished_markdown: '# Polished', created_at: '2026-11-15T11:00:00Z' },
          201,
        )
      }
      return jsonResponse({ detail: `unexpected ${method} ${url}` }, 404)
    })
  })

  function renderPage() {
    return render(
      <MemoryRouter>
        <Directions />
      </MemoryRouter>,
    )
  }

  async function pickAnchorRun() {
    fireEvent.change(await screen.findByLabelText('锚定 Run'), { target: { value: 'run-anchor' } })
    await screen.findByRole('button', { name: '生成简报' })
  }

  async function expandOverrideForm() {
    fireEvent.click(await screen.findByRole('button', { name: '新建变量覆盖方向' }))
    await screen.findByLabelText('覆盖方向名称')
  }

  it('asks for a run, then shows the generate form with MECE branch checkboxes', async () => {
    renderPage()
    expect(await screen.findByText('请选择一个锚定 Run')).toBeTruthy()
    await pickAnchorRun()
    expect(screen.getByLabelText('方向名称')).toBeTruthy()
    expect(screen.getByText('Demand')).toBeTruthy()
    expect(screen.getByText('Cost')).toBeTruthy()
    expect(screen.getByText('尚无简报')).toBeTruthy()
  })

  it('generates a narrative with the drafted directions and shows the reading view', async () => {
    renderPage()
    await pickAnchorRun()
    fireEvent.change(screen.getByLabelText('方向名称'), { target: { value: 'Go all in' } })
    fireEvent.click(screen.getByText('Demand'))
    fireEvent.click(screen.getByRole('button', { name: '生成简报' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0].body).toEqual({
      topic: null,
      directions: [
        { name: 'Go all in', source_run_id: 'run-anchor', arm: 'baseline', mece_branches: ['Demand'], deliberation_id: null },
      ],
      loop_id: null,
    })
    expect(await screen.findByText('方向 1：Go all in')).toBeTruthy()
    expect(screen.getByText(/P10 2 \/ P50 10 \/ P90 18/)).toBeTruthy()
  })

  it('surfaces a refusal code and message instead of inventing a narrative', async () => {
    generateResponse = {
      status: 400,
      body: { detail: { code: 'narrative_requires_ensemble', message: 'Run POST /runs/run-anchor/monte-carlo first.' } },
    }
    renderPage()
    await pickAnchorRun()
    fireEvent.change(screen.getByLabelText('方向名称'), { target: { value: 'Go all in' } })
    fireEvent.click(screen.getByRole('button', { name: '生成简报' }))
    expect(await screen.findByText(/narrative_requires_ensemble/)).toBeTruthy()
    expect(screen.getByText(/monte-carlo first/)).toBeTruthy()
    expect(screen.queryByText('方向 1：Go all in')).toBeNull()
  })

  it('lists versions newest first and switches between them', async () => {
    const v1 = { ...narrativeRead, id: 'narrative-v1', version: 1, topic: 'First draft', body: { ...narrativeRead.body, topic: 'First draft' } }
    const v2 = { ...narrativeRead, id: 'narrative-v2', version: 2, topic: 'Second draft', body: { ...narrativeRead.body, topic: 'Second draft' } }
    narratives = [v2, v1]
    renderPage()
    await pickAnchorRun()
    const buttons = await screen.findAllByRole('button', { name: /v[12] ·/ })
    expect(buttons.map((button) => button.textContent)).toEqual(['v2 · Second draft', 'v1 · First draft'])
    expect(screen.getByText('简报：Second draft')).toBeTruthy()
    fireEvent.click(buttons[1])
    expect(screen.getByText('简报：First draft')).toBeTruthy()
  })

  it('shows an honest notice when polish is unavailable', async () => {
    narratives = [narrativeRead]
    polishResponse = {
      status: 503,
      body: { detail: { code: 'narrative_polish_unavailable', message: 'No LLM service is configured.' } },
    }
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText('方向 1：Go all in')).toBeTruthy()
    fireEvent.click(screen.getByText('请求润色'))
    expect(await screen.findByText(/LLM 未配置，无法润色/)).toBeTruthy()
    expect(screen.getByText(/# 决策方向简报：Launch decision/)).toBeTruthy()
  })

  it('derives directions, shows every rule outcome, and lists the written mappings', async () => {
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByRole('button', { name: '推导方向' }))
    expect(await screen.findByText(/规则版本 derivation-rules-v1/)).toBeTruthy()
    expect(screen.getByText(/场景家族 2 个 Run/)).toBeTruthy()
    expect(screen.getByText(/已选 run-anchor \/ strategy/)).toBeTruthy()
    expect(screen.getByText(/与规则 最高 P50 重复/)).toBeTruthy()
    expect(await screen.findByText('Highest P50')).toBeTruthy()
  })

  it('surfaces a derive refusal with its code and message', async () => {
    deriveResponse = {
      status: 400,
      body: { detail: { code: 'direction_no_ensemble', message: 'Run POST /runs/run-anchor/monte-carlo first.' } },
    }
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByRole('button', { name: '推导方向' }))
    expect(await screen.findByText(/direction_no_ensemble/)).toBeTruthy()
    expect(screen.getByText(/monte-carlo first/)).toBeTruthy()
  })

  it('edits a mapping inline and sends the rename with re-pointing', async () => {
    mappings = [directionMappingDerived]
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText('Highest P50')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    fireEvent.change(screen.getByLabelText('映射名称'), { target: { value: 'My rename' } })
    fireEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0]).toEqual({
      url: '/api/runs/run-anchor/directions/mappings/mapping-1',
      body: { name: 'My rename', source_run_id: 'run-anchor', arm: 'strategy' },
    })
    expect(await screen.findByText('My rename')).toBeTruthy()
  })

  it('deletes a mapping only after two-step confirmation', async () => {
    mappings = [directionMappingDerived, directionMappingAuthored]
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText('My pick')).toBeTruthy()
    const deleteButtons = screen.getAllByRole('button', { name: '删除' })
    fireEvent.click(deleteButtons[1])
    expect(await screen.findByText('确认删除「My pick」？')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '确认删除' }))
    await waitFor(() => expect(screen.queryByText('My pick')).toBeNull())
    expect(screen.getByText('Highest P50')).toBeTruthy()
  })

  it('generates from stored mappings without a directions key and shows which were used', async () => {
    mappings = [directionMappingDerived]
    generateResponse = {
      status: 201,
      body: { ...narrativeRead, direction_mapping_ids: ['mapping-1'] },
    }
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByLabelText(/使用已存方向映射生成/))
    expect(screen.getByText(/将使用的映射：Highest P50/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '生成简报' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0].body).toEqual({ topic: null, loop_id: null })
    expect(await screen.findByText('本简报使用了已存映射：Highest P50')).toBeTruthy()
  })

  it('disables generate-from-stored while no mappings exist', async () => {
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByLabelText(/使用已存方向映射生成/))
    expect(screen.getByText(/还没有已存方向映射/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '生成简报' })).toHaveProperty('disabled', true)
  })

  it('shows proposed mappings in the review queue with grounding, never labeled manual', async () => {
    mappings = [directionMappingProposed, directionMappingDerived]
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText('待评审提案')).toBeTruthy()
    expect(screen.getByText(/关键变量：cash、burn/)).toBeTruthy()
    expect(screen.getByText(/Cash is the binding constraint/)).toBeTruthy()
    expect(screen.getByText(/模型 gpt-6.1-sol/)).toBeTruthy()
    expect(screen.getByText(/模板 direction\.propose v1/)).toBeTruthy()
    expect(screen.getByText(/提案哈希 sha256:propose000000/)).toBeTruthy()
    expect(screen.getByText(/回溯分支：Demand/)).toBeTruthy()
    // The proposal appears in the queue and in the stored list.
    expect(screen.getAllByText('Boost cash')).toHaveLength(2)
    expect(screen.getAllByText(/LLM 提案 · 待评审/)).toHaveLength(2)
    expect(screen.queryByText(/手动/)).toBeNull()
  })

  it('shows the decision gates of a proposal in the review queue', async () => {
    const gated = {
      ...directionMappingProposed,
      proposal_record: {
        ...directionMappingProposed.proposal_record,
        template_version: '2',
        gates: [
          {
            variable_id: 'cash',
            comparison: '>=',
            threshold: 90,
            basis: 'Anchor baseline P50 of cash is 100.',
          },
          {
            variable_id: 'burn',
            comparison: '<',
            threshold: 5,
            basis: 'Anchor strategy P50 of cash is 95.',
          },
        ],
      },
    }
    mappings = [gated, directionMappingDerived]
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText('决策门槛：')).toBeTruthy()
    expect(screen.getByText(/cash >= 90/)).toBeTruthy()
    expect(screen.getByText(/依据：Anchor baseline P50 of cash is 100/)).toBeTruthy()
    expect(screen.getByText(/burn < 5/)).toBeTruthy()
    expect(screen.getByText(/依据：Anchor strategy P50 of cash is 95/)).toBeTruthy()
    expect(screen.queryByText('决策门槛：无')).toBeNull()
  })

  it('shows an honest no-gates line for a v1 proposal record', async () => {
    mappings = [directionMappingProposed, directionMappingDerived]
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText('待评审提案')).toBeTruthy()
    expect(screen.getByText('决策门槛：无')).toBeTruthy()
  })

  it('shows an empty review queue when nothing is proposed', async () => {
    mappings = [directionMappingDerived]
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText('暂无待评审提案。')).toBeTruthy()
  })

  it('accepts a proposal, posts to the accept endpoint, and moves it out of the queue', async () => {
    mappings = [directionMappingProposed]
    renderPage()
    await pickAnchorRun()
    fireEvent.click(await screen.findByRole('button', { name: '接受提案「Boost cash」' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0]).toEqual({
      url: '/api/runs/run-anchor/directions/mappings/mapping-3/accept',
      body: null,
    })
    await waitFor(() => expect(screen.getAllByText('Boost cash')).toHaveLength(1))
    expect(screen.getByText('暂无待评审提案。')).toBeTruthy()
    expect(screen.getByText(/LLM 提案 · 可用/)).toBeTruthy()
  })

  it('rejects a proposal only after two-step confirmation, and shows it as rejected', async () => {
    mappings = [directionMappingProposed]
    renderPage()
    await pickAnchorRun()
    fireEvent.click(await screen.findByRole('button', { name: '拒绝提案「Boost cash」' }))
    expect(await screen.findByText(/确认拒绝「Boost cash」/)).toBeTruthy()
    expect(posted).toHaveLength(0)
    fireEvent.click(screen.getByRole('button', { name: '确认拒绝提案「Boost cash」' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0].url).toBe('/api/runs/run-anchor/directions/mappings/mapping-3/reject')
    await waitFor(() => expect(screen.getAllByText('Boost cash')).toHaveLength(1))
    expect(screen.getByText('暂无待评审提案。')).toBeTruthy()
    expect(screen.getByText(/LLM 提案 · 已拒绝/)).toBeTruthy()
  })

  it('surfaces a review refusal with its code and keeps the proposal queued', async () => {
    mappings = [directionMappingProposed]
    reviewResponse = {
      status: 400,
      body: {
        detail: {
          code: 'direction_mapping_not_proposed',
          message: "Mapping 'Boost cash' has status 'rejected'; only proposed mappings can be accepted.",
        },
      },
    }
    renderPage()
    await pickAnchorRun()
    fireEvent.click(await screen.findByRole('button', { name: '接受提案「Boost cash」' }))
    expect(await screen.findByText(/direction_mapping_not_proposed/)).toBeTruthy()
    expect(screen.getByText(/only proposed mappings can be accepted/)).toBeTruthy()
    expect(screen.getAllByText('Boost cash')).toHaveLength(2)
  })

  it('labels every mapping origin and status in the stored list', async () => {
    mappings = [
      directionMappingDerived,
      directionMappingAuthored,
      directionMappingProposed,
      directionMappingRejected,
      directionMappingOverride,
    ]
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText('Highest P50')).toBeTruthy()
    expect(screen.getByText(/推导 · 可用/)).toBeTruthy()
    expect(screen.getByText(/手动 · 可用 · 已编辑/)).toBeTruthy()
    expect(screen.getByText(/LLM 提案 · 已拒绝/)).toBeTruthy()
    expect(screen.getByText(/变量覆盖 · 可用/)).toBeTruthy()
    expect(screen.getByText(/变量覆盖：cash=80 · 分叉步 2/)).toBeTruthy()
  })

  it('generates from stored mappings using only active rows', async () => {
    mappings = [directionMappingProposed, directionMappingDerived]
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByLabelText(/使用已存方向映射生成/))
    expect(screen.getByText(/将使用的映射：Highest P50/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '生成简报' })).toHaveProperty('disabled', false)
  })

  it('disables generate-from-stored while no mapping is active', async () => {
    mappings = [directionMappingProposed]
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByLabelText(/使用已存方向映射生成/))
    expect(screen.getByText(/都不在可用状态/)).toBeTruthy()
    expect(screen.getByRole('button', { name: '生成简报' })).toHaveProperty('disabled', true)
  })

  it('shows the override form with bound variables and their current definitions', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    expect(screen.getByRole('option', { name: 'cash · USD · normal(μ=10, σ=2)' })).toBeTruthy()
    expect(screen.getByRole('option', { name: 'burn · USD/mo · fixed = 20' })).toBeTruthy()
    expect(screen.getByLabelText(/分叉步/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    expect(screen.getByText(/Cash on hand/)).toBeTruthy()
    expect(screen.getByText(/证据：finance-2026/)).toBeTruthy()
  })

  it('filters the variable picker by typed text and restores all options when cleared', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    const filter = screen.getByLabelText('筛选变量')
    fireEvent.change(filter, { target: { value: 'bur' } })
    expect(screen.queryByRole('option', { name: 'cash · USD · normal(μ=10, σ=2)' })).toBeNull()
    expect(screen.getByRole('option', { name: 'burn · USD/mo · fixed = 20' })).toBeTruthy()
    fireEvent.change(filter, { target: { value: '' } })
    expect(screen.getByRole('option', { name: 'cash · USD · normal(μ=10, σ=2)' })).toBeTruthy()
    expect(screen.getByRole('option', { name: 'burn · USD/mo · fixed = 20' })).toBeTruthy()
  })

  it('matches the picker filter against descriptions case-insensitively, and picking a filtered variable shows its definition', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('筛选变量'), { target: { value: 'MONTHLY' } })
    expect(screen.queryByRole('option', { name: 'cash · USD · normal(μ=10, σ=2)' })).toBeNull()
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'burn' } })
    expect(screen.getByText(/Monthly burn/)).toBeTruthy()
    expect(screen.getByText(/证据：finance-2026/)).toBeTruthy()
  })

  it('keeps the picker usable with 100 bound variables', async () => {
    const many = Array.from({ length: 100 }, (_, i) => ({
      id: `var-${i}`,
      unit: 'u',
      distribution: { type: 'fixed', value: i, mean: null, std: null, min: null, mode: null, max: null, p: null },
      evidence_ref: 'bulk',
      description: `Variable number ${i}`,
      scope_tags: [],
    }))
    variablesResponse = {
      status: 200,
      body: { ...VARIABLES, bindings: { ...VARIABLES.bindings, variables: many } },
    }
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    const select = screen.getByLabelText('变量')
    expect(within(select as HTMLElement).getAllByRole('option')).toHaveLength(101)
    fireEvent.change(screen.getByLabelText('筛选变量'), { target: { value: 'var-97' } })
    expect(within(select as HTMLElement).getAllByRole('option')).toHaveLength(2)
    expect(screen.getByRole('option', { name: 'var-97 · u · fixed = 97' })).toBeTruthy()
    fireEvent.change(screen.getByLabelText('筛选变量'), { target: { value: '' } })
    expect(within(select as HTMLElement).getAllByRole('option')).toHaveLength(101)
  })

  it('creates an override direction, omits fork_step, and shows the stored outcome', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('覆盖方向名称'), { target: { value: 'Cash at 80' } })
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: '80' } })
    fireEvent.click(screen.getByRole('checkbox', { name: '覆盖分支 Demand' }))
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0]).toEqual({
      url: '/api/runs/run-anchor/directions/override',
      body: {
        directions: [
          { name: 'Cash at 80', overrides: { cash: 80 }, arm: 'baseline', mece_branches: ['Demand'] },
        ],
      },
    })
    expect(
      (posted[0].body as { directions: Record<string, unknown>[] }).directions[0],
    ).not.toHaveProperty('fork_step')
    expect(await screen.findByText(/已存入/)).toBeTruthy()
    expect(screen.getByText(/子 Run run-child-1 · 分支 branch-1 · 分叉步 1 · 状态 COMPLETED/)).toBeTruthy()
    expect(screen.getByText(/No ensemble yet: run POST \/runs\/run-child-1\/monte-carlo/)).toBeTruthy()
    expect(await screen.findByText('变量覆盖：cash=80 · 分叉步 1')).toBeTruthy()
  })

  it('sends fork_step when provided', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('覆盖方向名称'), { target: { value: 'Cash at 80' } })
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: '80' } })
    fireEvent.change(screen.getByLabelText(/分叉步/), { target: { value: '2' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(
      (posted[0].body as { directions: Record<string, unknown>[] }).directions[0].fork_step,
    ).toBe(2)
  })

  it('creates two override directions in one request', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('覆盖方向名称'), { target: { value: 'First' } })
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: '80' } })
    fireEvent.click(screen.getByRole('button', { name: /添加覆盖方向/ }))
    const names = screen.getAllByLabelText('覆盖方向名称')
    fireEvent.change(names[1], { target: { value: 'Second' } })
    const selects = screen.getAllByLabelText('变量')
    fireEvent.change(selects[1], { target: { value: 'burn' } })
    const values = screen.getAllByLabelText('固定值')
    fireEvent.change(values[1], { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0].body).toEqual({
      directions: [
        { name: 'First', overrides: { cash: 80 }, arm: 'baseline', mece_branches: [] },
        { name: 'Second', overrides: { burn: 5 }, arm: 'baseline', mece_branches: [] },
      ],
    })
    expect(await screen.findByText(/已处理 2 个方向/)).toBeTruthy()
  })

  it('adds a variable row defaulting to the next unpicked bound variable', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.click(screen.getByRole('button', { name: '＋ 添加变量' }))
    const selects = screen.getAllByLabelText('变量')
    expect(selects).toHaveLength(2)
    expect(selects[1]).toHaveProperty('value', 'burn')
    expect(screen.queryByRole('button', { name: '＋ 添加变量' })).toBeNull()
  })

  it('refuses an empty direction name without posting', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: '80' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    expect(await screen.findByText(/每个覆盖方向都需要填写名称/)).toBeTruthy()
    expect(posted).toHaveLength(0)
  })

  it('refuses missing and non-finite fixed values without posting', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('覆盖方向名称'), { target: { value: 'Cash at 80' } })
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    expect(await screen.findByText(/需要填写固定值/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: 'abc' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    expect(await screen.findByText(/必须是有限数字/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: 'Infinity' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    expect(await screen.findByText(/必须是有限数字/)).toBeTruthy()
    expect(posted).toHaveLength(0)
  })

  it('refuses duplicate direction names without posting', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('覆盖方向名称'), { target: { value: 'Same' } })
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: '80' } })
    fireEvent.click(screen.getByRole('button', { name: /添加覆盖方向/ }))
    const names = screen.getAllByLabelText('覆盖方向名称')
    fireEvent.change(names[1], { target: { value: 'Same' } })
    const selects = screen.getAllByLabelText('变量')
    fireEvent.change(selects[1], { target: { value: 'burn' } })
    const values = screen.getAllByLabelText('固定值')
    fireEvent.change(values[1], { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    expect(await screen.findByText(/不能重复/)).toBeTruthy()
    expect(posted).toHaveLength(0)
  })

  it('refuses a fork_step below 1 without posting', async () => {
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('覆盖方向名称'), { target: { value: 'Cash at 80' } })
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: '80' } })
    fireEvent.change(screen.getByLabelText(/分叉步/), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    expect(
      await screen.findByText('方向「Cash at 80」的分叉步必须是 ≥ 1 的整数，留空则用默认中点。'),
    ).toBeTruthy()
    expect(posted).toHaveLength(0)
  })

  it('shows skipped and failed outcomes from the response', async () => {
    overrideResponse = {
      status: 201,
      body: {
        anchor_run_id: 'run-anchor',
        override_hash: 'sha256:mixed',
        directions_considered: 2,
        outcomes: [
          {
            name: 'First',
            status: 'skipped',
            reason: "A mapping named 'First' already exists (origin derived, status active); no branch run was created; left untouched.",
            mapping_id: null,
            branch_id: null,
            child_run_id: null,
            fork_step: 1,
            child_status: null,
            arm: 'baseline',
            mece_branches: [],
          },
          {
            name: 'Second',
            status: 'failed',
            reason: 'Branch creation failed: boom',
            mapping_id: null,
            branch_id: null,
            child_run_id: null,
            fork_step: 1,
            child_status: null,
            arm: 'baseline',
            mece_branches: [],
          },
        ],
        mappings: [],
      },
    }
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('覆盖方向名称'), { target: { value: 'First' } })
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: '80' } })
    fireEvent.click(screen.getByRole('button', { name: /添加覆盖方向/ }))
    const names = screen.getAllByLabelText('覆盖方向名称')
    fireEvent.change(names[1], { target: { value: 'Second' } })
    const selects = screen.getAllByLabelText('变量')
    fireEvent.change(selects[1], { target: { value: 'burn' } })
    const values = screen.getAllByLabelText('固定值')
    fireEvent.change(values[1], { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    expect(await screen.findByText(/已跳过/)).toBeTruthy()
    expect(screen.getByText(/already exists/)).toBeTruthy()
    expect(screen.getByText(/创建失败/)).toBeTruthy()
    expect(screen.getByText(/Branch creation failed: boom/)).toBeTruthy()
  })

  it('surfaces an override refusal with its code and message', async () => {
    overrideResponse = {
      status: 400,
      body: {
        detail: {
          code: 'direction_override_unknown_variable',
          message: "Override names unknown variable 'nope'. Valid variables: burn, cash",
        },
      },
    }
    renderPage()
    await pickAnchorRun()
    await expandOverrideForm()
    fireEvent.change(screen.getByLabelText('覆盖方向名称'), { target: { value: 'Cash at 80' } })
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('固定值'), { target: { value: '80' } })
    fireEvent.click(screen.getByRole('button', { name: '创建覆盖方向' }))
    expect(await screen.findByText(/direction_override_unknown_variable/)).toBeTruthy()
    expect(screen.getByText(/Valid variables: burn, cash/)).toBeTruthy()
    expect(screen.queryByText(/已处理/)).toBeNull()
  })

  it('labels every mapping origin and status, with an override summary', async () => {
    mappings = [directionMappingDerived, directionMappingAuthored, directionMappingProposed, directionMappingOverride]
    renderPage()
    await pickAnchorRun()
    expect(await screen.findAllByText('Boost cash')).toHaveLength(2)
    expect(screen.getByText(/推导 · 可用/)).toBeTruthy()
    expect(screen.getByText(/手动 · 可用 · 已编辑/)).toBeTruthy()
    expect(screen.getAllByText(/LLM 提案 · 待评审/)).toHaveLength(2)
    expect(screen.getByText(/变量覆盖 · 可用/)).toBeTruthy()
    expect(screen.getByText('变量覆盖：cash=80 · 分叉步 2')).toBeTruthy()
    expect(screen.getAllByText(/手动/)).toHaveLength(1)
  })

  it('shows an honest message when the anchor has no bound variables', async () => {
    variablesResponse = { status: 200, body: { ...VARIABLES, bindings: null } }
    renderPage()
    await pickAnchorRun()
    expect(await screen.findByText(/没有绑定变量/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '新建变量覆盖方向' })).toBeNull()
  })

  it('reforks an override mapping with edited fixed values and reloads the stored list', async () => {
    mappings = [directionMappingOverride]
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByRole('button', { name: '编辑固定值' }))
    const valueInput = screen.getByLabelText('cash 的固定值') as HTMLInputElement
    expect(valueInput.value).toBe('80')
    const forkInput = screen.getByLabelText('新分叉步（留空用默认中点）') as HTMLInputElement
    expect(forkInput.value).toBe('2')
    fireEvent.change(valueInput, { target: { value: '90' } })
    fireEvent.click(screen.getByRole('button', { name: '保存并重新分叉' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0].url).toBe('/api/runs/run-anchor/directions/mappings/mapping-5/refork')
    expect(posted[0].body).toEqual({ overrides: { cash: 90 }, fork_step: 2 })
    expect(await screen.findByText(/变量覆盖：cash=90 · 分叉步 2/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '保存并重新分叉' })).toBeNull()
  })

  it('omits fork_step from the refork payload when the fork-step input is cleared', async () => {
    mappings = [directionMappingOverride]
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByRole('button', { name: '编辑固定值' }))
    fireEvent.change(screen.getByLabelText('新分叉步（留空用默认中点）'), { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: '保存并重新分叉' }))
    await waitFor(() => expect(posted).toHaveLength(1))
    expect(posted[0].body).toEqual({ overrides: { cash: 80 } })
  })

  it('surfaces a refork refusal with its code and keeps the form open', async () => {
    mappings = [directionMappingOverride]
    reforkResponse = {
      status: 400,
      body: {
        detail: {
          code: 'direction_override_unknown_variable',
          message: "Override names unknown variable 'nope'. Valid variables: burn, cash",
        },
      },
    }
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByRole('button', { name: '编辑固定值' }))
    fireEvent.click(screen.getByRole('button', { name: '保存并重新分叉' }))
    expect(await screen.findByText(/direction_override_unknown_variable/)).toBeTruthy()
    expect(screen.getByText(/Valid variables: burn, cash/)).toBeTruthy()
    expect(screen.getByLabelText('cash 的固定值')).toBeTruthy()
  })

  it('shows the edit-fixed-values action only on active override rows', async () => {
    mappings = [
      directionMappingDerived,
      directionMappingAuthored,
      directionMappingProposed,
      directionMappingRejected,
      directionMappingOverride,
      { ...directionMappingOverride, id: 'mapping-6', name: 'Old cash', status: 'rejected' },
    ]
    renderPage()
    await pickAnchorRun()
    await screen.findByText('Highest P50')
    expect(screen.getAllByRole('button', { name: '编辑固定值' })).toHaveLength(1)
  })

  it('refuses a non-finite refork value without posting', async () => {
    mappings = [directionMappingOverride]
    renderPage()
    await pickAnchorRun()
    fireEvent.click(screen.getByRole('button', { name: '编辑固定值' }))
    fireEvent.change(screen.getByLabelText('cash 的固定值'), { target: { value: 'abc' } })
    fireEvent.click(screen.getByRole('button', { name: '保存并重新分叉' }))
    expect(await screen.findByText(/必须是有限数字/)).toBeTruthy()
    expect(posted).toHaveLength(0)
  })
})
