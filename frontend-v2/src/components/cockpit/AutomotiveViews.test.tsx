import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type {
  AutomotiveTrajectoryRead,
  ExpectationCatalogEntry,
  PromptReportRead,
  SalesLayerRead,
} from '../../api/engineTypes'
import {
  ExpectationCatalogTable,
  PromptList,
  SalesLayerDetailChart,
  SalesLayerPerTickChart,
  SalesLayerView,
  TrajectoryChart,
} from './AutomotiveViews'
import { detailSegments, detailSeriesByTick, oemSummaries } from './automotiveUtils'

const TRAJECTORY: AutomotiveTrajectoryRead = {
  run_id: 'run-1',
  domain_id: 'automotive',
  run_status: 'COMPLETED',
  tick_count: 2,
  multiple_actors: false,
  actor_ids: ['tier1_supplier'],
  points: [
    {
      tick: 0,
      actor_id: 'tier1_supplier',
      state: {
        production_volume: 287.8,
        sales_volume_retail: 197.9,
        nev_production_volume: 137.86,
        ice_production_volume: 149.94,
        nev_retail_volume: 94.79,
        ice_retail_volume: 103.11,
        nev_penetration: 0.479,
        dealer_inventory_coef: 1.35,
      },
    },
    {
      tick: 1,
      actor_id: 'tier1_supplier',
      state: {
        production_volume: 280.1,
        sales_volume_retail: 195.2,
        nev_production_volume: 134.8,
        ice_production_volume: 145.3,
        nev_retail_volume: 93.9,
        ice_retail_volume: 101.3,
        nev_penetration: 0.481,
        dealer_inventory_coef: 1.4,
      },
    },
    {
      tick: 2,
      actor_id: 'tier1_supplier',
      state: {
        production_volume: 272.5,
        sales_volume_retail: 192.6,
        nev_production_volume: 131.7,
        ice_production_volume: 140.8,
        nev_retail_volume: 93.1,
        ice_retail_volume: 99.5,
        nev_penetration: 0.483,
        dealer_inventory_coef: 1.45,
      },
    },
  ],
}

const LAYER: SalesLayerRead = {
  run_id: 'run-1',
  domain_id: 'automotive',
  snapshot_tick_count: 2,
  rows: [
    { tick: 1, oem_id: 'faw-vw', product_id: 'P01', units: 100, capacity_value: 120000, own_sales: 60000 },
    { tick: 1, oem_id: 'faw-vw', product_id: 'P02', units: 40, capacity_value: 100000, own_sales: 100000 },
    { tick: 2, oem_id: 'faw-vw', product_id: 'P01', units: 98, capacity_value: 117600, own_sales: 58800 },
  ],
  per_tick: [
    { tick: 1, production_volume: 280.1, units: 140, capacity_value: 220000, own_sales: 160000 },
    { tick: 2, production_volume: 272.5, units: 98, capacity_value: 117600, own_sales: 58800 },
  ],
  summary: {
    total_units: 238,
    total_capacity_value: 337600,
    total_own_sales: 218800,
    tick_count: 2,
    oem_count: 1,
    product_count: 2,
  },
  production_trajectory: [
    { tick: 1, production_volume: 280.1 },
    { tick: 2, production_volume: 272.5 },
  ],
  assumptions: ['Volume spine: OEM PRODUCTION volume including Audi.'],
  skipped_unpriced_slots: [],
  own_sales_basis: 'supplier_rows',
  own_sales_unavailable_reason: null,
}

const REPORT: PromptReportRead = {
  prompts: [
    {
      rule_id: 'R1',
      severity: 'anomaly',
      path: 'oem[0]/nameplates[0]/generations[0]/trims[0]',
      title: 'Driving domain controller without cameras',
      observed: 'P02 domain-controller rows present (1), no P05 camera rows.',
      expected_logic: 'A trim with a driving domain controller normally carries camera rows.',
      likely_explanations: ['Data gap: P05 rows missing for this trim.'],
      evidence_ref: 'verification report §1.1 (H1 VERIFIED)',
      scope: 'all OEMs',
    },
    {
      rule_id: 'EMBED1',
      severity: 'info',
      path: 'oem[0]/nameplates[0]/generations[0]/trims[0]',
      title: 'Front-view module embeds one camera',
      observed: '1 front-view module row(s) present.',
      expected_logic: 'MFK/IFC modules embed 1 camera; a 1-camera difference is normal tolerance.',
      likely_explanations: ['Accounting convention (Ho Q2); no action needed.'],
      evidence_ref: 'verification report §5 + Ho Q2',
      scope: 'per trim',
    },
  ],
  skipped: [{ rule_id: 'R11', path: '', reason: 'PHEV energy detail is not carried by the structure.' }],
  anomaly_count: 1,
  info_count: 1,
  rules_evaluated: ['EMBED1', 'R1'],
  rules_skipped: ['R11'],
}

