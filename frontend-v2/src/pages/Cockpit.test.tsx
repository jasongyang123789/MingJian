import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  calibrationFits,
  decisionGatesRead,
  determinismRead,
  firewallRead,
  meceRunRead,
  monteCarloResult,
  robustnessRead,
  variableRunRead,
} from '../test/engineFixtures'
import Cockpit from './Cockpit'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const RUNS = [
  { id: 'run-1', status: 'COMPLETED', domain_id: 'corporate', company_id: 'acme', created_at: '2026-11-13T00:00:00Z', tick_count: 4 },
  { id: 'run-2', status: 'RUNNING', domain_id: 'corporate', company_id: 'beta', created_at: '2026-11-13T01:00:00Z', tick_count: 2 },
]

function mockAllFragments(fragments: Record<string, unknown> = {}) {
  const defaults: Record<string, unknown> = {
    '/api/runs/run-1/mece': meceRunRead,
    '/api/runs/run-1/variables': variableRunRead,
    '/api/runs/run-1/monte-carlo': monteCarloResult,
    '/api/runs/run-1/determinism': determinismRead,
    '/api/runs/run-1/robustness': robustnessRead,
    '/api/runs/run-1/decision-gates': decisionGatesRead,
    '/api/runs/run-1/firewall': firewallRead,
  }
  const mapping = { ...defaults, ...fragments }
  return vi.spyOn(window, 'fetch').mockImplementation(async (input) => {
    const url = String(input)
    if (url === '/api/simulation/runs') return jsonResponse(RUNS)
    if (url.startsWith('/api/calibration/fits')) return jsonResponse(calibrationFits)
    if (url in mapping) {
      const value = mapping[url]
      if (value === null) return jsonResponse({ detail: 'not found' }, 404)
      return jsonResponse(value)
    }
    return jsonResponse({})
  })
}

async function selectRun() {
  fireEvent.change(screen.getByLabelText('选择推演'), { target: { value: 'run-1' } })
  await waitFor(() => {
    expect(screen.getByText('MECE 分解')).toBeInTheDocument()
  })
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Cockpit />
    </MemoryRouter>,
  )
}

describe('Cockpit', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders every Sprint 1–5 fragment section for the selected run', async () => {
    mockAllFragments()
    renderPage()
    expect(await screen.findByLabelText('选择推演')).toBeInTheDocument()
    await selectRun()

    expect(await screen.findByText('MECE 通过')).toBeInTheDocument()
    // 'Launch decision' appears 3 times: the tree root plus two check rows.
    expect(screen.getAllByText('Launch decision')).toHaveLength(3)
    expect(screen.getByText('MECE 通过')).toBeInTheDocument()
    expect(screen.getByText(/triangular\(60, 100, 140\)/)).toBeInTheDocument()
    expect(screen.getByText('98.9')).toBeInTheDocument()
    expect(screen.getByText(/目标不可达/)).toBeInTheDocument()
    expect(screen.getByText('claim-late-1')).toBeInTheDocument()
    expect(screen.getByText(/tmpl-cal-1/)).toBeInTheDocument()
    expect(screen.getAllByText(/p50-above-zero/)).toHaveLength(2) // registration + evaluation outcome
    expect(screen.getByText('tick 0')).toBeInTheDocument()
  })

  it('shows an empty state, not an error, when a fragment is missing (404)', async () => {
    mockAllFragments({ '/api/runs/run-1/monte-carlo': null, '/api/runs/run-1/robustness': null })
    renderPage()
    expect(await screen.findByLabelText('选择推演')).toBeInTheDocument()
    await selectRun()

    expect(await screen.findByText('该推演尚未运行蒙特卡洛')).toBeInTheDocument()
    expect(screen.getByText('该推演尚未存储稳健性分析')).toBeInTheDocument()
    // Other sections still render.
    expect(screen.getAllByText('Launch decision')).toHaveLength(3)
  })

  it('prompts to select a run before showing any fragment', async () => {
    mockAllFragments()
    renderPage()
    expect(await screen.findByText('驾驶舱展示该推演已存储的全部 Sprint 1–5 工件')).toBeInTheDocument()
    expect(screen.queryByText('MECE 分解')).not.toBeInTheDocument()
  })

  it('scopes the calibration history to the selected run domain', async () => {
    const fetchMock = mockAllFragments()
    renderPage()
    expect(await screen.findByLabelText('选择推演')).toBeInTheDocument()
    await selectRun()
    await screen.findByText(/tmpl-cal-1/)
    const fitsCall = fetchMock.mock.calls.find(([input]) => String(input).startsWith('/api/calibration/fits'))
    expect(fitsCall).toBeDefined()
    expect(String(fitsCall![0])).toContain('domain_id=corporate')
    expect(within(screen.getByText('校准拟合历史').closest('section')!).getByText(/tmpl-cal-1/)).toBeInTheDocument()
  })
})
