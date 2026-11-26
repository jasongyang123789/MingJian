import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  loopComparison,
  loopEvaluationError,
  loopEvaluationFired,
  loopEvaluationQuiet,
  loopIterationDecided,
  loopIterationEvaluated,
  loopIterationOpen,
  loopObservations,
  loopRegistration,
  monteCarloResult,
  trialValues,
} from '../../test/engineFixtures'
import {
  ComparisonView,
  EvaluationHistory,
  IterationCard,
  ObservationList,
  ResimulationView,
  TriggerBuilder,
  TriggerOutcomes,
  TriggerRegistrations,
} from './LoopViews'
import { triggerSummary } from './loopDisplay'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('triggerSummary', () => {
  it('summarizes all three trigger kinds', () => {
    const [threshold, gate, deviation] = loopRegistration.triggers
    expect(triggerSummary(threshold)).toBe('最新观测 cash < 70')
    expect(triggerSummary(gate)).toBe('观测统计 mean(cash) < 90')
    expect(triggerSummary(deviation)).toBe('cash 连续 2 次偏离 100 超过 20')
  })
})

describe('TriggerRegistrations', () => {
  it('renders the empty state when nothing is registered', () => {
    render(<TriggerRegistrations registrations={[]} />)
    expect(screen.getByText('尚未注册触发器')).toBeInTheDocument()
  })

  it('renders registrations with status and pre-registration evidence', () => {
    render(<TriggerRegistrations registrations={[loopRegistration]} />)
    expect(screen.getByText('活动')).toBeInTheDocument()
    expect(screen.getByText(/注册时已有观测 0 条/)).toBeInTheDocument()
    expect(screen.getByText('cash-floor')).toBeInTheDocument()
    expect(screen.getByText('cash-drift')).toBeInTheDocument()
  })

  it('marks superseded registrations', () => {
    render(<TriggerRegistrations registrations={[{ ...loopRegistration, status: 'superseded' }]} />)
    expect(screen.getByText('已取代')).toBeInTheDocument()
  })
})

describe('ObservationList', () => {
  it('renders observations in order', () => {
    render(<ObservationList observations={loopObservations} />)
    expect(screen.getByText('2026-01-10T00:00:00Z')).toBeInTheDocument()
    expect(screen.getByText('月度结算')).toBeInTheDocument()
    expect(screen.getAllByText('cash')).toHaveLength(3)
  })

  it('renders the empty state', () => {
    render(<ObservationList observations={[]} />)
    expect(screen.getByText('暂无观测记录')).toBeInTheDocument()
  })
})

describe('TriggerOutcomes', () => {
  it('shows fired outcomes with values and notes', () => {
    render(<TriggerOutcomes outcomes={loopIterationDecided.trigger_evaluations} />)
    expect(screen.getAllByText('已触发')).toHaveLength(3)
    expect(screen.getByText(/Latest observed cash 60 breached threshold 70/)).toBeInTheDocument()
    expect(screen.getByText(/连续偏离 2 次/)).toBeInTheDocument()
  })

  it('shows quiet and no-data outcomes distinctly', () => {
    render(
      <TriggerOutcomes
        outcomes={[
          {
            name: 'quiet-one',
            kind: 'threshold',
            field: 'cash',
            fired: false,
            status: 'quiet',
            observed_value: 95,
            threshold: 70,
            tolerance: null,
            reference_value: null,
            consecutive_breaches: null,
            observation_ids: ['obs-1'],
            observed_values: [95],
            note: 'Latest observed cash 95 did not breach threshold 70.',
          },
          {
            name: 'empty-one',
            kind: 'threshold',
            field: 'pipeline',
            fired: false,
            status: 'no_data',
            observed_value: null,
            threshold: 1,
            tolerance: null,
            reference_value: null,
            consecutive_breaches: null,
            observation_ids: [],
            observed_values: [],
            note: 'No observations for field pipeline in the window.',
          },
        ]}
      />,
    )
    expect(screen.getByText('未触发')).toBeInTheDocument()
    expect(screen.getByText('无数据')).toBeInTheDocument()
  })
})

