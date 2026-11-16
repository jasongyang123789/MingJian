// Automotive cockpit page (Phase 2): run the automotive template,
// view the production/retail trajectory (NEV/ICE dual track), compute
// the snapshot-wired S-layer capacity/sales, and evaluate
// co-occurrence prompts over the run's own split structure. Every
// section degrades honestly: a non-automotive run, a run without a
// split structure, or a missing trajectory each renders an empty
// state or the backend's own error, and nothing is synthesized.

import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { simulationApi } from '../api/endpoints'
import { automotiveApi } from '../api/engine'
import type { PromptReportRead, SalesLayerRead } from '../api/engineTypes'
import {
  ExpectationCatalogTable,
  PromptList,
  SalesLayerTable,
  TrajectoryChart,
} from '../components/cockpit/AutomotiveViews'
import { oemSummaries } from '../components/cockpit/automotiveUtils'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import { RunPicker } from '../components/cockpit/RunPicker'
import type { CockpitRun } from '../components/cockpit/RunPicker'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { useApi } from '../hooks/useApi'

const INPUT_CLASS =
  'rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 focus:border-blue-500/50 focus:outline-none'
const BUTTON_CLASS =
  'rounded-full border border-blue-500/30 bg-blue-500/10 px-4 py-2 text-sm font-medium text-blue-300 transition hover:bg-blue-500/20 disabled:opacity-50'

function RunLauncher({ onCreated }: { onCreated: (runId: string) => void }) {
  const [tickCount, setTickCount] = useState('6')
  const [seed, setSeed] = useState('7')
  const [companyName, setCompanyName] = useState('Auto Test OEM')
  const [splitJson, setSplitJson] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    setError(null)
    let splitStructure: unknown
    if (splitJson.trim() !== '') {
      try {
        splitStructure = JSON.parse(splitJson) as unknown
      } catch {
        setError('拆分结构 JSON 解析失败：请粘贴合法的 JSON 对象。')
        return
      }
    }
    setCreating(true)
    try {
      const payload: Record<string, unknown> = {
        company_id: 'auto-cockpit-oem',
        company_name: companyName || 'Auto Test OEM',
        market: 'china-auto',
        domain_id: 'automotive',
        actor_template: 'tier1_supplier',
        tick_count: Number(tickCount) || 6,
        seed: Number(seed) || 7,
        variable_template_id: 'builtin:automotive',
      }
      if (splitStructure !== undefined) payload.split_structure = splitStructure
      const created = (await simulationApi.createRun(payload)) as { id?: unknown }
      if (typeof created.id !== 'string') {
        setError('创建 Run 未返回 id。')
        return
      }
      onCreated(created.id)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Tick 数（月）
          <input
            aria-label="Tick 数"
            className={INPUT_CLASS}
            value={tickCount}
            onChange={(event) => setTickCount(event.target.value)}
            inputMode="numeric"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          种子
          <input
            aria-label="种子"
            className={INPUT_CLASS}
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
            inputMode="numeric"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          公司名
          <input
            aria-label="公司名"
            className={INPUT_CLASS}
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
          />
        </label>
        <button type="button" className={BUTTON_CLASS} onClick={() => void handleCreate()} disabled={creating}>
          {creating ? '运行中…' : '运行汽车模板'}
        </button>
      </div>
      <label className="flex flex-col gap-1 text-xs text-slate-400">
        拆分结构 JSON（可选：OEM → 牌名 → 代际 → 配置 → 产品 → 供应商份额；留空则不带拆分结构）
        <textarea
          aria-label="拆分结构 JSON"
          className={`${INPUT_CLASS} min-h-24 font-mono text-xs`}
          value={splitJson}
          onChange={(event) => setSplitJson(event.target.value)}
          placeholder='{"oems": [...]}'
        />
      </label>
      {error && <ErrorBanner message={error} />}
    </div>
  )
}

function TrajectorySection({ runId }: { runId: string }) {
  const { data, loading, error, reload } = useApi(() => automotiveApi.getTrajectory(runId), runId)
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  if (data === null) {
    return (
      <EmptyState
        title="暂无轨迹"
        description="该 Run 尚未存储任何快照。先运行一次汽车模板推演，轨迹会在此出现。"
      />
    )
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-400">
        Run 状态：{data.run_status} · {data.points.length} 个快照点（含 tick 0 初始状态）
        {data.multiple_actors ? ` · 多 actor（${data.actor_ids.join(', ')}），每 tick 取首个 actor` : ''}
      </p>
      <TrajectoryChart trajectory={data} />
    </div>
  )
}

