// Ensemble distribution charts over stored trial values (fetched from
// the read-only trial-values endpoint). Histograms bin the trial values;
// the P10/P50/P90 markers and loss probabilities are the backend's
// stored summary statistics, never recomputed from the bins. Fixed
// sizes throughout: no ResponsiveContainer, so rendering is
// deterministic in jsdom and identical on every load.

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type {
  DistributionSummary,
  MonteCarloResult,
  MonteCarloTrialValues,
  PairedDeltaSummary,
} from '../../api/engineTypes'
import { formatNumber, formatShare } from './format'
import {
  binEdgesFor,
  histogramBins,
  pairedDeltas,
  sharedBinEdges,
  sturgesBinCount,
} from './chartData'
import type { BinEdges } from './chartData'

const CHART_WIDTH = 720
const CHART_HEIGHT = 320
const AXIS_TICK = { fill: '#94a3b8', fontSize: 12 }
const GRID_STROKE = '#1e293b'

function barSizeFor(binCount: number): number {
  const plotWidth = CHART_WIDTH - 48 - 16
  return Math.max(4, Math.floor(plotWidth / binCount) - 2)
}

function ArmHistogram({
  label,
  values,
  summary,
  lossThreshold,
  edges,
  color,
}: {
  label: string
  values: number[]
  summary: DistributionSummary
  lossThreshold: number
  edges: BinEdges
  color: string
}) {
  const bins = histogramBins(values, edges, lossThreshold)
  const domain: [number, number] = [edges.start, edges.start + edges.width * edges.count]
  return (
    <div role="img" aria-label={`${label}分布直方图`}>
      <h4 className="mb-2 text-sm font-medium text-slate-200">{label}</h4>
      <BarChart width={CHART_WIDTH} height={CHART_HEIGHT} data={bins} margin={{ top: 16, right: 16, bottom: 24, left: 48 }}>
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
        <XAxis
          type="number"
          dataKey="mid"
          domain={domain}
          tick={AXIS_TICK}
          tickFormatter={(value: number) => formatNumber(value)}
          label={{ value: '终值', position: 'insideBottom', offset: -8, fill: '#64748b', fontSize: 12 }}
        />
        <YAxis allowDecimals={false} tick={AXIS_TICK} label={{ value: 'trial 数', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 12 }} />
        <Tooltip
          formatter={(value, name) => [value, name === 'count' ? 'trial 数' : String(name)]}
          labelFormatter={(label) => `bin 中点 ${formatNumber(Number(label))}`}
        />
        <ReferenceLine x={summary.p10} stroke="#94a3b8" strokeDasharray="4 4" label="P10" />
        <ReferenceLine x={summary.p50} stroke="#e2e8f0" strokeDasharray="4 4" label="P50" />
        <ReferenceLine x={summary.p90} stroke="#94a3b8" strokeDasharray="4 4" label="P90" />
        <ReferenceLine x={lossThreshold} stroke="#f87171" strokeDasharray="2 2" label="阈值" />
        <Bar dataKey="count" barSize={barSizeFor(edges.count)} isAnimationActive={false}>
          {bins.map((bin, index) => (
            <Cell key={index} fill={bin.belowThreshold ? '#f87171' : color} />
          ))}
        </Bar>
      </BarChart>
      <p className="mt-1 text-xs leading-5 text-slate-500">
        n={summary.n} · P10 {formatNumber(summary.p10)} · P50 {formatNumber(summary.p50)} · P90{' '}
        {formatNumber(summary.p90)} · 亏损概率 {formatShare(summary.p_loss)}（阈值 {formatNumber(lossThreshold)}）。
        红色 bin：该 bin 全部 trial 均低于阈值。P10/P50/P90 与亏损概率为后端摘要统计量。
      </p>
    </div>
  )
}

function DeltaHistogram({ deltas, paired }: { deltas: number[]; paired: PairedDeltaSummary }) {
  const edges = binEdgesFor(deltas, sturgesBinCount(deltas.length))
  const bins = histogramBins(deltas, edges, null)
  const domain: [number, number] = [edges.start, edges.start + edges.width * edges.count]
  return (
    <div role="img" aria-label="配对差值直方图">
      <h4 className="mb-2 text-sm font-medium text-slate-200">配对差值（策略 − 基线，按 trial 索引配对）</h4>
      <BarChart width={CHART_WIDTH} height={CHART_HEIGHT} data={bins} margin={{ top: 16, right: 16, bottom: 24, left: 48 }}>
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
        <XAxis
          type="number"
          dataKey="mid"
          domain={domain}
          tick={AXIS_TICK}
          tickFormatter={(value: number) => formatNumber(value)}
          label={{ value: '差值', position: 'insideBottom', offset: -8, fill: '#64748b', fontSize: 12 }}
        />
        <YAxis allowDecimals={false} tick={AXIS_TICK} label={{ value: 'trial 数', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 12 }} />
        <Tooltip
          formatter={(value, name) => [value, name === 'count' ? 'trial 数' : String(name)]}
          labelFormatter={(label) => `bin 中点 ${formatNumber(Number(label))}`}
        />
        <ReferenceLine x={0} stroke="#64748b" label="0" />
        <ReferenceLine x={paired.p50} stroke="#e2e8f0" strokeDasharray="4 4" label="P50" />
        <Bar dataKey="count" fill="#2dd4bf" barSize={barSizeFor(edges.count)} isAnimationActive={false} />
      </BarChart>
      <p className="mt-1 text-xs leading-5 text-slate-500">
        n={paired.n} · 均值差 {formatNumber(paired.mean_delta)} · P10 {formatNumber(paired.p10)} · P50{' '}
        {formatNumber(paired.p50)} · P90 {formatNumber(paired.p90)} · 策略更优概率 {formatShare(paired.p_strategy_better)}。
        直方图为展示用派生（按 trial 索引相减）；摘要数字为后端配对统计量。
      </p>
    </div>
  )
}

export function EnsembleHistograms({
  result,
  trialValues,
}: {
  result: MonteCarloResult
  trialValues: MonteCarloTrialValues
}) {
  const binCount = sturgesBinCount(Math.max(trialValues.baseline.length, trialValues.strategy.length))
  const edges = sharedBinEdges(trialValues.baseline, trialValues.strategy, binCount)
  const deltas = pairedDeltas(trialValues.baseline, trialValues.strategy)
  return (
    <div className="space-y-8">
      <ArmHistogram
        label="基线臂"
        values={trialValues.baseline}
        summary={result.baseline}
        lossThreshold={result.loss_threshold}
        edges={edges}
        color="#60a5fa"
      />
      <ArmHistogram
        label="策略臂"
        values={trialValues.strategy}
        summary={result.strategy}
        lossThreshold={result.loss_threshold}
        edges={edges}
        color="#a78bfa"
      />
      {deltas.length > 0 && <DeltaHistogram deltas={deltas} paired={result.paired} />}
      <p className="text-xs leading-5 text-slate-500">
        直方图来自存储的 trial 值（ensemble {result.ensemble_id}，{trialValues.trial_values_hash}）。两臂共享 bin
        边界，可直接比较形状。
      </p>
    </div>
  )
}