const CATALOG: ExpectationCatalogEntry[] = [
  {
    id: 'R1',
    title: 'Driving domain controller implies cameras',
    normal_logic: 'A trim with a driving domain controller (P02 DC) carries camera rows (P05).',
    strength: '63/64 DC blocks',
    scope: 'All OEMs',
    evidence_ref: 'verification report §1.1',
    evaluated: true,
  },
  {
    id: 'R11',
    title: 'PHEV energy detail implies a battery-pack domain',
    normal_logic: 'PHEV nameplates carry a battery-pack domain row.',
    strength: 'Not evaluable',
    scope: 'None',
    evidence_ref: 'verification report §3 (R11)',
    evaluated: false,
  },
]

describe('TrajectoryChart', () => {
  it('renders the volume series legend and the per-tick table', () => {
    render(<TrajectoryChart trajectory={TRAJECTORY} />)
    expect(screen.getByText('产量（主轴）')).toBeTruthy()
    expect(screen.getAllByText('零售').length).toBeGreaterThan(0)
    expect(screen.getAllByText('NEV 产量').length).toBeGreaterThan(0)
    expect(screen.getAllByText('ICE 产量').length).toBeGreaterThan(0)
    expect(screen.getByText('287.8')).toBeTruthy()
    expect(screen.getByText('137.86')).toBeTruthy()
    expect(screen.getByText('47.9%')).toBeTruthy()
    expect(screen.getAllByText(/NEV 渗透率/).length).toBeGreaterThan(0)
  })
})

describe('SalesLayerView', () => {
  it('renders totals, per-tick rows, and product rows from the backend summary', () => {
    render(<SalesLayerView layer={LAYER} />)
    expect(screen.getByText('337600')).toBeTruthy()
    expect(screen.getByText('218800')).toBeTruthy()
    expect(screen.getByText('280.1')).toBeTruthy()
    expect(screen.getAllByText('P01').length).toBeGreaterThan(0)
    expect(screen.getAllByText('P02').length).toBeGreaterThan(0)
    expect(screen.getByText(/Volume spine/)).toBeTruthy()
  })

  it('charts the per-tick totals with all four series and a dual-axis note', () => {
    render(<SalesLayerPerTickChart layer={LAYER} />)
    expect(screen.getByRole('img', { name: 'S 层逐 tick 总量图' })).toBeTruthy()
    expect(screen.getByText('产量（主轴）')).toBeTruthy()
    expect(screen.getAllByText('件数').length).toBeGreaterThan(0)
    expect(screen.getAllByText('容量').length).toBeGreaterThan(0)
    expect(screen.getAllByText('自有销售').length).toBeGreaterThan(0)
    expect(screen.getByText(/左轴：产量/)).toBeTruthy()
  })

  it('omits the own-sales line and says so when own sales are un-attributed', () => {
    render(
      <SalesLayerPerTickChart
        layer={{
          ...LAYER,
          summary: { ...LAYER.summary, total_own_sales: null },
          rows: LAYER.rows.map((row) => ({ ...row, own_sales: null })),
          per_tick: LAYER.per_tick.map((tick) => ({ ...tick, own_sales: null })),
        }}
      />,
    )
    expect(screen.getByText(/自有销售未归属，图中不含自有销售线/)).toBeTruthy()
  })

  it('charts the detail rows as OEM × product stacks with a measure toggle', () => {
    render(<SalesLayerDetailChart layer={LAYER} />)
    expect(screen.getByRole('img', { name: 'S 层明细堆叠图（容量）' })).toBeTruthy()
    expect(screen.getByText('faw-vw · P01')).toBeTruthy()
    expect(screen.getByText('faw-vw · P02')).toBeTruthy()
    const unitsButton = screen.getByRole('button', { name: '件数' })
    expect(unitsButton.getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(unitsButton)
    expect(unitsButton.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('img', { name: 'S 层明细堆叠图（件数）' })).toBeTruthy()
    const ownSalesButton = screen.getByRole('button', { name: '自有销售' })
    fireEvent.click(ownSalesButton)
    expect(screen.getByRole('img', { name: 'S 层明细堆叠图（自有销售）' })).toBeTruthy()
  })

  it('explains the own-sales stack is unavailable when every row is null', () => {
    render(
      <SalesLayerDetailChart
        layer={{
          ...LAYER,
          rows: LAYER.rows.map((row) => ({ ...row, own_sales: null })),
        }}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: '自有销售' }))
    expect(screen.getByText(/无法绘出自有销售堆叠/)).toBeTruthy()
  })

  it('keeps the exact-value tables with the charts', () => {
    render(<SalesLayerView layer={LAYER} />)
    expect(screen.getByText(/精确数值（与图表同源/)).toBeTruthy()
    // 117600 / 58800 each appear in BOTH exact-value tables (per-tick
    // totals and the detail rows): the fold-out keeps every number.
    expect(screen.getAllByText('117600').length).toBe(2)
    expect(screen.getAllByText('58800').length).toBe(2)
  })

  it('explains unavailable own-sales attribution instead of showing zero', () => {
    render(
      <SalesLayerView
        layer={{
          ...LAYER,
          own_sales_basis: 'unavailable',
          own_sales_unavailable_reason: 'No supplier attribution supplied.',
          summary: { ...LAYER.summary, total_own_sales: null },
          rows: LAYER.rows.map((row) => ({ ...row, own_sales: null })),
          per_tick: LAYER.per_tick.map((tick) => ({ ...tick, own_sales: null })),
        }}
      />,
    )
    expect(screen.getByText('未归属（见下）')).toBeTruthy()
    expect(screen.getByText(/No supplier attribution supplied/)).toBeTruthy()
  })

  it('discloses skipped unpriced slots', () => {
    render(<SalesLayerView layer={{ ...LAYER, skipped_unpriced_slots: ['tick 1: faw-vw.sagitar.P01@ho'] }} />)
    expect(screen.getByText(/跳过了 1 个无价槽位/)).toBeTruthy()
  })
})

