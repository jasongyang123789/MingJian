import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  monteCarloResult,
  robustnessRead,
  robustnessReadReachable,
  trialValues,
} from '../test/engineFixtures'
import Charts from './Charts'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const RUNS = [
  { id: 'run-1', status: 'COMPLETED', domain_id: 'corporate', company_id: 'acme', created_at: '2026-11-13T00:00:00Z', tick_count: 4 },
]

describe('Charts', () => {
  let ensemble: unknown
  let values: unknown
  let robustness: unknown

  beforeEach(() => {
    vi.restoreAllMocks()
    ensemble = monteCarloResult
    values = trialValues
    robustness = robustnessRead
    vi.spyOn(window, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/simulation/runs') return jsonResponse(RUNS)
      if (url === '/api/runs/run-1/monte-carlo') {
        return ensemble === null ? jsonResponse({ detail: 'not found' }, 404) : jsonResponse(ensemble)
      }
      if (url === '/api/runs/run-1/monte-carlo/trial-values') {
        return values === null ? jsonResponse({ detail: 'not found' }, 404) : jsonResponse(values)
      }
      if (url === '/api/runs/run-1/robustness') {
        return robustness === null ? jsonResponse({ detail: 'not found' }, 404) : jsonResponse(robustness)
      }
      return jsonResponse({})
    })
  })

  function renderPage() {
    return render(
      <MemoryRouter>
        <Charts />
      </MemoryRouter>,
    )
  }

  async function selectRun() {
    fireEvent.change(screen.getByLabelText('选择模拟 Run'), { target: { value: 'run-1' } })
    await waitFor(() => {
      expect(screen.getByText('Ensemble 分布（run-1）')).toBeInTheDocument()
    })
  }

  it('asks for a run before showing any chart', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('请选择一个 Run')).toBeInTheDocument()
    })
    expect(screen.queryByText('Ensemble 分布（run-1）')).not.toBeInTheDocument()
  })

  it('renders ensemble histograms and all robustness charts for a run', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '基线臂分布直方图' })).toBeInTheDocument()
    })
    expect(screen.getByRole('img', { name: '策略臂分布直方图' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '配对差值直方图' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '龙卷风图' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Bootstrap 区间图' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '阈值搜索图' })).toBeInTheDocument()
    // The stored threshold search is unreachable — the honest state shows.
    expect(screen.getByText(/阈值不可达/)).toBeInTheDocument()
  })

  it('shows an empty state with how to run an ensemble when none is stored', async () => {
    ensemble = null
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('暂无 Ensemble 结果')).toBeInTheDocument()
    })
    expect(screen.getByText(/POST \/runs\/\{id\}\/monte-carlo/)).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: '基线臂分布直方图' })).not.toBeInTheDocument()
  })

  it('says trial values are unavailable instead of fabricating a distribution', async () => {
    values = null
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('Trial 值不可用')).toBeInTheDocument()
    })
    expect(screen.getByText(/不会用摘要统计量伪造分布/)).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: '基线臂分布直方图' })).not.toBeInTheDocument()
  })

  it('renders the found-threshold state when the search reached its target', async () => {
    robustness = robustnessReadReachable
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText(/找到阈值 105/)).toBeInTheDocument()
    })
  })

  it('shows per-analysis empty states when robustness rows are missing', async () => {
    robustness = { ...robustnessRead, tornado: null, bootstrap: null, threshold_search: null }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('尚未运行龙卷风分析')).toBeInTheDocument()
    })
    expect(screen.getByText('尚未运行 Bootstrap 分析')).toBeInTheDocument()
    expect(screen.getByText('尚未运行阈值搜索')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: '龙卷风图' })).not.toBeInTheDocument()
  })

  it('shows an empty state when no robustness analysis is stored at all', async () => {
    robustness = null
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('暂无稳健性分析')).toBeInTheDocument()
    })
  })
})
