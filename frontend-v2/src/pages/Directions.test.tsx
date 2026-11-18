import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

describe('Directions', () => {
  let narratives: unknown[]
  let mappings: unknown[]
  let generateResponse: { status: number; body: unknown } | null
  let polishResponse: { status: number; body: unknown } | null
  let deriveResponse: { status: number; body: unknown } | null
  let reviewResponse: { status: number; body: unknown } | null
  const posted: { url: string; body: unknown }[] = []

  beforeEach(() => {
    vi.restoreAllMocks()
    narratives = []
    mappings = []
    generateResponse = null
    polishResponse = null
    deriveResponse = null
    reviewResponse = null
    posted.length = 0
    vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/simulation/runs') return jsonResponse(RUNS)
      if (url === '/api/runs/run-anchor/mece') return jsonResponse(MECE)
      if (url === '/api/runs/run-other/mece') return jsonResponse({ detail: 'not found' }, 404)
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
    expect(screen.getByText(/覆盖：cash=80 · 分支步骤 2/)).toBeTruthy()
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
})
