import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  monteCarloResult,
  robustnessRead,
  robustnessReadReachable,
  trialValues,
  variableRunRead,
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

interface CapturedRequest {
  url: string
  method: string
  body: unknown
}

interface HeldPost {
  url: string
  resolve: (response: Response) => void
}

describe('Charts', () => {
  let ensemble: unknown
  let values: unknown
  let robustness: unknown
  let runVariables: unknown
  let requests: CapturedRequest[]
  let postStatus: number
  let postBody: unknown
  let holdPosts: boolean
  let heldPosts: HeldPost[]

  function postResponse(url: string): Response {
    if (postStatus !== 201) return jsonResponse(postBody, postStatus)
    if (url === '/api/runs/run-1/monte-carlo') {
      ensemble = monteCarloResult
      robustness = { ...robustnessRead, tornado: null, bootstrap: null, threshold_search: null }
      return jsonResponse(monteCarloResult, 201)
    }
    if (url === '/api/runs/run-1/robustness/tornado') {
      robustness = { ...(robustness as Record<string, unknown>), tornado: robustnessRead.tornado }
      return jsonResponse(robustnessRead.tornado, 201)
    }
    if (url === '/api/runs/run-1/robustness/bootstrap') {
      robustness = { ...(robustness as Record<string, unknown>), bootstrap: robustnessRead.bootstrap }
      return jsonResponse(robustnessRead.bootstrap, 201)
    }
    if (url === '/api/runs/run-1/robustness/threshold-search') {
      robustness = { ...(robustness as Record<string, unknown>), threshold_search: robustnessRead.threshold_search }
      return jsonResponse(robustnessRead.threshold_search, 201)
    }
    return jsonResponse({})
  }

  function releaseHeldPosts() {
    const held = heldPosts
    heldPosts = []
    for (const post of held) post.resolve(postResponse(post.url))
  }

  beforeEach(() => {
    vi.restoreAllMocks()
    ensemble = monteCarloResult
    values = trialValues
    robustness = robustnessRead
    runVariables = variableRunRead
    requests = []
    postStatus = 201
    postBody = null
    holdPosts = false
    heldPosts = []
    vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      let body: unknown = null
      if (typeof init?.body === 'string') {
        try {
          body = JSON.parse(init.body)
        } catch {
          body = init.body
        }
      }
      requests.push({ url, method, body })
      if (method === 'POST') {
        if (holdPosts) return new Promise<Response>((resolve) => heldPosts.push({ url, resolve }))
        return postResponse(url)
      }
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
      if (url === '/api/runs/run-1/variables') {
        return runVariables === null ? jsonResponse({ detail: 'not found' }, 404) : jsonResponse(runVariables)
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

  it('runs an ensemble from the empty state and refreshes the charts', async () => {
    ensemble = null
    robustness = null
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行 Ensemble')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByLabelText('指标')).toHaveValue('cash')
    })
    fireEvent.click(screen.getByText('运行 Ensemble'))
    const posted = requests.find((request) => request.method === 'POST')
    expect(posted?.url).toBe('/api/runs/run-1/monte-carlo')
    expect(posted?.body).toEqual({ trials: 50, seed: null, metric: 'cash', loss_threshold: 0, strategy_levers: {} })
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '基线臂分布直方图' })).toBeInTheDocument()
    })
    // The robustness section refetched too: per-analysis launchers appear.
    expect(screen.getByText('尚未运行龙卷风分析')).toBeInTheDocument()
    expect(screen.getByText('运行龙卷风分析')).toBeInTheDocument()
  })

  it('runs an ensemble with the selected metric', async () => {
    ensemble = null
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行 Ensemble')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText('指标'), { target: { value: 'pipeline' } })
    fireEvent.click(screen.getByText('运行 Ensemble'))
    const posted = requests.find((request) => request.method === 'POST')
    expect(posted?.body).toMatchObject({ metric: 'pipeline' })
  })

  it('falls back to a typed metric when the run has no variables fragment', async () => {
    ensemble = null
    runVariables = null
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('如 cash')).toBeInTheDocument()
    })
    expect(screen.getByText('运行 Ensemble')).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText('如 cash'), { target: { value: 'readiness' } })
    fireEvent.click(screen.getByText('运行 Ensemble'))
    const posted = requests.find((request) => request.method === 'POST')
    expect(posted?.body).toMatchObject({ metric: 'readiness' })
  })

  it('shows the backend error and retries the ensemble launch', async () => {
    ensemble = null
    postStatus = 400
    postBody = { detail: { code: 'monte_carlo_unknown_metric', message: "Metric 'nope' is not a state field of domain 'corporate'." } }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行 Ensemble')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行 Ensemble'))
    await waitFor(() => {
      expect(screen.getByText(/monte_carlo_unknown_metric：Metric 'nope' is not a state field/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('img', { name: '基线臂分布直方图' })).not.toBeInTheDocument()
    postStatus = 201
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '基线臂分布直方图' })).toBeInTheDocument()
    })
  })

  it('disables the ensemble button while the launch is in flight', async () => {
    ensemble = null
    holdPosts = true
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行 Ensemble')).toBeInTheDocument()
    })
    const button = screen.getByText('运行 Ensemble')
    fireEvent.click(button)
    await waitFor(() => {
      expect(screen.getByText('运行中…')).toBeDisabled()
    })
    releaseHeldPosts()
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '基线臂分布直方图' })).toBeInTheDocument()
    })
  })

  it('runs a tornado analysis from its empty state and refreshes the chart', async () => {
    robustness = { ...robustnessRead, tornado: null }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行龙卷风分析')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行龙卷风分析'))
    const posted = requests.find((request) => request.method === 'POST')
    expect(posted?.url).toBe('/api/runs/run-1/robustness/tornado')
    expect(posted?.body).toEqual({ low_quantile: 0.1, high_quantile: 0.9, seed: null, variables: null })
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '龙卷风图' })).toBeInTheDocument()
    })
  })

  it('shows the backend error and retries a tornado launch', async () => {
    robustness = { ...robustnessRead, tornado: null }
    postStatus = 400
    postBody = { detail: { code: 'robustness_no_ensemble', message: 'Run run-1 has no stored ensemble.' } }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行龙卷风分析')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行龙卷风分析'))
    await waitFor(() => {
      expect(screen.getByText(/robustness_no_ensemble：Run run-1 has no stored ensemble/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('img', { name: '龙卷风图' })).not.toBeInTheDocument()
    postStatus = 201
    fireEvent.click(screen.getByText('重试'))
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '龙卷风图' })).toBeInTheDocument()
    })
  })

  it('disables the tornado button while the launch is in flight', async () => {
    robustness = { ...robustnessRead, tornado: null }
    holdPosts = true
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行龙卷风分析')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行龙卷风分析'))
    await waitFor(() => {
      expect(screen.getByText('运行中…')).toBeDisabled()
    })
    releaseHeldPosts()
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '龙卷风图' })).toBeInTheDocument()
    })
  })

  it('runs a bootstrap analysis from its empty state and refreshes the chart', async () => {
    robustness = { ...robustnessRead, bootstrap: null }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行 Bootstrap 分析')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行 Bootstrap 分析'))
    const posted = requests.find((request) => request.method === 'POST')
    expect(posted?.url).toBe('/api/runs/run-1/robustness/bootstrap')
    expect(posted?.body).toEqual({ statistics: ['mean', 'median', 'p_loss'], draws: 1000, seed: null, level: 0.9 })
    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'Bootstrap 区间图' })).toBeInTheDocument()
    })
  })

  it('shows the backend error for a failed bootstrap launch', async () => {
    robustness = { ...robustnessRead, bootstrap: null }
    postStatus = 400
    postBody = { detail: { code: 'robustness_no_ensemble', message: 'Run run-1 has no stored ensemble.' } }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行 Bootstrap 分析')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行 Bootstrap 分析'))
    await waitFor(() => {
      expect(screen.getByText(/robustness_no_ensemble：Run run-1 has no stored ensemble/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('img', { name: 'Bootstrap 区间图' })).not.toBeInTheDocument()
  })

  it('disables the bootstrap button while the launch is in flight', async () => {
    robustness = { ...robustnessRead, bootstrap: null }
    holdPosts = true
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行 Bootstrap 分析')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行 Bootstrap 分析'))
    await waitFor(() => {
      expect(screen.getByText('运行中…')).toBeDisabled()
    })
    releaseHeldPosts()
    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'Bootstrap 区间图' })).toBeInTheDocument()
    })
  })

  it('runs a threshold search from its empty state with the chosen variable and target', async () => {
    robustness = { ...robustnessRead, threshold_search: null }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行阈值搜索')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByLabelText('变量')).toHaveValue('cash')
    })
    expect(screen.getByLabelText('目标概率')).toHaveValue(0.5)
    fireEvent.change(screen.getByLabelText('变量'), { target: { value: 'cac' } })
    fireEvent.change(screen.getByLabelText('目标概率'), { target: { value: '0.3' } })
    fireEvent.click(screen.getByText('运行阈值搜索'))
    const posted = requests.find((request) => request.method === 'POST')
    expect(posted?.url).toBe('/api/runs/run-1/robustness/threshold-search')
    expect(posted?.body).toEqual({
      variable: 'cac',
      mode: 'p_loss',
      target: 0.3,
      direction: 'increasing',
      bounds: null,
      trials_per_evaluation: 20,
      max_iterations: 8,
      tolerance: 0.001,
      seed: null,
      loss_threshold: null,
    })
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '阈值搜索图' })).toBeInTheDocument()
    })
  })

  it('disables the threshold launch while the target is out of range', async () => {
    robustness = { ...robustnessRead, threshold_search: null }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行阈值搜索')).toBeInTheDocument()
    })
    const button = screen.getByText('运行阈值搜索')
    expect(button).not.toBeDisabled()
    fireEvent.change(screen.getByLabelText('目标概率'), { target: { value: '1.5' } })
    expect(button).toBeDisabled()
    fireEvent.change(screen.getByLabelText('目标概率'), { target: { value: '' } })
    expect(button).toBeDisabled()
    fireEvent.change(screen.getByLabelText('目标概率'), { target: { value: '0.3' } })
    expect(button).not.toBeDisabled()
    expect(requests.some((request) => request.method === 'POST')).toBe(false)
  })

  it('falls back to a typed variable when the run has no variable bindings', async () => {
    robustness = { ...robustnessRead, threshold_search: null }
    runVariables = null
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByPlaceholderText('变量 id，如 cash')).toBeInTheDocument()
    })
    expect(screen.getByText('运行阈值搜索')).toBeDisabled()
    fireEvent.change(screen.getByPlaceholderText('变量 id，如 cash'), { target: { value: 'cac' } })
    fireEvent.click(screen.getByText('运行阈值搜索'))
    const posted = requests.find((request) => request.method === 'POST')
    expect(posted?.body).toMatchObject({ variable: 'cac', target: 0.5 })
  })

  it('shows the backend error for a failed threshold search', async () => {
    robustness = { ...robustnessRead, threshold_search: null }
    postStatus = 400
    postBody = { detail: { code: 'robustness_threshold_fixed_variable', message: "Variable 'cash' is fixed; there is no range to search." } }
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行阈值搜索')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行阈值搜索'))
    await waitFor(() => {
      expect(screen.getByText(/robustness_threshold_fixed_variable：Variable 'cash' is fixed/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('img', { name: '阈值搜索图' })).not.toBeInTheDocument()
  })

  it('disables the threshold button while the launch is in flight', async () => {
    robustness = { ...robustnessRead, threshold_search: null }
    holdPosts = true
    renderPage()
    await waitFor(() => {
      expect(screen.getByLabelText('选择模拟 Run')).toBeInTheDocument()
    })
    await selectRun()
    await waitFor(() => {
      expect(screen.getByText('运行阈值搜索')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByText('运行阈值搜索'))
    await waitFor(() => {
      expect(screen.getByText('运行中…')).toBeDisabled()
    })
    releaseHeldPosts()
    await waitFor(() => {
      expect(screen.getByRole('img', { name: '阈值搜索图' })).toBeInTheDocument()
    })
  })
})
