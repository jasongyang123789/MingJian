import { render, screen } from '@testing-library/react'
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
  SalesLayerTable,
  TrajectoryChart,
} from './AutomotiveViews'
import { oemSummaries } from './automotiveUtils'

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

describe('SalesLayerTable', () => {
  it('renders totals, per-tick rows, and product rows from the backend summary', () => {
    render(<SalesLayerTable layer={LAYER} />)
    expect(screen.getByText('337600')).toBeTruthy()
    expect(screen.getByText('218800')).toBeTruthy()
    expect(screen.getByText('280.1')).toBeTruthy()
    expect(screen.getAllByText('P01').length).toBeGreaterThan(0)
    expect(screen.getAllByText('P02').length).toBeGreaterThan(0)
    expect(screen.getByText(/Volume spine/)).toBeTruthy()
  })

  it('explains unavailable own-sales attribution instead of showing zero', () => {
    render(
      <SalesLayerTable
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
    render(<SalesLayerTable layer={{ ...LAYER, skipped_unpriced_slots: ['tick 1: faw-vw.sagitar.P01@ho'] }} />)
    expect(screen.getByText(/跳过了 1 个无价槽位/)).toBeTruthy()
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
    expect(screen.getByText('Driving domain controller implies cameras')).toBeTruthy()
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
