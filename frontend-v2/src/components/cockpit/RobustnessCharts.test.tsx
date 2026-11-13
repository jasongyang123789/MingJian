import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  reachableThresholdSearch,
  robustnessRead,
} from '../../test/engineFixtures'
import { BootstrapChart, ThresholdSearchChart, TornadoChart } from './RobustnessCharts'

const tornado = robustnessRead.tornado
const bootstrap = robustnessRead.bootstrap
const unreachable = robustnessRead.threshold_search

if (!tornado || !bootstrap || !unreachable) throw new Error('robustness fixture incomplete')

function svgTexts(chart: HTMLElement): (string | null)[] {
  return [...chart.querySelectorAll('svg text')].map((node) => node.textContent)
}

describe('TornadoChart', () => {
  it('renders rows ranked by swing with the base reference line', () => {
    const { container } = render(<TornadoChart tornado={tornado} />)
    const chart = screen.getByRole('img', { name: '龙卷风图' })
    const ticks = [...chart.querySelectorAll('.recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value')].map(
      (node) => node.textContent,
    )
    // Largest swing first: cash (64) above cac (0).
    expect(ticks).toEqual(['cash', 'cac'])
    expect(screen.getByText(/按摆动降序/)).toBeInTheDocument()
    expect(screen.getByText(/基线结果 100/)).toBeInTheDocument()
    const svgLabels = [...container.querySelectorAll('svg text')].map((node) => node.textContent)
    expect(svgLabels).toContain('基线')
    // The cac row has a zero-width range [100, 100]; recharts omits
    // zero-size bars, so only the cash bar renders — its tick remains.
    expect(chart.querySelectorAll('.recharts-bar-rectangle').length).toBe(1)
  })

  it('renders an empty note when there are no rows', () => {
    render(<TornadoChart tornado={{ ...tornado, rows: [] }} />)
    expect(screen.getByText(/没有行/)).toBeInTheDocument()
  })
})

describe('BootstrapChart', () => {
  it('renders interval bars with estimate dots for both arms', () => {
    render(<BootstrapChart bootstrap={bootstrap} />)
    const chart = screen.getByRole('img', { name: 'Bootstrap 区间图' })
    const ticks = [...chart.querySelectorAll('.recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value')].map(
      (node) => node.textContent,
    )
    expect(ticks).toEqual(['基线 · mean', '基线 · p_loss', '策略 · mean'])
    // The degenerate strategy interval [140, 140] renders no
    // rectangle; its estimate dot still marks the point.
    expect(chart.querySelectorAll('.recharts-bar-rectangle').length).toBe(2)
    // One estimate dot per interval.
    expect(chart.querySelectorAll('.recharts-line-dot').length).toBe(3)
    expect(screen.getByText(/90% percentile 区间/)).toBeInTheDocument()
  })
})

describe('ThresholdSearchChart', () => {
  it('renders the found threshold with its reference line', () => {
    render(<ThresholdSearchChart search={reachableThresholdSearch} />)
    const chart = screen.getByRole('img', { name: '阈值搜索图' })
    expect(screen.getByText(/找到阈值 105/)).toBeInTheDocument()
    expect(svgTexts(chart)).toContain('阈值')
    expect(svgTexts(chart)).toContain('目标')
    // One dot per probe point.
    expect(chart.querySelectorAll('.recharts-line-dot').length).toBe(5)
  })

  it('renders the honest unreachable state without a threshold line', () => {
    render(<ThresholdSearchChart search={unreachable} />)
    const chart = screen.getByRole('img', { name: '阈值搜索图' })
    expect(screen.getByText(/阈值不可达/)).toBeInTheDocument()
    expect(svgTexts(chart)).not.toContain('阈值')
    expect(svgTexts(chart)).toContain('目标')
    // The single probe point is still drawn.
    expect(chart.querySelectorAll('.recharts-line-dot').length).toBe(1)
  })
})
