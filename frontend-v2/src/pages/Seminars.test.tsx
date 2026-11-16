import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Seminars from './Seminars'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const RUNS = [
  { id: 'run-1', status: 'COMPLETED', label: 'Q3 launch' },
  { id: 'run-2', status: 'RUNNING', label: 'Pricing' },
]

const SEMINARS = [
  {
    seminar_id: 'sem-1',
    run_id: 'run-1',
    topic: 'Should we launch in Q3?',
    status: 'collecting',
    roster_size: 2,
    finals_count: 1,
    report_versions: [1],
  },
  {
    seminar_id: 'sem-2',
    run_id: 'run-1',
    topic: 'Pricing tiers?',
    status: 'open',
    roster_size: 3,
    finals_count: 0,
    report_versions: [],
  },
]

type CapturedRequest = { url: string; method: string; body: unknown }

let requests: CapturedRequest[]
let createStatus = 201

function installFetch() {
  requests = []
  createStatus = 201
  vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    let body: unknown = null
    if (typeof init?.body === 'string') {
      try {
        body = JSON.parse(init.body) as unknown
      } catch {
        body = init.body
      }
    }
    requests.push({ url, method, body })
    if (url === '/api/simulation/runs' && method === 'GET') return jsonResponse(RUNS)
    if (url === '/api/runs/run-1/seminars' && method === 'GET') return jsonResponse(SEMINARS)
    if (url === '/api/runs/run-2/seminars' && method === 'GET') return jsonResponse([])
    if (url === '/api/runs/run-1/seminars' && method === 'POST') {
      if (createStatus !== 201) {
        return jsonResponse(
          { detail: { code: 'run_not_completed', message: 'run run-1 is not COMPLETED' } },
          createStatus,
        )
      }
      return jsonResponse(
        {
          seminar_id: 'sem-new',
          run_id: 'run-1',
          topic: 'New topic',
          status: 'open',
          case_snapshot_hash: 'sha256:abcdef0123456789',
        },
        201,
      )
    }
    return jsonResponse({ detail: 'not found' }, 404)
  })
}

function renderPage(initialEntry = '/cockpit/seminars?run=run-1') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Seminars />
    </MemoryRouter>,
  )
}

describe('Seminars', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('lists seminars for the picked run with links to details', async () => {
    installFetch()
    renderPage()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    expect(screen.getByText('Pricing tiers?')).toBeTruthy()
    const link = screen.getByRole('link', { name: 'Should we launch in Q3?' })
    expect(link.getAttribute('href')).toBe('/cockpit/seminars/sem-1')
  })

  it('shows an honest empty state when the run has no seminars', async () => {
    installFetch()
    renderPage('/cockpit/seminars?run=run-2')
    await waitFor(() => expect(screen.getByText('该 Run 还没有研讨')).toBeTruthy())
  })

  it('blocks a roster below two models client-side', async () => {
    installFetch()
    renderPage()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    const removeButtons = screen.getAllByRole('button', { name: '移除' })
    fireEvent.click(removeButtons[0])
    fireEvent.click(screen.getByRole('button', { name: '创建研讨（冻结案例快照）' }))
    expect(screen.getByText(/名册至少需要 2 个模型/)).toBeTruthy()
    expect(requests.filter((req) => req.method === 'POST')).toHaveLength(0)
  })

  it('creates a seminar and shows a link to the new detail page', async () => {
    installFetch()
    renderPage()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('主题'), { target: { value: 'New topic' } })
    fireEvent.click(screen.getByRole('button', { name: '创建研讨（冻结案例快照）' }))
    await waitFor(() => expect(screen.getByText(/研讨已创建/)).toBeTruthy())
    const link = screen.getByRole('link', { name: '打开研讨详情' })
    expect(link.getAttribute('href')).toBe('/cockpit/seminars/sem-new')
    const post = requests.find((req) => req.method === 'POST')
    const body = post?.body as Record<string, unknown>
    expect(body.topic).toBe('New topic')
    expect((body.roster as unknown[]).length).toBe(2)
    expect(body.chair_mode).toBe('model')
    expect(body.max_stage_calls).toBe(200)
    expect(body.max_tokens).toBe(1000000)
  })

  it('shows server errors verbatim and leaves no phantom state', async () => {
    installFetch()
    createStatus = 400
    renderPage()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('主题'), { target: { value: 'New topic' } })
    fireEvent.click(screen.getByRole('button', { name: '创建研讨（冻结案例快照）' }))
    await waitFor(() => expect(screen.getByText(/run_not_completed/)).toBeTruthy())
    expect(screen.queryByText(/研讨已创建/)).toBeNull()
  })

  it('hides chair fields in agent mode and sends the glint-agent chair', async () => {
    installFetch()
    renderPage()
    await waitFor(() => expect(screen.getByText('Should we launch in Q3?')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('主控模式'), { target: { value: 'agent' } })
    expect(screen.getByText(/永不调用/)).toBeTruthy()
    expect(screen.queryByLabelText('主控模型 id')).toBeNull()
    fireEvent.change(screen.getByLabelText('主题'), { target: { value: 'Agent topic' } })
    fireEvent.click(screen.getByRole('button', { name: '创建研讨（冻结案例快照）' }))
    await waitFor(() => expect(screen.getByText(/研讨已创建/)).toBeTruthy())
    const post = requests.find((req) => req.method === 'POST')
    const body = post?.body as Record<string, unknown>
    expect(body.chair_mode).toBe('agent')
    expect((body.chair_model as { model_id: string }).model_id).toBe('glint-agent')
  })
})
