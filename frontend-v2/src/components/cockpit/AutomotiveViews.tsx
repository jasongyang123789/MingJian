// Automotive cockpit views (Phase 2; S-layer charts added 2026-11-20):
// trajectory chart, S-layer charts (per-tick totals + per-tick ×
// OEM × product detail stacks), co-occurrence prompt list, and the
// expectation catalog. Fixed chart sizes throughout (no
// ResponsiveContainer), matching the distribution charts: deterministic
// rendering in jsdom and identical on every load. All values are stored
// backend values, never recomputed here; the S-layer totals are the
// backend's own summary. The two original S-layer tables survive
// verbatim inside a collapsed "精确数值" fold-out, so the charts are
// the presentation and the tables are the precision appendix — every
// field the tables carried is still in the DOM.

import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import type {
  AutomotiveTrajectoryRead,
  CooccurrencePrompt,
  ExpectationCatalogEntry,
  PromptReportRead,
  SalesLayerRead,
} from '../../api/engineTypes'
import { detailSegments, detailSeriesByTick } from './automotiveUtils'
import type { DetailMeasure } from './automotiveUtils'
import { formatNumber, formatShare } from './format'

const CHART_WIDTH = 720
const CHART_HEIGHT = 320
const AXIS_TICK = { fill: '#94a3b8', fontSize: 12 }
const GRID_STROKE = '#1e293b'

const SERIES = [
  { key: 'production_volume', label: '产量（主轴）', stroke: '#60a5fa' },
  { key: 'sales_volume_retail', label: '零售', stroke: '#34d399' },
  { key: 'nev_production_volume', label: 'NEV 产量', stroke: '#f472b6' },
  { key: 'ice_production_volume', label: 'ICE 产量', stroke: '#fbbf24' },
]

