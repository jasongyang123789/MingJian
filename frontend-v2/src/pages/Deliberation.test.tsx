import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  advisoryBoardRecord,
  strategyTeamRecord,
} from '../test/engineFixtures'
import Deliberation from './Deliberation'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const RUNS = [
  { id: 'run-1', status: 'COMPLETED', domain_id: 'corporate', company_id: 'acme', created_at: '2026-11-13T00:00:00Z' },
  { id: 'run-2', status: 'RUNNING', domain_id: 'corporate', company_id: 'beta', created_at: '2026-11-13T01:00:00Z' },
]

function mockBackend(overrides: Record<string, unknown> = {}) {
  return vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    if (url === '/api/simulation/runs') return jsonResponse(RUNS)
    if (url === '/api/runs/run-1/skills/deliberations') {
      return jsonResponse(overrides.deliberations ?? { run_id: 'run-1', deliberations: [strategyTeamRecord, advisoryBoardRecord] })
    }
    if (url === '/api/runs/run-1/skills/strategy-team' && method === 'POST') {
      return jsonResponse(overrides.strategyTeam ?? strategyTeamRecord, 201)
    }
    if (url === '/api/runs/run-1/skills/advisory-board' && method === 'POST') {
      return jsonResponse(overrides.advisoryBoard ?? advisoryBoardRecord, 201)
    }
    return jsonResponse({})
  })
}

function renderPage(initialEntries: string[] = ['/cockpit/deliberations']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Deliberation />
    </MemoryRouter>,
  )
}

async function selectRun(runId: string) {
  fireEvent.change(await screen.findByLabelText('选择模拟 Run'), { target: { value: runId } })
}

describe('Deliberation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('preselects the run from the ?run= URL parameter', async () => {
    mockBackend()
    renderPage(['/cockpit/deliberations?run=run-1'])
    expect(await screen.findByText('历史记录（append-only，最新在前）')).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toHaveValue('run-1')
    })
  })

  it('lists stored deliberations newest-first and expands a record', async () => {
    mockBackend()
    renderPage()
    await selectRun('run-1')

    const rows = await screen.findAllByText(/standard · 2026-11-13T/)
    expect(rows).toHaveLength(2)
    // Newest first: the advisory record (09:00) precedes the strategy record (08:00).
    expect(rows[0]).toHaveTextContent('09:00:00Z')
    expect(rows[1]).toHaveTextContent('08:00:00Z')

    fireEvent.click(rows[0])
    expect(await screen.findByText(/Round 1 · 各 lens 独立打分/)).toBeInTheDocument()
  })

  it('launches a strategy-team deliberation and shows the result', async () => {
    const fetchMock = mockBackend({ deliberations: { run_id: 'run-1', deliberations: [] } })
    renderPage()
    await selectRun('run-1')

    fireEvent.change(screen.getByLabelText('决策主题'), { target: { value: 'Launch?' } })
    fireEvent.click(screen.getByRole('button', { name: /启动 deliberation/ }))

    expect(await screen.findByText('最新结果')).toBeInTheDocument()
    expect(screen.getByText(/#1 Phased rollout/)).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/skills/strategy-team') && init?.method === 'POST')
    expect(post).toBeDefined()
    const body = JSON.parse(String(post![1]?.body))
    expect(body).toMatchObject({ topic: 'Launch?', mode: 'standard', include_premortem: true })
  })

  it('launches an advisory-board deliberation with options split by line', async () => {
    const fetchMock = mockBackend({ deliberations: { run_id: 'run-1', deliberations: [] } })
    renderPage()
    await selectRun('run-1')

    fireEvent.click(screen.getByRole('button', { name: /顾问团/ }))
    fireEvent.change(screen.getByLabelText('决策'), { target: { value: 'Launch?' } })
    fireEvent.change(screen.getByLabelText(/候选选项/), { target: { value: 'Phased rollout\nFull launch\n' } })
    fireEvent.click(screen.getByRole('button', { name: /启动 deliberation/ }))

    expect(await screen.findByText('最新结果')).toBeInTheDocument()
    const post = fetchMock.mock.calls.find(([input, init]) => String(input).endsWith('/skills/advisory-board') && init?.method === 'POST')
    expect(post).toBeDefined()
    const body = JSON.parse(String(post![1]?.body))
    expect(body).toMatchObject({ decision: 'Launch?', options: ['Phased rollout', 'Full launch'], mode: 'standard' })
  })

  it('blocks launching on a run that is not completed', async () => {
    mockBackend()
    renderPage()
    await selectRun('run-2')

    expect(await screen.findByText(/该 Run 尚未完成/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /启动 deliberation/ })).toBeDisabled()
  })

  it('shows the honest 503 banner when launching without a configured LLM', async () => {
    const fetchMock = mockBackend()
    fetchMock.mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/simulation/runs') return jsonResponse(RUNS)
      if (url.endsWith('/skills/deliberations')) return jsonResponse({ run_id: 'run-1', deliberations: [] })
      if (url.endsWith('/skills/strategy-team')) {
        return jsonResponse({ detail: { code: 'skill_llm_unavailable', message: 'No LLM is configured.' } }, 503)
      }
      return jsonResponse({})
    })
    renderPage()
    await selectRun('run-1')

    fireEvent.change(screen.getByLabelText('决策主题'), { target: { value: 'Launch?' } })
    fireEvent.click(screen.getByRole('button', { name: /启动 deliberation/ }))

    expect(await screen.findByText('未配置 LLM，无法启动 deliberation')).toBeInTheDocument()
    expect(screen.queryByText('最新结果')).not.toBeInTheDocument()
    // The launcher stays visible and usable.
    expect(screen.getByRole('button', { name: /启动 deliberation/ })).toBeEnabled()
  })

  it('shows the distinct 502 contract-failure banner for malformed LLM output', async () => {
    vi.spyOn(window, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/simulation/runs') return jsonResponse(RUNS)
      if (url.endsWith('/skills/deliberations')) return jsonResponse({ run_id: 'run-1', deliberations: [] })
      if (url.endsWith('/skills/strategy-team')) {
        return jsonResponse({ detail: { code: 'skill_contract_failed', message: 'stage output failed contract', template_id: 'mckinsey.synthesize' } }, 502)
      }
      return jsonResponse({})
    })
    renderPage()
    await selectRun('run-1')

    fireEvent.change(screen.getByLabelText('决策主题'), { target: { value: 'Launch?' } })
    fireEvent.click(screen.getByRole('button', { name: /启动 deliberation/ }))

    expect(await screen.findByText(/LLM 输出未通过契约校验（502）/)).toBeInTheDocument()
    expect(screen.queryByText('未配置 LLM，无法启动 deliberation')).not.toBeInTheDocument()
  })
})
