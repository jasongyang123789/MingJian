import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { narrativeRead } from '../test/engineFixtures'
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
  let generateResponse: { status: number; body: unknown } | null
  let polishResponse: { status: number; body: unknown } | null
  const posted: { url: string; body: unknown }[] = []

  beforeEach(() => {
    vi.restoreAllMocks()
    narratives = []
    generateResponse = null
    polishResponse = null
    posted.length = 0
    vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url === '/api/simulation/runs') return jsonResponse(RUNS)
      if (url === '/api/runs/run-anchor/mece') return jsonResponse(MECE)
      if (url === '/api/runs/run-other/mece') return jsonResponse({ detail: 'not found' }, 404)
      if (url === '/api/runs/run-anchor/narratives' && method === 'GET') {
        return jsonResponse({ run_id: 'run-anchor', narratives })
      }
      if (url === '/api/runs/run-other/narratives' && method === 'GET') {
        return jsonResponse({ run_id: 'run-other', narratives: [] })
      }
      if (method === 'POST' && url === '/api/runs/run-anchor/narratives') {
        posted.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        if (generateResponse) return jsonResponse(generateResponse.body, generateResponse.status)
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
})
