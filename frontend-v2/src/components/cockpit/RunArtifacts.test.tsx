import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  calibrationFits,
  decisionGatesRead,
  determinismRead,
  firewallRead,
  monteCarloResult,
  robustnessRead,
  variableRunRead,
} from '../../test/engineFixtures'
import {
  CalibrationFitsView,
  DecisionGatesView,
  DeterminismView,
  EnsembleView,
  FirewallView,
  RobustnessView,
  VariableBindingsView,
} from './RunArtifacts'
import { distributionSummary } from './format'

describe('distributionSummary', () => {
  it('summarizes each distribution type from its own parameters', () => {
    const base = { id: 'v', unit: 'u', evidence_ref: 'e', description: '', scope_tags: [] }
    expect(distributionSummary({ ...base, distribution: { type: 'fixed', value: 5, mean: null, std: null, min: null, mode: null, max: null, p: null } })).toBe('fixed = 5')
    expect(distributionSummary({ ...base, distribution: { type: 'normal', value: null, mean: 10, std: 2, min: null, mode: null, max: null, p: null } })).toBe('normal(μ=10, σ=2)')
    expect(distributionSummary({ ...base, distribution: { type: 'bernoulli', value: null, mean: null, std: null, min: null, mode: null, max: null, p: 0.25 } })).toBe('bernoulli(p=0.25)')
  })
})

describe('VariableBindingsView', () => {
  it('renders the template snapshot, bindings, formulas, and internal table', () => {
    render(<VariableBindingsView data={variableRunRead} />)
    expect(screen.getByText(/Corporate \(built-in\)/)).toBeInTheDocument()
    // 'cash' appears twice: once as a template state field, once as a bound variable.
    expect(screen.getAllByText('cash')).toHaveLength(2)
    expect(screen.getByText(/triangular\(60, 100, 140\)/)).toBeInTheDocument()
    expect(screen.getByText('estimate: founder')).toBeInTheDocument()
    expect(screen.getByText(/runway_months =/)).toBeInTheDocument()
    expect(screen.getByText('9 months of cash')).toBeInTheDocument()
    expect(screen.getByText('变量表有效')).toBeInTheDocument()
  })
})

describe('EnsembleView', () => {
  it('renders both arms with P10/P50/P90 and loss probability plus paired deltas', () => {
    render(<EnsembleView result={monteCarloResult} />)
    expect(screen.getByText('基线')).toBeInTheDocument()
    expect(screen.getByText('策略')).toBeInTheDocument()
    expect(screen.getByText('98.9')).toBeInTheDocument()
    expect(screen.getByText('30.0%')).toBeInTheDocument()
    expect(screen.getByText(/40.61/)).toBeInTheDocument()
    expect(screen.getByText(/ensemble ens-1/)).toBeInTheDocument()
  })
})

describe('DeterminismView', () => {
  it('renders the input hash, per-tick hashes, and sampled values', () => {
    render(<DeterminismView data={determinismRead} />)
    expect(screen.getByText(/sha256:01234/)).toBeInTheDocument()
    expect(screen.getByText('tick 0')).toBeInTheDocument()
    expect(screen.getByText(/98.9 · 已应用/)).toBeInTheDocument()
    expect(screen.getByText(/8.24/)).toBeInTheDocument()
  })
})

describe('RobustnessView', () => {
  it('renders expected shortfall, tornado rows ranked by swing, and bootstrap intervals', () => {
    render(<RobustnessView data={robustnessRead} />)
    expect(screen.getByText(/74.23/)).toBeInTheDocument()
    expect(screen.getByText('cash')).toBeInTheDocument()
    expect(screen.getByText('64')).toBeInTheDocument()
    expect(screen.getByText('99.39')).toBeInTheDocument()
    expect(screen.getByText('95.3')).toBeInTheDocument()
  })

  it('reports an unreachable threshold honestly instead of inventing one', () => {
    render(<RobustnessView data={robustnessRead} />)
    expect(screen.getByText(/目标不可达/)).toBeInTheDocument()
    expect(screen.getByText(/未找到阈值是如实报告的结果/)).toBeInTheDocument()
  })

  it('renders a reachable threshold with its achieved statistic', () => {
    render(
      <RobustnessView
        data={{
          ...robustnessRead,
          threshold_search: {
            ...robustnessRead.threshold_search!,
            reachable: true,
            threshold: 89.84,
            achieved_statistic: 0.3,
          },
        }}
      />,
    )
    expect(screen.getByText('89.84')).toBeInTheDocument()
    expect(screen.queryByText(/目标不可达/)).not.toBeInTheDocument()
  })

  it('renders an empty state when no analysis is stored', () => {
    render(
      <RobustnessView
        data={{ run_id: 'run-1', ensemble_id: null, expected_shortfall: null, tornado: null, threshold_search: null, bootstrap: null }}
      />,
    )
    expect(screen.getByText('该 Run 尚未存储稳健性分析。')).toBeInTheDocument()
  })
})

describe('DecisionGatesView', () => {
  it('renders registrations with pre-registration evidence and evaluations with outcomes', () => {
    render(<DecisionGatesView data={decisionGatesRead} />)
    expect(screen.getByText(/p50-above-zero: baseline.p50 >= 0/)).toBeInTheDocument()
    expect(screen.getByText(/注册时 ensemble 不存在/)).toBeInTheDocument()
    expect(screen.getByText('全部通过')).toBeInTheDocument()
    expect(screen.getByText(/预注册：是/)).toBeInTheDocument()
    expect(screen.getByText(/PASS/)).toBeInTheDocument()
  })
})

describe('FirewallView', () => {
  it('lists excluded claims separately from included claims', () => {
    render(<FirewallView data={firewallRead} />)
    expect(screen.getByText(/被防火墙挡在外的 claim（2）/)).toBeInTheDocument()
    expect(screen.getByText('claim-late-1')).toBeInTheDocument()
    expect(screen.getByText('claim-early-1')).toBeInTheDocument()
    expect(screen.getByText(/2026-03-01/)).toBeInTheDocument()
  })
})

describe('CalibrationFitsView', () => {
  it('renders threshold fits with the new template version hint and source untouched', () => {
    render(<CalibrationFitsView fits={calibrationFits} />)
    expect(screen.getByText(/tmpl-cal-1/)).toBeInTheDocument()
    expect(screen.getByText(/源模板 builtin:corporate 未被修改/)).toBeInTheDocument()
    expect(screen.getByText(/alert 50 → 86/)).toBeInTheDocument()
    expect(screen.getByText(/critical 25 → 52.5/)).toBeInTheDocument()
  })

  it('renders rule-weight fits with the association note and LOO RMSE', () => {
    render(<CalibrationFitsView fits={calibrationFits} />)
    expect(screen.getByText(/corp.cost_pressure：权重 1 → 2/)).toBeInTheDocument()
    expect(screen.getByText(/association signal/)).toBeInTheDocument()
    expect(screen.getByText(/LOO RMSE 45.31/)).toBeInTheDocument()
  })
})
