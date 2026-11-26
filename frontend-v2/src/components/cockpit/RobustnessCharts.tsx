// Robustness charts over stored Sprint 4 results: tornado swings,
// bootstrap intervals, and threshold-search probes. Rows render as
// stored; the only transforms are ranking (tornado) and sorting
// (threshold probes) in chartData.ts. Fixed sizes, no animation, so
// rendering is deterministic.

import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type {
  BootstrapResult,
  ThresholdSearchResult,
  TornadoResult,
} from '../../api/engineTypes'
import { formatNumber, formatShare } from './format'
import {
  bootstrapChartRows,
  rankedTornadoRows,
  sortedEvaluations,
} from './chartData'

const CHART_WIDTH = 720
const AXIS_TICK = { fill: '#94a3b8', fontSize: 12 }
const GRID_STROKE = '#1e293b'

export function TornadoChart({ tornado }: { tornado: TornadoResult }) {
  const rows = rankedTornadoRows(tornado.rows).map((row) => ({
    ...row,
    range: [row.outcome_low, row.outcome_high] as [number, number],
  }))
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">龙卷风分析没有行——后端返回了空结果。</p>
  }
  const base = rows[0].outcome_base
  const height = Math.min(560, 80 + rows.length * 40)
  return (
    <div role="img" aria-label="龙卷风图">
      <BarChart
        layout="vertical"
        width={CHART_WIDTH}
        height={height}
        data={rows}
        margin={{ top: 8, right: 24, bottom: 24, left: 8 }}
      >
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" horizontal={false} />
        <XAxis
          type="number"
          tick={AXIS_TICK}
          tickFormatter={(value: number) => formatNumber(value)}
          label={{ value: tornado.metric, position: 'insideBottom', offset: -8, fill: '#64748b', fontSize: 12 }}
        />
        <YAxis type="category" dataKey="variable" width={110} tick={AXIS_TICK} />
        <Tooltip
          formatter={(value, name) => {
            if (name === 'range' && Array.isArray(value)) {
              return [`${formatNumber(value[0])} → ${formatNumber(value[1])}`, '结果区间']
            }
            return [value, String(name)]
          }}
        />
        <ReferenceLine x={base} stroke="#e2e8f0" strokeDasharray="4 4" label="基线" />
        <Bar dataKey="range" fill="#60a5fa" barSize={20} isAnimationActive={false} />
      </BarChart>
      <p className="mt-1 text-xs leading-5 text-slate-500">
        按摆动降序；每条为变量从 P{Math.round(tornado.low_quantile * 100)} 摆动到 P
        {Math.round(tornado.high_quantile * 100)} 时的结果区间，其余变量取中位数。基线结果{' '}
        {formatNumber(base)}。行来自存储的龙卷风分析（{rows.length} 行）。
      </p>
    </div>
  )
}

export function BootstrapChart({ bootstrap }: { bootstrap: BootstrapResult }) {
  const rows = bootstrapChartRows(bootstrap)
  if (rows.length === 0) {
    return <p className="text-sm text-slate-500">Bootstrap 分析没有区间——后端返回了空结果。</p>
  }
  const height = Math.min(560, 80 + rows.length * 40)
  const first = bootstrap.baseline[0] ?? bootstrap.strategy[0]
  return (
    <div role="img" aria-label="自助法区间图">
      <ComposedChart
        layout="vertical"
        width={CHART_WIDTH}
        height={height}
        data={rows}
        margin={{ top: 8, right: 24, bottom: 24, left: 8 }}
      >
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" horizontal={false} />
        <XAxis
          type="number"
          tick={AXIS_TICK}
          tickFormatter={(value: number) => formatNumber(value)}
          label={{ value: bootstrap.metric, position: 'insideBottom', offset: -8, fill: '#64748b', fontSize: 12 }}
        />
        <YAxis type="category" dataKey="label" width={140} tick={AXIS_TICK} />
        <Tooltip
          formatter={(value, name) => {
            if (name === 'interval' && Array.isArray(value)) {
              return [`${formatNumber(value[0])} → ${formatNumber(value[1])}`, '区间']
            }
            if (name === 'estimate') return [formatNumber(Number(value)), '估计值']
            return [value, String(name)]
          }}
        />
        <Bar dataKey="interval" fill="#60a5fa" barSize={16} isAnimationActive={false} />
        <Line
          dataKey="estimate"
          stroke="none"
          dot={{ r: 4, fill: '#e2e8f0', strokeWidth: 0 }}
          isAnimationActive={false}
          legendType="none"
        />
      </ComposedChart>
      <p className="mt-1 text-xs leading-5 text-slate-500">
        横条为 {first ? `${Math.round(first.level * 100)}% ${first.method} 区间（${first.draws} 次抽取）` : '区间'}
        ，白点为点估计。行来自存储的 bootstrap 分析。
      </p>
    </div>
  )
}

export function ThresholdSearchChart({ search }: { search: ThresholdSearchResult }) {
  const points = sortedEvaluations(search.evaluations)
  if (points.length === 0) {
    return <p className="text-sm text-slate-500">阈值搜索没有探针点——后端返回了空结果。</p>
  }
  const statisticLabel = search.mode === 'p_loss' ? '亏损概率' : '臂差值（策略 − 基线）'
  return (
    <div role="img" aria-label="阈值搜索图">
      <LineChart width={CHART_WIDTH} height={320} data={points} margin={{ top: 16, right: 16, bottom: 24, left: 48 }}>
        <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" />
        <XAxis
          type="number"
          dataKey="value"
          domain={[search.bounds[0], search.bounds[1]]}
          tick={AXIS_TICK}
          tickFormatter={(value: number) => formatNumber(value)}
          label={{ value: search.variable, position: 'insideBottom', offset: -8, fill: '#64748b', fontSize: 12 }}
        />
        <YAxis
          tick={AXIS_TICK}
          tickFormatter={(value: number) => formatNumber(value)}
          label={{ value: statisticLabel, angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 12 }}
        />
        <Tooltip
          formatter={(value) => [formatNumber(Number(value)), statisticLabel]}
          labelFormatter={(label) => `${search.variable} = ${formatNumber(Number(label))}`}
        />
        <ReferenceLine y={search.target} stroke="#f87171" strokeDasharray="4 4" label="目标" />
        {search.reachable && search.threshold !== null && (
          <ReferenceLine x={search.threshold} stroke="#e2e8f0" strokeDasharray="4 4" label="阈值" />
        )}
        <Line
          type="linear"
          dataKey="statistic"
          stroke="#60a5fa"
          strokeWidth={2}
          dot={{ r: 3, fill: '#60a5fa' }}
          isAnimationActive={false}
        />
      </LineChart>
      {search.reachable && search.threshold !== null ? (
        <p className="mt-1 text-xs leading-5 text-slate-500">
          找到阈值 {formatNumber(search.threshold)}（{search.variable}，目标{' '}
          {search.mode === 'p_loss' ? formatShare(search.target) : formatNumber(search.target)}，达到统计量{' '}
          {search.achieved_statistic !== null ? formatNumber(search.achieved_statistic) : '—'}，{search.iterations}{' '}
          次迭代，{points.length} 个探针点）。
        </p>
      ) : (
        <p className="mt-1 text-xs leading-5 text-amber-300">
          未达到目标：在搜索边界 [{formatNumber(search.bounds[0])}, {formatNumber(search.bounds[1])}]
          内没有探针点越过目标线——阈值不可达，不是作图缺失。{points.length} 个探针点如实画出。
        </p>
      )}
    </div>
  )
}