function StructureBody({
  runId,
  structure,
}: {
  runId: string
  structure: Record<string, unknown>
}) {
  const oems = oemSummaries(structure)
  const [shares, setShares] = useState<Record<string, number>>(() => {
    if (oems.length === 0) return {}
    const equal = 1 / oems.length
    return Object.fromEntries(oems.map((oem) => [oem.oem_id, equal]))
  })
  const [ownSupplierId, setOwnSupplierId] = useState('')
  const [defaultShare, setDefaultShare] = useState('')
  const [strictPrices, setStrictPrices] = useState(true)
  const [dmsOn, setDmsOn] = useState(false)
  const [layer, setLayer] = useState<SalesLayerRead | null>(null)
  const [layerLoading, setLayerLoading] = useState(false)
  const [layerError, setLayerError] = useState<string | null>(null)
  const [report, setReport] = useState<PromptReportRead | null>(null)
  const [promptsLoading, setPromptsLoading] = useState(false)
  const [promptsError, setPromptsError] = useState<string | null>(null)

  async function handleComputeLayer() {
    setLayerLoading(true)
    setLayerError(null)
    try {
      const parsedDefault = defaultShare.trim() === '' ? null : Number(defaultShare)
      const result = await automotiveApi.computeSalesLayer(runId, {
        oem_production_shares: shares,
        own_supplier_id: ownSupplierId.trim() === '' ? null : ownSupplierId.trim(),
        default_supply_share: parsedDefault,
        strict_prices: strictPrices,
      })
      setLayer(result)
    } catch (e: unknown) {
      setLayerError(e instanceof Error ? e.message : String(e))
    } finally {
      setLayerLoading(false)
    }
  }

  async function handleEvaluatePrompts() {
    setPromptsLoading(true)
    setPromptsError(null)
    try {
      const result = await automotiveApi.evaluatePrompts({
        split_structure: structure,
        dms_mandate_on: dmsOn ? true : null,
      })
      setReport(result)
    } catch (e: unknown) {
      setPromptsError(e instanceof Error ? e.message : String(e))
    } finally {
      setPromptsLoading(false)
    }
  }

  const shareTotal = Object.values(shares).reduce((sum, value) => sum + value, 0)

  return (
    <div className="space-y-6">
      <div>
        <h4 className="mb-2 text-sm font-medium text-slate-200">拆分结构</h4>
        <ul className="space-y-1 text-sm text-slate-300">
          {oems.map((oem) => (
            <li key={oem.oem_id}>
              {oem.oem_id} · {oem.customer_status === 'prospect' ? '待开拓客户' : '现有客户'} ·{' '}
              {oem.nameplate_count} 个牌名
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h4 className="mb-2 text-sm font-medium text-slate-200">S 层容量 / 销售（读快照产量轨迹自动计算）</h4>
        <div className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            {oems.map((oem) => (
              <label key={oem.oem_id} className="flex flex-col gap-1 text-xs text-slate-400">
                {oem.oem_id} 产量份额
                <input
                  aria-label={`${oem.oem_id} 产量份额`}
                  className={INPUT_CLASS}
                  value={shares[oem.oem_id] ?? ''}
                  onChange={(event) =>
                    setShares((prev) => ({ ...prev, [oem.oem_id]: Number(event.target.value) }))
                  }
                  inputMode="decimal"
                />
              </label>
            ))}
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              自有供应商 id（留空则不归属）
              <input
                aria-label="自有供应商 id"
                className={INPUT_CLASS}
                value={ownSupplierId}
                onChange={(event) => setOwnSupplierId(event.target.value)}
                placeholder="ho"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              默认供货份额（0–1，留空则不用）
              <input
                aria-label="默认供货份额"
                className={INPUT_CLASS}
                value={defaultShare}
                onChange={(event) => setDefaultShare(event.target.value)}
                inputMode="decimal"
              />
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={strictPrices}
                onChange={(event) => setStrictPrices(event.target.checked)}
              />
              严格价格（无价槽位拒绝计算）
            </label>
            <button
              type="button"
              className={BUTTON_CLASS}
              onClick={() => void handleComputeLayer()}
              disabled={layerLoading}
            >
              {layerLoading ? '计算中…' : '计算 S 层'}
            </button>
          </div>
          <p className="text-xs text-slate-400">
            份额合计：{shareTotal.toFixed(4)}（须为 1；后端强制校验）。
            {oems.some((oem) => oem.customer_status === 'prospect') &&
              ' 待开拓客户的自有销售恒为 0。'}
          </p>
          {layerError && <ErrorBanner message={layerError} />}
          {layer && <SalesLayerTable layer={layer} />}
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-sm font-medium text-slate-200">共生提示 / 逻辑异常标注</h4>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-slate-400">
              <input
                type="checkbox"
                checked={dmsOn}
                onChange={(event) => setDmsOn(event.target.checked)}
              />
              DMS 强制令已开（评估 R12）
            </label>
            <button
              type="button"
              className={BUTTON_CLASS}
              onClick={() => void handleEvaluatePrompts()}
              disabled={promptsLoading}
            >
              {promptsLoading ? '评估中…' : '评估共生提示'}
            </button>
          </div>
          {promptsError && <ErrorBanner message={promptsError} />}
          {report && <PromptList report={report} />}
        </div>
      </div>
    </div>
  )
}

function StructureSection({ runId }: { runId: string }) {
  const { data, loading, error, reload } = useApi(
    () => automotiveApi.getSplitStructure(runId),
    runId,
  )

  if (loading) return <LoadingSpinner />
  if (error) {
    // The backend names the missing-structure case; anything else is a
    // genuine error. The code rides in the ApiError message body.
    if (error.includes('automotive_no_split_structure')) {
      return (
        <EmptyState
          title="该 Run 未带拆分结构"
          description="S 层计算与共生提示都需要 Run 在创建时附带的拆分结构（OEM → 牌名 → 代际 → 配置 → 产品 → 供应商份额）。用上方启动器重新运行一次并粘贴拆分结构 JSON。"
        />
      )
    }
    return <ErrorBanner message={error} onRetry={reload} />
  }
  if (data === null) return <EmptyState title="暂无拆分结构" description="该 Run 未存储拆分结构。" />

  // Keyed by run: switching runs remounts the body, resetting the form
  // and per-run results without any set-state-in-effect.
  return <StructureBody key={runId} runId={runId} structure={data.structure} />
}

function ExpectationsSection() {
  const { data, loading, error, reload } = useApi(() => automotiveApi.getExpectations())
  if (loading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={reload} />
  if (data === null || data.length === 0) {
    return <EmptyState title="暂无期望目录" description="后端未返回共生期望目录。" />
  }
  return <ExpectationCatalogTable entries={data} />
}

export default function Automotive() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: runs, loading, error, reload } = useApi(() => simulationApi.listRuns())
  const [selectedRunId, setSelectedRunId] = useState<string | null>(searchParams.get('run'))

  function selectRun(runId: string) {
    setSelectedRunId(runId)
    setSearchParams({ run: runId })
  }

  function handleCreated(runId: string) {
    reload()
    selectRun(runId)
  }

  return (
    <div className="space-y-6">
      <CockpitNav />
      <div>
        <h2 className="text-2xl font-bold text-slate-100">汽车推演</h2>
        <p className="mt-1 text-sm text-slate-400">
          中国汽车市场推演：运行汽车模板，看产量 / 零售轨迹与 NEV/ICE 双轨；S 层直接读快照产量轨迹算出逐月容量与销售；共生提示只标注逻辑异常、不拒绝、不修正。
        </p>
      </div>

      <Card>
        <CardHeader title="运行汽车模板" />
        <CardBody>
          <RunLauncher onCreated={handleCreated} />
        </CardBody>
      </Card>

      {loading && <LoadingSpinner />}
      {error && <ErrorBanner message={error} onRetry={reload} />}
      {runs && (
        <RunPicker
          runs={runs as CockpitRun[]}
          selectedId={selectedRunId}
          onSelect={selectRun}
          label="选择模拟 Run"
        />
      )}

      {!selectedRunId && (
        <EmptyState title="请选择一个 Run" description="轨迹、S 层与共生提示都展示所选 Run 已存储的数据" />
      )}

      {selectedRunId && (
        <Card>
          <CardHeader title="产量 / 零售轨迹（NEV/ICE 双轨）" />
          <CardBody>
            <TrajectorySection runId={selectedRunId} />
          </CardBody>
        </Card>
      )}

      {selectedRunId && (
        <Card>
          <CardHeader title="拆分结构 · S 层 · 共生提示" />
          <CardBody>
            <StructureSection runId={selectedRunId} />
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="共生期望目录（提示制：概率性期望，不是硬规则）" />
        <CardBody>
          <ExpectationsSection />
        </CardBody>
      </Card>
    </div>
  )
}