export function TrajectoryChart({ trajectory }: { trajectory: AutomotiveTrajectoryRead }) {
  const data = trajectory.points.map((point) => ({ tick: point.tick, ...point.state }))
  const first = trajectory.points[0]?.state
  const last = trajectory.points[trajectory.points.length - 1]?.state
  return (
    <div className="space-y-4">
      <LineChart width={CHART_WIDTH} height={CHART_HEIGHT} data={data}>
        <CartesianGrid stroke={GRID_STROKE} />
        <XAxis dataKey="tick" tick={AXIS_TICK} label={{ value: 'tick（月）', fill: '#94a3b8', fontSize: 12 }} />
        <YAxis tick={AXIS_TICK} width={64} />
        <Tooltip
          contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: 8 }}
          labelStyle={{ color: '#e2e8f0' }}
        />
        <Legend />
        {SERIES.map((series) => (
          <Line
            key={series.key}
            type="monotone"
            dataKey={series.key}
            name={series.label}
            stroke={series.stroke}
            dot={false}
            strokeWidth={2}
          />
        ))}
      </LineChart>
      {first && last && (
        <p className="text-xs text-slate-400">
          NEV 渗透率：{formatShare(first.nev_penetration ?? 0)} → {formatShare(last.nev_penetration ?? 0)}；
          产量：{formatNumber(first.production_volume ?? 0)} → {formatNumber(last.production_volume ?? 0)} 万辆/月；
          零售：{formatNumber(first.sales_volume_retail ?? 0)} → {formatNumber(last.sales_volume_retail ?? 0)} 万辆/月。
        </p>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-700/50 text-xs text-slate-400">
              <th className="py-2 pr-4 font-medium">Tick</th>
              <th className="py-2 pr-4 font-medium">产量</th>
              <th className="py-2 pr-4 font-medium">零售</th>
              <th className="py-2 pr-4 font-medium">NEV 产量</th>
              <th className="py-2 pr-4 font-medium">ICE 产量</th>
              <th className="py-2 pr-4 font-medium">NEV 渗透率</th>
              <th className="py-2 font-medium">库存系数</th>
            </tr>
          </thead>
          <tbody>
            {trajectory.points.map((point) => (
              <tr key={point.tick} className="border-b border-slate-800/50 text-slate-200">
                <td className="py-1.5 pr-4">{point.tick}</td>
                <td className="py-1.5 pr-4">{formatNumber(point.state.production_volume ?? 0)}</td>
                <td className="py-1.5 pr-4">{formatNumber(point.state.sales_volume_retail ?? 0)}</td>
                <td className="py-1.5 pr-4">{formatNumber(point.state.nev_production_volume ?? 0)}</td>
                <td className="py-1.5 pr-4">{formatNumber(point.state.ice_production_volume ?? 0)}</td>
                <td className="py-1.5 pr-4">{formatShare(point.state.nev_penetration ?? 0)}</td>
                <td className="py-1.5">{formatNumber(point.state.dealer_inventory_coef ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const DETAIL_MEASURES: Array<{ key: DetailMeasure; label: string }> = [
  { key: 'capacity_value', label: '容量' },
  { key: 'units', label: '件数' },
  { key: 'own_sales', label: '自有销售' },
]

const SEGMENT_COLORS = [
  '#60a5fa',
  '#34d399',
  '#fbbf24',
  '#f472b6',
  '#a78bfa',
  '#22d3ee',
  '#fb923c',
  '#a3e635',
]

/** Per-tick totals as four lines over tick (the old per-tick table's
 * four numeric columns). Two axes because the measures live on two
 * scales: left = 产量（万辆/月）+ 件数, right = 容量 + 自有销售
 * （金额）. A null own_sales breaks its line (recharts gap), never a
 * silent zero — matching the table's '—'. */
export function SalesLayerPerTickChart({ layer }: { layer: SalesLayerRead }) {
  const hasOwnSales = layer.per_tick.some((tick) => tick.own_sales !== null)
  if (layer.per_tick.length === 0) {
    return <p className="text-sm text-slate-400">暂无逐 tick 数据。</p>
  }
  return (
    <div className="space-y-2">
      <div role="img" aria-label="S 层逐 tick 总量图">
        <ComposedChart
          width={CHART_WIDTH}
          height={CHART_HEIGHT}
          data={layer.per_tick}
          margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
        >
          <CartesianGrid stroke={GRID_STROKE} />
          <XAxis
            dataKey="tick"
            tick={AXIS_TICK}
            label={{ value: 'tick（月）', fill: '#94a3b8', fontSize: 12 }}
          />
          <YAxis
            yAxisId="volume"
            tick={AXIS_TICK}
            width={64}
            label={{ value: '量', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 12 }}
          />
          <YAxis yAxisId="value" orientation="right" tick={AXIS_TICK} width={72} />
          <Tooltip
            contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: 8 }}
            labelStyle={{ color: '#e2e8f0' }}
            formatter={(value, name) => [formatNumber(Number(value)), String(name)]}
            labelFormatter={(label) => `Tick ${label}`}
          />
          <Legend />
          <Line
            yAxisId="volume"
            type="monotone"
            dataKey="production_volume"
            name="产量（主轴）"
            stroke="#60a5fa"
            dot={false}
            strokeWidth={2}
          />
          <Line
            yAxisId="volume"
            type="monotone"
            dataKey="units"
            name="件数"
            stroke="#34d399"
            dot={false}
            strokeWidth={2}
          />
          <Line
            yAxisId="value"
            type="monotone"
            dataKey="capacity_value"
            name="容量"
            stroke="#fbbf24"
            dot={false}
            strokeWidth={2}
          />
          {hasOwnSales && (
            <Line
              yAxisId="value"
              type="monotone"
              dataKey="own_sales"
              name="自有销售"
              stroke="#f472b6"
              dot={false}
              strokeWidth={2}
            />
          )}
        </ComposedChart>
      </div>
      <p className="text-xs text-slate-400">
        左轴：产量（万辆/月）与件数；右轴：容量与自有销售（金额）。悬停查看每 tick 精确数值。
        {hasOwnSales ? '' : ' 自有销售未归属，图中不含自有销售线。'}
      </p>
    </div>
  )
}

/** Detail rows as one stacked bar per tick, segments = OEM × 产品
 * (the old detail table's tick × OEM × product rows, pivoted). The
 * measure toggle switches which of the table's three numeric columns
 * the stack shows — 容量 / 件数 / 自有销售 — so every row's every
 * number is charted. A null own_sales counts as 0 in the stack; the
 * exact-value table below keeps the literal null as '—'. */
export function SalesLayerDetailChart({ layer }: { layer: SalesLayerRead }) {
  const [measure, setMeasure] = useState<DetailMeasure>('capacity_value')
  const segments = detailSegments(layer.rows)
  const measureLabel = DETAIL_MEASURES.find((entry) => entry.key === measure)?.label ?? '容量'
  const ownSalesAllNull = measure === 'own_sales' && layer.rows.every((row) => row.own_sales === null)
  if (layer.rows.length === 0) {
    return <p className="text-sm text-slate-400">暂无明细行。</p>
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="明细度量">
        {DETAIL_MEASURES.map((entry) => (
          <button
            key={entry.key}
            type="button"
            aria-pressed={measure === entry.key}
            onClick={() => setMeasure(entry.key)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
              measure === entry.key
                ? 'border-blue-500/50 bg-blue-500/20 text-blue-200'
                : 'border-slate-700/50 bg-slate-800/40 text-slate-300 hover:bg-slate-800'
            }`}
          >
            {entry.label}
          </button>
        ))}
      </div>
      {ownSalesAllNull ? (
        <p className="text-sm text-slate-400">
          自有销售未归属：明细行全部无自有销售值，无法绘出自有销售堆叠。切换容量或件数查看明细。
        </p>
      ) : (
        <div className="space-y-2">
          <div role="img" aria-label={`S 层明细堆叠图（${measureLabel}）`}>
            <BarChart
              width={CHART_WIDTH}
              height={CHART_HEIGHT}
              data={detailSeriesByTick(layer.rows, measure)}
              margin={{ top: 8, right: 16, bottom: 8, left: 8 }}
            >
              <CartesianGrid stroke={GRID_STROKE} />
              <XAxis
                dataKey="tick"
                tick={AXIS_TICK}
                label={{ value: 'tick（月）', fill: '#94a3b8', fontSize: 12 }}
              />
              <YAxis tick={AXIS_TICK} width={72} />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: 8 }}
                labelStyle={{ color: '#e2e8f0' }}
                formatter={(value, name) => [formatNumber(Number(value)), String(name)]}
                labelFormatter={(label) => `Tick ${label}`}
              />
              <Legend />
              {segments.map((segment, index) => (
                <Bar
                  key={segment}
                  dataKey={segment}
                  name={segment}
                  stackId="detail"
                  fill={SEGMENT_COLORS[index % SEGMENT_COLORS.length]}
                />
              ))}
            </BarChart>
          </div>
          <p className="text-xs text-slate-400">
            每段 = 该 tick 下同一 OEM × 产品的行合计（同 tick 同 OEM 同产品有多行时求和，见下方精确数值表）；
            整条柱高 = 该 tick 明细合计。悬停查看每段精确数值。
          </p>
        </div>
      )}
    </div>
  )
}

export function SalesLayerView({ layer }: { layer: SalesLayerRead }) {
  const { summary } = layer
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4 text-sm">
        <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 px-4 py-3">
          <div className="text-xs text-slate-400">总容量（全市场）</div>
          <div className="mt-1 font-medium text-slate-100">{formatNumber(summary.total_capacity_value)}</div>
        </div>
        <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 px-4 py-3">
          <div className="text-xs text-slate-400">自有销售</div>
          <div className="mt-1 font-medium text-slate-100">
            {summary.total_own_sales === null ? '未归属（见下）' : formatNumber(summary.total_own_sales)}
          </div>
        </div>
        <div className="rounded-lg border border-slate-700/50 bg-slate-800/30 px-4 py-3">
          <div className="text-xs text-slate-400">总件数 / 覆盖</div>
          <div className="mt-1 font-medium text-slate-100">
            {formatNumber(summary.total_units)} · {summary.tick_count} ticks · {summary.oem_count} OEM ·{' '}
            {summary.product_count} 产品
          </div>
        </div>
      </div>
      {layer.own_sales_basis === 'unavailable' && (
        <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-300">
          自有销售未归属：{layer.own_sales_unavailable_reason}
        </p>
      )}
      {layer.skipped_unpriced_slots.length > 0 && (
        <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-sm text-amber-300">
          非严格价格模式跳过了 {layer.skipped_unpriced_slots.length} 个无价槽位（容量不含它们，件数含）：
          {layer.skipped_unpriced_slots.join('；')}
        </p>
      )}
      <div>
        <h4 className="mb-2 text-sm font-medium text-slate-200">逐 tick 总量</h4>
        <SalesLayerPerTickChart layer={layer} />
      </div>
      <div>
        <h4 className="mb-2 text-sm font-medium text-slate-200">逐 tick × OEM × 产品明细</h4>
        <SalesLayerDetailChart layer={layer} />
      </div>
      <details className="text-sm text-slate-400">
        <summary className="cursor-pointer text-slate-300">
          精确数值（与图表同源：逐 tick 总量表 + 明细表）
        </summary>
        <div className="mt-3 space-y-4">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 text-xs text-slate-400">
                  <th className="py-2 pr-4 font-medium">Tick</th>
                  <th className="py-2 pr-4 font-medium">产量（主轴）</th>
                  <th className="py-2 pr-4 font-medium">容量</th>
                  <th className="py-2 pr-4 font-medium">件数</th>
                  <th className="py-2 font-medium">自有销售</th>
                </tr>
              </thead>
              <tbody>
                {layer.per_tick.map((tick) => (
                  <tr key={tick.tick} className="border-b border-slate-800/50 text-slate-200">
                    <td className="py-1.5 pr-4">{tick.tick}</td>
                    <td className="py-1.5 pr-4">{formatNumber(tick.production_volume)}</td>
                    <td className="py-1.5 pr-4">{formatNumber(tick.capacity_value)}</td>
                    <td className="py-1.5 pr-4">{formatNumber(tick.units)}</td>
                    <td className="py-1.5">{tick.own_sales === null ? '—' : formatNumber(tick.own_sales)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700/50 text-xs text-slate-400">
                  <th className="py-2 pr-4 font-medium">Tick</th>
                  <th className="py-2 pr-4 font-medium">OEM</th>
                  <th className="py-2 pr-4 font-medium">产品</th>
                  <th className="py-2 pr-4 font-medium">件数</th>
                  <th className="py-2 pr-4 font-medium">容量</th>
                  <th className="py-2 font-medium">自有销售</th>
                </tr>
              </thead>
              <tbody>
                {layer.rows.map((row, index) => (
                  <tr
                    key={`${row.tick}-${row.oem_id}-${row.product_id}-${index}`}
                    className="border-b border-slate-800/50 text-slate-200"
                  >
                    <td className="py-1.5 pr-4">{row.tick}</td>
                    <td className="py-1.5 pr-4">{row.oem_id}</td>
                    <td className="py-1.5 pr-4">{row.product_id}</td>
                    <td className="py-1.5 pr-4">{formatNumber(row.units)}</td>
                    <td className="py-1.5 pr-4">{formatNumber(row.capacity_value)}</td>
                    <td className="py-1.5">{row.own_sales === null ? '—' : formatNumber(row.own_sales)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </details>
      <details className="text-sm text-slate-400">
        <summary className="cursor-pointer text-slate-300">计算假设（{layer.assumptions.length} 条）</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {layer.assumptions.map((assumption) => (
            <li key={assumption}>{assumption}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}

function PromptCard({ prompt }: { prompt: CooccurrencePrompt }) {
  const isAnomaly = prompt.severity === 'anomaly'
  return (
    <article
      className={`rounded-lg border px-4 py-3 ${
        isAnomaly ? 'border-red-500/30 bg-red-500/5' : 'border-slate-700/50 bg-slate-800/30'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${
            isAnomaly ? 'bg-red-500/15 text-red-300' : 'bg-slate-700/50 text-slate-300'
          }`}
        >
          {isAnomaly ? '逻辑异常' : '提示'}
        </span>
        <span className="font-mono text-xs text-slate-400">{prompt.rule_id}</span>
        <h4 className="text-sm font-medium text-slate-100">{prompt.title}</h4>
      </div>
      <p className="mt-2 text-sm text-slate-200">
        <span className="text-slate-400">观测：</span>
        {prompt.observed}
      </p>
      <p className="mt-1 text-sm text-slate-200">
        <span className="text-slate-400">正常逻辑应然：</span>
        {prompt.expected_logic}
      </p>
      {prompt.likely_explanations.length > 0 && (
        <p className="mt-1 text-sm text-slate-400">
          可能解释：{prompt.likely_explanations.join('；')}
        </p>
      )}
      <p className="mt-1 font-mono text-xs text-slate-500">
        {prompt.path} · 适用范围：{prompt.scope} · 证据：{prompt.evidence_ref}
      </p>
    </article>
  )
}

export function PromptList({ report }: { report: PromptReportRead }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-300">
        {report.anomaly_count} 条逻辑异常 · {report.info_count} 条提示 · 已评估规则{' '}
        {report.rules_evaluated.length} 条 · 未评估 {report.rules_skipped.length} 条。
        提示是概率性期望（“大概率”），不是硬规则：只标注、不拒绝、不修正。
      </p>
      {report.prompts.length === 0 && (
        <p className="text-sm text-slate-400">未发现逻辑异常：该拆分结构符合全部可评估的共生期望。</p>
      )}
      {report.prompts.map((prompt, index) => (
        <PromptCard key={`${prompt.rule_id}-${prompt.path}-${index}`} prompt={prompt} />
      ))}
      {report.skipped.length > 0 && (
        <details className="text-sm text-slate-400">
          <summary className="cursor-pointer text-slate-300">
            未评估的期望（{report.skipped.length} 条，均已记录原因）
          </summary>
          <ul className="mt-2 space-y-1">
            {report.skipped.map((skip, index) => (
              <li key={`${skip.rule_id}-${index}`} className="font-mono text-xs">
                {skip.rule_id} · {skip.path || '结构级'} · {skip.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

/** 共生期望目录的中文显示映射（按后端 EXPECTATION_CATALOG 的 entry id）。
 * 规则编号（R1–R13、X1–X5、AVM1、BUNDLE1、SCREEN1、EMBED1）与技术标识
 * （P01–P05、DC、AVM、GB 47955-2026、Ho Q 编号）保留原样，只翻描述文字。
 * 后端新增规则时这里没有对应条目，表格回退显示后端原文。 */
const EXPECTATION_ZH: Record<string, { title: string; normal_logic: string; strength: string; scope: string }> = {
  R1: {
    title: '行车域控制器意味着配备摄像头',
    normal_logic: '带行车域控制器（P02 DC）的配置，必有摄像头行（P05）。',
    strength: '63/64 个域控块（唯一例外是华为套餐，Ho Q11）',
    scope: '全部整车厂；套餐配置除外（摄像头已含在套餐价内）',
  },
  R2: {
    title: '摄像头数量随行车计算平台分级',
    normal_logic: '摄像头总数随平台分级：IFC/前视模块 5 个，8620 平台 7 个，8650 平台 10 个（2026 年）/ 11 个（2027 年起），RHP/NGX 平台 11 个（含模块内置的 1 个前视摄像头）。',
    strength: '35/35 组前缀配对（红旗）；5/7/11 摄像头档位与公开证据一致',
    scope: '红旗已验证；凡有平台与可计数 P05 标签的配置均适用；±1 容差（Ho Q2）',
  },
  R3: {
    title: '一体形态意味着没有独立中控屏',
    normal_logic: 'IVI 一体机 / 融合形态的配置没有独立的 P03 中控行（屏幕在 P01 里）。',
    strength: '丰田一体机 11/11 个块；大众融合块按 Ho Q5',
    scope: '形态为 ivi_one_box / fused 的配置',
  },
  R4: {
    title: '分体主机意味着有中控屏',
    normal_logic: '带座舱主机的分体主机配置，必有 P03 中控屏行。',
    strength: '总体 115/140 个主机块；排除丰田一体机后 109/123；红旗 98%，本田 93%',
    scope: '形态为 discrete_host 的配置',
  },
  R5: {
    title: '形态与已核实登记事实一致',
    normal_logic: '配置的形态与已逐项核实的（整车厂、车型、年份）登记事实一致（如有）。',
    strength: '仅限登记事实；不跨车型推广（Ho Q9）',
    scope: '（整车厂、车型、年份）有登记事实的配置',
  },
  R6: {
    title: '同类 P02 替代（重叠只是提示）',
    normal_logic: '同一功能类（域控 / 前视模块）内，不同方案互相替代：其搭载率通常每配置合计不超过 1。',
    strength: '类级规律；大众 2027 年四方案合计 1.2 的块属于合理的独立渗透（Ho Q7）——重叠只提示说明，永不拒绝',
    scope: '带已分类 P02 行且含方案码的配置',
  },
  R7: {
    title: '中控位替代（副驾屏除外）',
    normal_logic: 'ABT 中控屏各变体在中控位内互相替代：其搭载率通常合计不超过 1。CDD/CDI 副驾屏可共存，不计入（Ho Q3）。',
    strength: '大众 2027 年 ABT+CDD 合计 1.1–1.2 属于合理共存',
    scope: '带已分类 P03 中控行的配置',
  },
  R8: {
    title: '仪表行归属 P03',
    normal_logic: '仪表行记在 P03（屏幕）下，永不记在 P01 下（Ho Q3 2026-11-16：仪表计入 P03）。',
    strength: '已确认的分类裁决',
    scope: '所有归类为仪表的 P01 行',
  },
  R9: {
    title: '4G/5G 变体替代',
    normal_logic: '4G 与 5G 通信终端变体互相替代：其搭载率通常每配置合计不超过 1（一车一终端）。',
    strength: 'P04 槽位：一车一终端；变体最大值按不同变体的装配读取',
    scope: '同时带 4G 与 5G 变体标签的配置',
  },
  R10: {
    title: '摄像头多意味着有行车计算',
    normal_logic: '摄像头不少于 7 个的配置，通常在 P02 带行车计算（域控或模块）。',
    strength: '块级共现率 0.94；仅泊车环视组属于合理例外',
    scope: '可计数 P05 总数不少于 7 的配置',
  },
  R11: {
    title: '插混能量细节意味着有电池包域',
    normal_logic: '插混车型带电池包域行（仅目录：能量细节不由结构承载）。',
    strength: '无法评估',
    scope: '无（结构能量只有新能源/燃油两类）',
  },
  R12: {
    title: 'DMS 法规增加一个座舱摄像头',
    normal_logic: 'DMS 法规生效时（GB 47955-2026，自 2027-01-01 起），摄像头总数含 +1 个座舱（DMS/OMS）摄像头。',
    strength: '法规（强制标准）',
    scope: '带 dms_mandate_on 上下文的推演',
  },
  R13: {
    title: 'P.O 要拆解，永不是篮子行',
    normal_logic: 'P.O 子产品（HUD/雷达/网关/车身域/APA/AVM/UWB/……）各自成行；裸 P.O 篮子行会被标记要求拆解。',
    strength: '结构性裁决（Ho Q8）',
    scope: '全部配置',
  },
  X1: {
    title: 'IVI 一体机排除独立座舱域控',
    normal_logic: '一车一种形态：一机形态的配置没有独立的 SCDC 行（结构强制——形态是单一字段）。',
    strength: '仅目录',
    scope: '无（结构性）',
  },
  X2: {
    title: '一体机与分体主机互斥',
    normal_logic: '一个配置恰有一种形态（结构强制——形态是单一字段）。',
    strength: '仅目录',
    scope: '无（结构性）',
  },
  X3: {
    title: '域控 + 前视模块重叠',
    normal_logic: '域控与前视模块是不同计算层级；同一配置两者都有，提示可能是合并的子人群（与 R6 联合评估）。',
    strength: '仅提示',
    scope: '同时带域控与模块行的配置',
  },
  X4: {
    title: '一个配置里有两个域控',
    normal_logic: '一个配置一个行车域控；两个不同域控方案提示可能是合并的子人群（与 R6 联合评估）。',
    strength: '仅提示',
    scope: '带不少于 2 个不同域控方案的配置',
  },
  X5: {
    title: 'ABT 变体只在中控位内替代',
    normal_logic: 'ABT 变体之间互相替代，永不与副驾屏替代（与 R7 联合评估）。',
    strength: '仅提示',
    scope: '带不少于 2 个不同 ABT 变体的配置',
  },
  AVM1: {
    title: 'AVM 意味着有环视摄像头组',
    normal_logic: '带 AVM 的配置在 P05 有环视摄像头组。反过来不成立：有环视组不意味着有 AVM。',
    strength: '结构性配对（Ho Q8）',
    scope: '带 AVM 行的配置',
  },
  BUNDLE1: {
    title: '华为行按套餐计价，永不与单件均价比较',
    normal_logic: "华为全套方案行按 price_basis 'bundle' 计价（屏幕 + 摄像头已含），套餐配置不带独立的 P03/P05 行。",
    strength: '已确认的分类裁决',
    scope: '所有带华为行 / 套餐计价行的配置',
  },
  SCREEN1: {
    title: '一体机 / 融合形态的 P01 均价含屏幕',
    normal_logic: "一体形态配置的 P01 均价按 price_basis 'includes_screen' 标注；永不与分体主机均价比较。",
    strength: '已确认的分类裁决',
    scope: '形态为 ivi_one_box / fused 的配置',
  },
  EMBED1: {
    title: '前视模块内置一个摄像头（记账说明）',
    normal_logic: 'MFK/IFC 前视模块内置 1 个摄像头：总数按含/不含内置单元标注；1 个摄像头的差异属于正常容差（Ho Q2），永不是异常。',
    strength: '记账约定',
    scope: '带前视模块行的配置',
  },
}

export function ExpectationCatalogTable({ entries }: { entries: ExpectationCatalogEntry[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-700/50 text-xs text-slate-400">
            <th className="py-2 pr-4 font-medium">规则</th>
            <th className="py-2 pr-4 font-medium">正常逻辑</th>
            <th className="py-2 pr-4 font-medium">强度 / 依据</th>
            <th className="py-2 pr-4 font-medium">适用范围</th>
            <th className="py-2 font-medium">评估</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => {
            const zh = EXPECTATION_ZH[entry.id]
            return (
              <tr key={entry.id} className="border-b border-slate-800/50 align-top text-slate-200">
                <td className="py-2 pr-4">
                  <span className="font-mono text-xs text-slate-400">{entry.id}</span>
                  <div className="font-medium">{zh?.title ?? entry.title}</div>
                </td>
                <td className="py-2 pr-4">{zh?.normal_logic ?? entry.normal_logic}</td>
                <td className="py-2 pr-4 text-slate-400">{zh?.strength ?? entry.strength}</td>
                <td className="py-2 pr-4 text-slate-400">{zh?.scope ?? entry.scope}</td>
                <td className="py-2 text-slate-400">{entry.evaluated ? '评估' : '仅目录'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
