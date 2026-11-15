import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { loopEvaluationFired, loopIterationOpen, loopRead, loopTimeline } from '../test/engineFixtures'
import LivingLoop from './LivingLoop'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const RUNS = [
  { id: 'run-baseline', status: 'COMPLETED', domain_id: 'corporate', company_id: 'acme', created_at: '2026-01-01T00:00:00Z', tick_count: 2 },
]

describe('LivingLoop', () => {
  let loops: unknown[]
  let timeline: unknown
  let evaluations: unknown[]
  let cycleResult: unknown
  const posted: { url: string; body: unknown }[] = []

  beforeEach(() => {
    vi.restoreAllMocks()
    loops = [loopRead]
    timeline = loopTimeline
    evaluations = []
    cycleResult = {
      cycle_id: 'cycle-9',
      evaluated_at: '2026-02-05T00:00:00Z',
      loops_evaluated: 1,
      loops_skipped: 2,
      loops_fired: 1,
      loops_errored: 0,
      loops: [],
      errors: [],
    }
    posted.length = 0
    vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (method === 'POST') {
        posted.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        if (url === '/api/loops') {
          const created = { ...loopRead, id: 'loop-2', name: '新循环', triggers: [] }
          loops = [...loops, created]
          return jsonResponse(created, 201)
        }
        if (url === '/api/loops/monitoring/evaluate') {
          evaluations = [loopEvaluationFired]
          return jsonResponse(cycleResult)
        }
        if (url.endsWith('/iterations')) return jsonResponse(loopIterationOpen, 201)
        if (url.endsWith('/triggers')) return jsonResponse({ id: 'registration-2' }, 201)
        if (url.endsWith('/observations')) return jsonResponse({}, 201)
        return jsonResponse({})
      }
      if (url === '/api/loops') return jsonResponse(loops)
      if (url === '/api/simulation/runs') return jsonResponse(RUNS)
      if (url.includes('/evaluations')) return jsonResponse(evaluations)
      if (url === '/api/loops/loop-1/timeline') return jsonResponse(timeline)
      if (url === '/api/loops/loop-2/timeline') {
        return jsonResponse({ loop: { ...loopRead, id: 'loop-2', name: '新循环', triggers: [] }, observations: [], iterations: [] })
      }
      if (url.includes('/monte-carlo')) return jsonResponse({ detail: 'not found' }, 404)
      return jsonResponse({})
    })
  })

  function renderPage(initialEntry = '/cockpit/loops') {
    return render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <LivingLoop />
      </MemoryRouter>,
    )
  }

  it('shows the empty states when there are no loops', async () => {
    loops = []
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('暂无战略循环')).toBeInTheDocument()
    })
    expect(screen.getByText('请选择一个循环')).toBeInTheDocument()
  })

  it('lists loops and shows the selected timeline', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('AI 客服线')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('AI 客服线'))
    await waitFor(() => {
      expect(screen.getByText('时间线：AI 客服线')).toBeInTheDocument()
    })
    expect(screen.getAllByText('cash-floor')).toHaveLength(2) // registration + outcome
    expect(screen.getByText('月度结算')).toBeInTheDocument()
    expect(screen.getByText('评审 #0')).toBeInTheDocument()
    expect(screen.getByText('已决策')).toBeInTheDocument()
    expect(screen.getByText('开启新一轮评审')).toBeInTheDocument()
  })

  it('loads the timeline directly from the ?loop= parameter', async () => {
    renderPage('/cockpit/loops?loop=loop-1')
    await waitFor(() => {
      expect(screen.getByText('时间线：AI 客服线')).toBeInTheDocument()
    })
  })

  it('blocks a new iteration while one is still open', async () => {
    timeline = { ...loopTimeline, iterations: [loopTimeline.iterations[0], loopIterationOpen] }
    renderPage('/cockpit/loops?loop=loop-1')
    await waitFor(() => {
      expect(screen.getByText(/评审 #1 尚未决策/)).toBeInTheDocument()
    })
    expect(screen.queryByText('开启新一轮评审')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '评估触发器' })).toBeInTheDocument()
  })

  it('creates a loop from the form and selects it', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('AI 客服线')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('新建循环'))
    fireEvent.change(screen.getByPlaceholderText('例如 AI 客服线'), { target: { value: '新循环' } })
    fireEvent.change(screen.getByLabelText('基线 Run（须已完成）'), { target: { value: 'run-baseline' } })
    fireEvent.click(screen.getByText('创建循环'))
    await waitFor(() => {
      expect(screen.getByText('时间线：新循环')).toBeInTheDocument()
    })
    const create = posted.find((entry) => entry.url === '/api/loops')
    expect(create?.body).toEqual({ baseline_run_id: 'run-baseline', name: '新循环', triggers: [] })
  })

  it('starts a new iteration with the chosen review time', async () => {
    renderPage('/cockpit/loops?loop=loop-1')
    await waitFor(() => {
      expect(screen.getByText('时间线：AI 客服线')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText('评审时间'), { target: { value: '2026-03-01T00:00' } })
    fireEvent.click(screen.getByText('开启新一轮评审'))
    await waitFor(() => {
      expect(posted.some((entry) => entry.url === '/api/loops/loop-1/iterations')).toBe(true)
    })
    const start = posted.find((entry) => entry.url === '/api/loops/loop-1/iterations')
    const decisionTime = (start?.body as { decision_time: string }).decision_time
    expect(Number.isNaN(Date.parse(decisionTime))).toBe(false)
  })

  it('registers a new trigger set superseding the active registration', async () => {
    renderPage('/cockpit/loops?loop=loop-1')
    await waitFor(() => {
      expect(screen.getByText('时间线：AI 客服线')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText('触发器名称'), { target: { value: 'cash-floor-2' } })
    // Two "状态字段" labels exist (trigger builder + observation form);
    // the builder's comes first in DOM order.
    fireEvent.change(screen.getAllByLabelText('状态字段')[0], { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('阈值'), { target: { value: '60' } })
    fireEvent.click(screen.getByText('添加触发器'))
    fireEvent.click(screen.getByText('注册触发器'))
    await waitFor(() => {
      expect(posted.some((entry) => entry.url === '/api/loops/loop-1/triggers')).toBe(true)
    })
    const registration = posted.find((entry) => entry.url === '/api/loops/loop-1/triggers')
    expect(registration?.body).toEqual({
      triggers: [{ kind: 'threshold', name: 'cash-floor-2', field: 'cash', operator: '<', threshold: 60 }],
      supersedes: 'registration-1',
    })
  })

  it('records an observation from the form', async () => {
    renderPage('/cockpit/loops?loop=loop-1')
    await waitFor(() => {
      expect(screen.getByText('时间线：AI 客服线')).toBeInTheDocument()
    })
    const fieldInputs = screen.getAllByPlaceholderText('例如 cash')
    fireEvent.change(fieldInputs[fieldInputs.length - 1], { target: { value: 'cash' } })
    const valueInputs = screen.getAllByPlaceholderText('数值')
    fireEvent.change(valueInputs[valueInputs.length - 1], { target: { value: '88' } })
    fireEvent.change(screen.getByLabelText('观测时间'), { target: { value: '2026-02-10T00:00' } })
    fireEvent.click(screen.getByRole('button', { name: '记录观测' }))
    await waitFor(() => {
      expect(posted.some((entry) => entry.url === '/api/loops/loop-1/observations')).toBe(true)
    })
    const observation = posted.find((entry) => entry.url === '/api/loops/loop-1/observations')
    expect(observation?.body).toMatchObject({ field: 'cash', value: 88, source_claim_id: null })
  })

  it('shows the monitoring evaluation history for the selected loop', async () => {
    evaluations = [loopEvaluationFired]
    renderPage('/cockpit/loops?loop=loop-1')
    await waitFor(() => {
      expect(screen.getByText('监测评估')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('2026-02-05T00:00:00Z')).toBeInTheDocument()
    })
    // The fired note appears once in the iteration card and once in
    // the evaluation history.
    expect(screen.getAllByText(/Latest observed cash 60 breached threshold 70/)).toHaveLength(2)
  })

  it('runs one monitoring cycle on demand and shows the result', async () => {
    renderPage('/cockpit/loops?loop=loop-1')
    await waitFor(() => {
      expect(screen.getByText('暂无监测评估')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行一次监测（全部循环）'))
    await waitFor(() => {
      expect(posted.some((entry) => entry.url === '/api/loops/monitoring/evaluate')).toBe(true)
    })
    await waitFor(() => {
      expect(screen.getByText(/评估 1 个循环/)).toBeInTheDocument()
    })
    expect(screen.getByText(/跳过 2 个/)).toBeInTheDocument()
    expect(screen.getByText(/触发 1 个/)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('2026-02-05T00:00:00Z')).toBeInTheDocument()
    })
  })
})