describe('EvaluationHistory', () => {
  it('shows the empty state when no evaluation has been recorded', () => {
    render(<EvaluationHistory evaluations={[]} />)
    expect(screen.getByText('暂无监测评估')).toBeInTheDocument()
    expect(screen.getByText(/评估只记录触发状态/)).toBeInTheDocument()
  })

  it('shows a fired evaluation with its trigger outcomes', () => {
    render(<EvaluationHistory evaluations={[loopEvaluationFired]} />)
    expect(screen.getAllByText('已触发')).toHaveLength(4)
    expect(screen.getByText('2026-02-05T00:00:00Z')).toBeInTheDocument()
    expect(screen.getByText(/指纹 sha256:01234…abcdef/)).toBeInTheDocument()
    expect(screen.getByText(/Latest observed cash 60 breached threshold 70/)).toBeInTheDocument()
    expect(screen.getByText(/连续偏离 2 次/)).toBeInTheDocument()
  })

  it('shows a quiet evaluation distinctly', () => {
    render(<EvaluationHistory evaluations={[loopEvaluationQuiet]} />)
    expect(screen.getAllByText('未触发')).toHaveLength(2)
    expect(screen.getByText(/指纹 sha256:abcde…456789/)).toBeInTheDocument()
  })

  it('shows an error evaluation with its code and message', () => {
    render(<EvaluationHistory evaluations={[loopEvaluationError]} />)
    expect(screen.getByText('评估失败')).toBeInTheDocument()
    expect(screen.getByText(/loop_trigger_evaluation_failed/)).toBeInTheDocument()
    expect(screen.getByText(/has no reference value for field 'cash'/)).toBeInTheDocument()
  })
})

describe('ResimulationView', () => {
  it('shows both cutoffs, both hashes, and the no-change note', () => {
    render(<ResimulationView record={loopIterationDecided.resimulation!} />)
    expect(screen.getByText(/2026-01-01T00:00:00Z/)).toBeInTheDocument()
    expect(screen.getByText(/2026-02-01T00:00:00Z/)).toBeInTheDocument()
    expect(screen.getByText(/哈希不同是设计要求/)).toBeInTheDocument()
    expect(screen.getByText(/可见 claims 0 条/)).toBeInTheDocument()
    expect(screen.getByText(/无显式变更/)).toBeInTheDocument()
  })

  it('lists explicit changes and flags template drift', () => {
    render(
      <ResimulationView
        record={{
          ...loopIterationDecided.resimulation!,
          template_id: 'template:custom',
          template_snapshot_hash: 'sha256:old',
          resolved_template_snapshot_hash: 'sha256:new',
          changes: { seed: { from: 7, to: 99 } },
        }}
      />,
    )
    expect(screen.getByText(/模板快照已漂移/)).toBeInTheDocument()
    expect(screen.getByText(/"from":7/)).toBeInTheDocument()
  })
})

describe('ComparisonView', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  function mockEnsembles(oldId: string, newId: string) {
    vi.spyOn(window, 'fetch').mockImplementation(async (input) => {
      const url = String(input)
      if (url === '/api/runs/run-baseline/monte-carlo') {
        return jsonResponse({ ...monteCarloResult, ensemble_id: oldId, base_run_id: 'run-baseline' })
      }
      if (url === '/api/runs/run-resim/monte-carlo') {
        return jsonResponse({ ...monteCarloResult, ensemble_id: newId, base_run_id: 'run-resim' })
      }
      if (url.endsWith('/monte-carlo/trial-values')) return jsonResponse(trialValues)
      return jsonResponse({})
    })
  }

  it('renders arm delta tables, paired stats, and the evidence caveat', async () => {
    mockEnsembles('ensemble-old', 'ensemble-new')
    render(<ComparisonView comparison={loopComparison} />)
    expect(screen.getByText('基线臂')).toBeInTheDocument()
    expect(screen.getByText('策略臂')).toBeInTheDocument()
    expect(screen.getByText('种子配对')).toBeInTheDocument()
    expect(screen.getByText(/different evidence cutoffs/)).toBeInTheDocument()
    expect(screen.getByText(/配对均值差 40 → 40/)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getAllByText(/直方图来自存储的 trial 值/)).toHaveLength(2)
    })
  })

  it('refuses to stand a newer ensemble in for the compared one', async () => {
    mockEnsembles('ensemble-later', 'ensemble-new')
    render(<ComparisonView comparison={loopComparison} />)
    await waitFor(() => {
      expect(
        screen.getByText('旧模拟集合已不是该推演当前存储的模拟集合'),
      ).toBeInTheDocument()
    })
    expect(screen.getAllByText(/直方图来自存储的 trial 值/)).toHaveLength(1)
  })

  it('renders gate reevaluation and threshold drift when present', () => {
    mockEnsembles('ensemble-old', 'ensemble-new')
    render(
      <ComparisonView
        comparison={{
          ...loopComparison,
          gate_reevaluation: {
            registration_id: 'reg-1',
            ensemble_id: 'ensemble-new',
            outcomes: [
              { name: 'g1', metric: 'mean', operator: '<', threshold: 90, arm: 'baseline', alpha: null, observed: 100, passed: false },
            ],
            all_passed: false,
            pre_registered: true,
          },
          threshold_drift: [
            { variable: 'cac', mode: 'p_loss', old_threshold: 12000, old_reachable: true, new_threshold: null, new_reachable: false },
          ],
        }}
      />,
    )
    expect(screen.getByText(/有门未通过/)).toBeInTheDocument()
    expect(screen.getByText('未通过')).toBeInTheDocument()
    expect(screen.getByText(/cac（p_loss）：旧阈值 12000 → 新阈值 不可达/)).toBeInTheDocument()
  })
})

