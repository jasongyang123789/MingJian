// Pure data transforms for the distribution charts. Everything here is
// derived from stored backend values only: histograms bin trial values
// fetched from the read-only trial-values endpoint, tornado/bootstrap/
// threshold rows are rendered as stored. Display rounding happens at
// render time (format.ts); nothing computed here flows back into any
// stored value.

import type {
  BootstrapResult,
  ThresholdEvaluation,
  TornadoRow,
} from '../../api/engineTypes'

export interface HistogramBin {
  start: number
  end: number
  mid: number
  count: number
  /** True when the whole bin sits at or below the loss threshold. */
  belowThreshold: boolean
}

export interface BinEdges {
  start: number
  width: number
  count: number
}

/** Sturges' rule, clamped so small ensembles stay readable and large ones bounded. */
export function sturgesBinCount(n: number): number {
  if (n <= 1) return 5
  return Math.min(30, Math.max(5, Math.ceil(Math.log2(n)) + 1))
}

export function binEdgesFor(values: number[], binCount: number): BinEdges {
  const min = Math.min(...values)
  const max = Math.max(...values)
  let start = min
  let width = (max - min) / binCount
  if (width === 0) {
    // Degenerate arm (every trial identical): a unit-wide window
    // centered on the value, so the spike renders in the middle bin
    // instead of dividing by zero.
    width = 1
    start = min - (binCount * width) / 2
  }
  return { start, width, count: binCount }
}

export function sharedBinEdges(baseline: number[], strategy: number[], binCount: number): BinEdges {
  return binEdgesFor([...baseline, ...strategy], binCount)
}

export function histogramBins(
  values: number[],
  edges: BinEdges,
  lossThreshold: number | null,
): HistogramBin[] {
  const counts = new Array<number>(edges.count).fill(0)
  for (const value of values) {
    let index = Math.floor((value - edges.start) / edges.width)
    if (index < 0) index = 0
    if (index >= edges.count) index = edges.count - 1
    counts[index] += 1
  }
  return counts.map((count, index) => {
    const start = edges.start + index * edges.width
    const end = start + edges.width
    return {
      start,
      end,
      mid: (start + end) / 2,
      count,
      belowThreshold: lossThreshold !== null && end <= lossThreshold,
    }
  })
}

/**
 * Paired deltas (strategy − baseline) by trial index, truncated to the
 * shorter arm. Display-only: the backend's paired summary is the
 * authoritative statistic; this only shapes the delta histogram.
 */
export function pairedDeltas(baseline: number[], strategy: number[]): number[] {
  const n = Math.min(baseline.length, strategy.length)
  const deltas: number[] = []
  for (let i = 0; i < n; i += 1) deltas.push(strategy[i] - baseline[i])
  return deltas
}

/** Tornado rows ranked by swing, largest first (the backend stores them ranked). */
export function rankedTornadoRows(rows: TornadoRow[]): TornadoRow[] {
  return [...rows].sort((a, b) => b.swing - a.swing)
}

/** Threshold-search probes in increasing value order, for the line chart. */
export function sortedEvaluations(evaluations: ThresholdEvaluation[]): ThresholdEvaluation[] {
  return [...evaluations].sort((a, b) => a.value - b.value)
}

export interface BootstrapChartRow {
  label: string
  arm: 'baseline' | 'strategy'
  statistic: string
  estimate: number
  low: number
  high: number
  interval: [number, number]
}

export function bootstrapChartRows(result: BootstrapResult): BootstrapChartRow[] {
  const rows: BootstrapChartRow[] = []
  for (const arm of ['baseline', 'strategy'] as const) {
    for (const interval of result[arm]) {
      rows.push({
        label: `${arm === 'baseline' ? '基线' : '策略'} · ${interval.statistic}`,
        arm,
        statistic: interval.statistic,
        estimate: interval.estimate,
        low: interval.low,
        high: interval.high,
        interval: [interval.low, interval.high],
      })
    }
  }
  return rows
}
