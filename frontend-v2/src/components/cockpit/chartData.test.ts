import { describe, expect, it } from 'vitest'

import type { BootstrapResult, TornadoRow } from '../../api/engineTypes'
import {
  binEdgesFor,
  bootstrapChartRows,
  histogramBins,
  pairedDeltas,
  rankedTornadoRows,
  sharedBinEdges,
  sortedEvaluations,
  sturgesBinCount,
} from './chartData'

describe('chartData', () => {
  it('sizes bins by Sturges rule, clamped', () => {
    expect(sturgesBinCount(0)).toBe(5)
    expect(sturgesBinCount(5)).toBe(5)
    expect(sturgesBinCount(50)).toBe(7)
    expect(sturgesBinCount(200)).toBe(9)
    expect(sturgesBinCount(1_000_000)).toBe(21)
    expect(sturgesBinCount(1_000_000_000)).toBe(30)
  })

  it('bins values into equal-width bins, max value in the last bin', () => {
    const edges = binEdgesFor([0, 10], 5)
    expect(edges).toEqual({ start: 0, width: 2, count: 5 })
    const bins = histogramBins([0, 1, 2, 5, 9.9, 10], edges, null)
    expect(bins.map((bin) => bin.count)).toEqual([2, 1, 1, 0, 2])
    expect(bins[0]).toMatchObject({ start: 0, end: 2, mid: 1 })
  })

  it('marks bins fully below the loss threshold', () => {
    const edges = binEdgesFor([0, 10], 5)
    const bins = histogramBins([0, 5, 10], edges, 4)
    expect(bins.map((bin) => bin.belowThreshold)).toEqual([true, true, false, false, false])
  })

  it('renders a degenerate arm as a single spike bin', () => {
    const edges = binEdgesFor([140, 140, 140], 5)
    const bins = histogramBins([140, 140, 140], edges, 90)
    expect(bins.map((bin) => bin.count)).toEqual([0, 0, 3, 0, 0])
    expect(bins.every((bin) => !bin.belowThreshold)).toBe(true)
  })

  it('shares bin edges across arms', () => {
    const edges = sharedBinEdges([0, 10], [100, 110], 5)
    expect(edges.start).toBe(0)
    expect(edges.width).toBe(22)
    const baseline = histogramBins([0, 10], edges, null)
    const strategy = histogramBins([100, 110], edges, null)
    expect(baseline[0].count).toBe(2)
    expect(strategy[4].count).toBe(2)
  })

  it('pairs deltas by trial index, truncated to the shorter arm', () => {
    expect(pairedDeltas([10, 20, 30], [15, 15, 15])).toEqual([5, -5, -15])
    expect(pairedDeltas([10, 20], [15, 15, 15])).toEqual([5, -5])
    expect(pairedDeltas([], [1])).toEqual([])
  })

  it('ranks tornado rows by swing descending', () => {
    const rows = [
      { variable: 'a', swing: 5 },
      { variable: 'b', swing: 40 },
      { variable: 'c', swing: 12 },
    ] as TornadoRow[]
    expect(rankedTornadoRows(rows).map((row) => row.variable)).toEqual(['b', 'c', 'a'])
    // Input order untouched.
    expect(rows[0].variable).toBe('a')
  })

  it('sorts threshold evaluations by value', () => {
    const evaluations = [
      { value: 30, statistic: 0.1, trials: 10, probe_run_ids: [] },
      { value: 10, statistic: 0.4, trials: 10, probe_run_ids: [] },
      { value: 20, statistic: 0.2, trials: 10, probe_run_ids: [] },
    ]
    expect(sortedEvaluations(evaluations).map((entry) => entry.value)).toEqual([10, 20, 30])
  })

  it('flattens bootstrap intervals into chart rows, baseline first', () => {
    const result = {
      baseline: [{ statistic: 'mean', estimate: 99, low: 90, high: 108, draws: 1000, seed: 1, level: 0.95, method: 'percentile' }],
      strategy: [{ statistic: 'mean', estimate: 140, low: 140, high: 140, draws: 1000, seed: 1, level: 0.95, method: 'percentile' }],
    } as BootstrapResult
    const rows = bootstrapChartRows(result)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ label: '基线 · mean', interval: [90, 108], estimate: 99 })
    expect(rows[1]).toMatchObject({ label: '策略 · mean', interval: [140, 140], estimate: 140 })
  })
})