describe('TriggerBuilder', () => {
  it('builds a threshold trigger and submits the set', () => {
    const onSubmit = vi.fn()
    render(<TriggerBuilder submitLabel="注册触发器" onSubmit={onSubmit} />)
    fireEvent.change(screen.getByLabelText('触发器名称'), { target: { value: 'cash-floor' } })
    fireEvent.change(screen.getByLabelText('状态字段'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('阈值'), { target: { value: '70' } })
    fireEvent.click(screen.getByText('添加触发器'))
    expect(screen.getByText(/最新观测 cash < 70/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('注册触发器'))
    expect(onSubmit).toHaveBeenCalledWith(
      [{ kind: 'threshold', name: 'cash-floor', field: 'cash', operator: '<', threshold: 70 }],
      null,
    )
  })

  it('builds a deviation trigger with an explicit reference value', () => {
    const onSubmit = vi.fn()
    render(<TriggerBuilder submitLabel="注册触发器" onSubmit={onSubmit} />)
    fireEvent.change(screen.getByLabelText('触发器类型'), { target: { value: 'deviation' } })
    fireEvent.change(screen.getByLabelText('触发器名称'), { target: { value: 'cash-drift' } })
    fireEvent.change(screen.getByLabelText('状态字段'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('容差（大于 0）'), { target: { value: '20' } })
    fireEvent.change(screen.getByLabelText('连续次数'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('参考值（留空用基线终值）'), { target: { value: '100' } })
    fireEvent.click(screen.getByText('添加触发器'))
    fireEvent.click(screen.getByText('注册触发器'))
    expect(onSubmit).toHaveBeenCalledWith(
      [
        {
          kind: 'deviation',
          name: 'cash-drift',
          field: 'cash',
          tolerance: 20,
          consecutive: 2,
          reference_value: 100,
        },
      ],
      null,
    )
  })

  it('requires a loss threshold for a p_loss gate trigger', () => {
    const onSubmit = vi.fn()
    render(<TriggerBuilder submitLabel="注册触发器" onSubmit={onSubmit} />)
    fireEvent.change(screen.getByLabelText('触发器类型'), { target: { value: 'gate' } })
    fireEvent.change(screen.getByLabelText('触发器名称'), { target: { value: 'loss-gate' } })
    fireEvent.change(screen.getByLabelText('状态字段'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('统计量'), { target: { value: 'p_loss' } })
    fireEvent.change(screen.getByLabelText('阈值'), { target: { value: '0.3' } })
    fireEvent.click(screen.getByText('添加触发器'))
    expect(screen.getByText('p_loss 门需要亏损阈值。')).toBeInTheDocument()
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('refuses duplicate names and non-positive tolerance', () => {
    render(<TriggerBuilder submitLabel="注册触发器" onSubmit={vi.fn()} />)
    fireEvent.change(screen.getByLabelText('触发器名称'), { target: { value: 'dup' } })
    fireEvent.change(screen.getByLabelText('状态字段'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('阈值'), { target: { value: '70' } })
    fireEvent.click(screen.getByText('添加触发器'))
    fireEvent.change(screen.getByLabelText('触发器名称'), { target: { value: 'dup' } })
    fireEvent.change(screen.getByLabelText('状态字段'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('阈值'), { target: { value: '60' } })
    fireEvent.click(screen.getByText('添加触发器'))
    expect(screen.getByText(/触发器名称 dup 已存在/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('触发器类型'), { target: { value: 'deviation' } })
    fireEvent.change(screen.getByLabelText('触发器名称'), { target: { value: 'bad-tol' } })
    fireEvent.change(screen.getByLabelText('容差（大于 0）'), { target: { value: '0' } })
    fireEvent.click(screen.getByText('添加触发器'))
    expect(screen.getByText('容差必须是大于 0 的有限数值。')).toBeInTheDocument()
  })

  it('supersedes the active registration by default, opt-out with the checkbox', () => {
    const onSubmit = vi.fn()
    render(
      <TriggerBuilder
        submitLabel="注册触发器"
        supersedeOption={{ activeRegistrationId: 'registration-1' }}
        onSubmit={onSubmit}
      />,
    )
    fireEvent.change(screen.getByLabelText('触发器名称'), { target: { value: 't1' } })
    fireEvent.change(screen.getByLabelText('状态字段'), { target: { value: 'cash' } })
    fireEvent.change(screen.getByLabelText('阈值'), { target: { value: '70' } })
    fireEvent.click(screen.getByText('添加触发器'))
    fireEvent.click(screen.getByText('注册触发器'))
    expect(onSubmit).toHaveBeenCalledWith(expect.anything(), 'registration-1')

    fireEvent.click(screen.getByLabelText(/取代当前活动注册/))
    fireEvent.click(screen.getByText('注册触发器'))
    expect(onSubmit).toHaveBeenLastCalledWith(expect.anything(), null)
  })
})

describe('IterationCard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  function mockActions(handler: (url: string, init?: RequestInit) => Response) {
    vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      if (url.includes('/monte-carlo')) return jsonResponse({ detail: 'not found' }, 404)
      return handler(url, init)
    })
  }

  it('renders a decided iteration with no actions', () => {
    mockActions(() => jsonResponse({}))
    render(<IterationCard iteration={loopIterationDecided} onChanged={vi.fn()} />)
    expect(screen.getByText('评审 #0')).toBeInTheDocument()
    expect(screen.getByText('已决策')).toBeInTheDocument()
    expect(screen.getByText(/分布未变，继续执行/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '评估触发器' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '重新模拟' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '记录决策' })).not.toBeInTheDocument()
  })

  it('evaluates an open iteration and notifies the parent', async () => {
    const onChanged = vi.fn()
    const calls: string[] = []
    mockActions((url) => {
      calls.push(url)
      return jsonResponse({ ...loopIterationOpen, state: 'evaluated' })
    })
    render(<IterationCard iteration={loopIterationOpen} onChanged={onChanged} />)
    fireEvent.click(screen.getByText('评估触发器'))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(calls).toContain('/api/loops/loop-1/iterations/iteration-open/evaluate')
  })

  it('re-simulates with explicit overrides and records a decision', async () => {
    const onChanged = vi.fn()
    const bodies: Record<string, unknown> = {}
    mockActions((url, init) => {
      bodies[url] = init?.body ? JSON.parse(String(init.body)) : null
      return jsonResponse(loopIterationEvaluated)
    })
    render(<IterationCard iteration={loopIterationEvaluated} onChanged={onChanged} />)
    fireEvent.change(screen.getByLabelText('Seed（留空继承基线）'), { target: { value: '99' } })
    fireEvent.click(screen.getByText('重新模拟'))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(bodies['/api/loops/loop-1/iterations/iteration-evaluated/resimulate']).toEqual({ seed: 99 })

    fireEvent.change(screen.getByLabelText('决策理由（必填，记入审计轨迹）'), {
      target: { value: '触发器已触发，继续观察。' },
    })
    fireEvent.click(screen.getByText('记录决策'))
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2))
    expect(bodies['/api/loops/loop-1/iterations/iteration-evaluated/decide']).toEqual({
      decision: 'continue',
      rationale: '触发器已触发，继续观察。',
    })
  })

  it('surfaces a refused re-simulation with its structured code', async () => {
    const onChanged = vi.fn()
    mockActions((url) => {
      if (url.endsWith('/resimulate')) {
        return jsonResponse(
          { detail: { code: 'variable_validation_failed', message: 'Variable bindings failed validation.' } },
          400,
        )
      }
      return jsonResponse({})
    })
    render(<IterationCard iteration={loopIterationEvaluated} onChanged={onChanged} />)
    fireEvent.click(screen.getByText('重新模拟'))
    await waitFor(() => {
      expect(screen.getByText(/variable_validation_failed/)).toBeInTheDocument()
    })
    expect(onChanged).not.toHaveBeenCalled()
  })

  it('compares a resimulated iteration', async () => {
    const onChanged = vi.fn()
    const calls: string[] = []
    mockActions((url) => {
      calls.push(url)
      return jsonResponse({ ...loopIterationEvaluated, state: 'compared' })
    })
    render(
      <IterationCard
        iteration={{ ...loopIterationEvaluated, state: 'resimulated', resimulation: loopIterationDecided.resimulation }}
        onChanged={onChanged}
      />,
    )
    fireEvent.click(screen.getByText('比较 Ensemble'))
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    expect(calls).toContain('/api/loops/loop-1/iterations/iteration-evaluated/compare')
  })
})
