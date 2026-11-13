import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { DistributionSummary, MonteCarloTrialValues } from '../../api/engineTypes'
import { monteCarloResult, trialValues } from '../../test/engineFixtures'
import { EnsembleHistograms } from './DistributionCharts'

function summary(overrides: Partial<DistributionSummary>): DistributionSummary {
  return {
    n: 5,
    mean: 50,
    min: 10,
    max: 110,
    p10: 14,
    p50: 30,
    p90: 106,
    stddev: 40,
    p_loss: 0.6,
    ...overrides,
  }
}

describe('EnsembleHistograms', () => {
  it('renders both arm histograms with summary markers and captions', () => {
    const { container } = render(<EnsembleHistograms result={monteCarloResult} trialValues={trialValues} />)
    const baseline = screen.getByRole('img', { name: '基线臂分布直方图' })
    const strategy = screen.getByRole('img', { name: '策略臂分布直方图' })
    expect(within(baseline).getByText(/P10 79.4/)).toBeInTheDocument()
    expect(within(baseline).getByText(/亏损概率 30.0%/)).toBeInTheDocument()
    expect(within(strategy).getByText(/P50 140/)).toBeInTheDocument()
    // Reference-line labels render inside the SVG.
    const svgLabels = [...container.querySelectorAll('svg text')].map((node) => node.textContent)
    expect(svgLabels).toContain('P10')
    expect(svgLabels).toContain('P50')
    expect(svgLabels).toContain('P90')
    expect(svgLabels).toContain('阈值')
  })

  it('renders a bar for each non-empty bin in each histogram', () => {
    render(<EnsembleHistograms result={monteCarloResult} trialValues={trialValues} />)
    // Recharts omits zero-height bars, so only non-empty bins appear:
    // baseline 4 of 5 bins, degenerate strategy arm 1 of 5, deltas 5 of 5.
    const countBars = (name: string) =>
      screen.getByRole('img', { name }).querySelectorAll('.recharts-bar-rectangle').length
    expect(countBars('基线臂分布直方图')).toBe(4)
    expect(countBars('策略臂分布直方图')).toBe(1)
    expect(countBars('配对差值直方图')).toBe(5)
  })

  it('shades bins fully below the loss threshold', () => {
    const values: MonteCarloTrialValues = {
      ...trialValues,
      baseline: [10, 20, 30, 100, 110],
      strategy: [100, 100, 100, 100, 100],
    }
    const result = {
      ...monteCarloResult,
      baseline: summary({}),
      loss_threshold: 50,
    }
    const { container } = render(<EnsembleHistograms result={result} trialValues={values} />)
    const baseline = screen.getByRole('img', { name: '基线臂分布直方图' })
    const fills = [...baseline.querySelectorAll('.recharts-bar-rectangle path')].map((node) =>
      node.getAttribute('fill'),
    )
    expect(fills).toContain('#f87171')
    expect(fills).toContain('#60a5fa')
    expect(container.querySelectorAll('.recharts-bar-rectangle').length).toBeGreaterThan(0)
  })

  it('renders the paired-delta histogram from index-paired differences', () => {
    render(<EnsembleHistograms result={monteCarloResult} trialValues={trialValues} />)
    const deltas = screen.getByRole('img', { name: '配对差值直方图' })
    expect(within(deltas).getByText(/均值差 40.61/)).toBeInTheDocument()
    expect(within(deltas).getByText(/策略更优概率/)).toBeInTheDocument()
    const svgLabels = [...deltas.querySelectorAll('svg text')].map((node) => node.textContent)
    expect(svgLabels).toContain('0')
  })
})