describe('detailSegments / detailSeriesByTick', () => {
  it('lists segments in first-appearance order', () => {
    expect(detailSegments(LAYER.rows)).toEqual(['faw-vw · P01', 'faw-vw · P02'])
    expect(detailSegments([])).toEqual([])
  })

  it('pivots rows per tick and sums duplicate tick × OEM × product rows', () => {
    const series = detailSeriesByTick(
      [
        { tick: 1, oem_id: 'faw-vw', product_id: 'P01', units: 100, capacity_value: 120000, own_sales: 60000 },
        { tick: 1, oem_id: 'faw-vw', product_id: 'P01', units: 5, capacity_value: 6000, own_sales: null },
        { tick: 2, oem_id: 'faw-vw', product_id: 'P01', units: 98, capacity_value: 117600, own_sales: 58800 },
      ],
      'capacity_value',
    )
    expect(series).toEqual([
      { tick: 1, 'faw-vw · P01': 126000 },
      { tick: 2, 'faw-vw · P01': 117600 },
    ])
    expect(
      detailSeriesByTick(
        [
          { tick: 1, oem_id: 'faw-vw', product_id: 'P01', units: 100, capacity_value: 120000, own_sales: 60000 },
          { tick: 1, oem_id: 'faw-vw', product_id: 'P01', units: 5, capacity_value: 6000, own_sales: null },
        ],
        'own_sales',
      ),
    ).toEqual([{ tick: 1, 'faw-vw · P01': 60000 }])
    expect(detailSeriesByTick([], 'units')).toEqual([])
  })
})

describe('PromptList', () => {
  it('flags anomalies prominently with the expected logic and explanations', () => {
    render(<PromptList report={REPORT} />)
    expect(screen.getByText('逻辑异常')).toBeTruthy()
    expect(screen.getByText('Driving domain controller without cameras')).toBeTruthy()
    expect(screen.getByText(/normally carries camera rows/)).toBeTruthy()
    expect(screen.getByText(/Data gap: P05 rows missing/)).toBeTruthy()
    expect(screen.getByText('提示')).toBeTruthy()
    expect(screen.getByText(/1 条逻辑异常 · 1 条提示/)).toBeTruthy()
  })

  it('shows skipped expectations with their reasons', () => {
    render(<PromptList report={REPORT} />)
    expect(screen.getByText(/未评估的期望/)).toBeTruthy()
    expect(screen.getByText(/PHEV energy detail/)).toBeTruthy()
  })

  it('states the prompt-system rule when nothing fires', () => {
    render(<PromptList report={{ ...REPORT, prompts: [], anomaly_count: 0, info_count: 0 }} />)
    expect(screen.getByText(/符合全部可评估的共生期望/)).toBeTruthy()
    expect(screen.getByText(/只标注、不拒绝、不修正/)).toBeTruthy()
  })
})

describe('ExpectationCatalogTable', () => {
  it('renders evaluated and catalog-only entries distinctly', () => {
    render(<ExpectationCatalogTable entries={CATALOG} />)
    expect(screen.getByText('行车域控制器意味着配备摄像头')).toBeTruthy()
    expect(screen.getAllByText('评估').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('仅目录')).toBeTruthy()
  })
})

describe('oemSummaries', () => {
  it('extracts OEM ids, statuses, and nameplate counts', () => {
    const summaries = oemSummaries({
      oems: [
        { oem_id: 'faw-vw', customer_status: 'existing', nameplates: [{}, {}] },
        { oem_id: 'dongfeng-honda', customer_status: 'prospect', nameplates: [{}] },
      ],
    })
    expect(summaries).toEqual([
      { oem_id: 'faw-vw', customer_status: 'existing', nameplate_count: 2 },
      { oem_id: 'dongfeng-honda', customer_status: 'prospect', nameplate_count: 1 },
    ])
  })

  it('returns empty for malformed structures', () => {
    expect(oemSummaries({})).toEqual([])
    expect(oemSummaries({ oems: 'nope' })).toEqual([])
    expect(oemSummaries({ oems: [{ customer_status: 'existing' }] })).toEqual([])
  })
})
