import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import Automotive from './Automotive'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const RUNS = [
  {
    id: 'run-1',
    status: 'COMPLETED',
    domain_id: 'automotive',
    company_id: 'auto-oem',
    created_at: '2026-11-16T00:00:00Z',
    tick_count: 6,
  },
]

const STRUCTURE = {
  oems: [
    {
      oem_id: 'faw-vw',
      customer_status: 'existing',
      nameplates: [
        {
          nameplate_id: 'sagitar',
          energy: 'ICE',
          price_band: '10-15',
          share: 1.0,
          generations: [],
        },
      ],
    },
  ],
}

const TRAJECTORY = {
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
        nev_penetration: 0.481,
        dealer_inventory_coef: 1.4,
      },
    },
  ],
}

const LAYER = {
  run_id: 'run-1',
  domain_id: 'automotive',
  snapshot_tick_count: 1,
  rows: [
    { tick: 1, oem_id: 'faw-vw', product_id: 'P01', units: 100, capacity_value: 120000, own_sales: 60000 },
  ],
  per_tick: [{ tick: 1, production_volume: 280.1, units: 100, capacity_value: 120000, own_sales: 60000 }],
  summary: {
    total_units: 100,
    total_capacity_value: 120000,
    total_own_sales: 60000,
    tick_count: 1,
    oem_count: 1,
    product_count: 1,
  },
  production_trajectory: [{ tick: 1, production_volume: 280.1 }],
  assumptions: ['Volume spine: OEM PRODUCTION volume including Audi.'],
  skipped_unpriced_slots: [],
  own_sales_basis: 'supplier_rows',
  own_sales_unavailable_reason: null,
}

const REPORT = {
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
  ],
  skipped: [],
  anomaly_count: 1,
  info_count: 0,
  rules_evaluated: ['R1'],
  rules_skipped: [],
}

const CATALOG = [
  {
    id: 'R1',
    title: 'Driving domain controller implies cameras',
    normal_logic: 'A trim with a driving domain controller (P02 DC) carries camera rows (P05).',
    strength: '63/64 DC blocks',
    scope: 'All OEMs',
    evidence_ref: 'verification report §1.1',
    evaluated: true,
  },
]

interface CapturedRequest {
  url: string
  method: string
  body: unknown
}

describe('Automotive', () => {
  let requests: CapturedRequest[]
  let splitStructureStatus: number

  function installFetch() {
    requests = []
    splitStructureStatus = 200
    vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      let body: unknown = null
      if (typeof init?.body === 'string') {
        try {
          body = JSON.parse(init.body) as unknown
        } catch {
          body = init.body
        }
      }
      requests.push({ url, method, body })
      if (url === '/api/simulation/runs' && method === 'GET') return jsonResponse(RUNS)
      if (url === '/api/simulation/runs' && method === 'POST') {
        return jsonResponse({ id: 'run-2', status: 'COMPLETED' }, 201)
      }
      if (url.endsWith('/automotive/trajectory')) return jsonResponse(TRAJECTORY)
      if (url.endsWith('/automotive/split-structure')) {
        if (splitStructureStatus !== 200) {
          return jsonResponse(
            { detail: { code: 'automotive_no_split_structure', message: 'no split structure' } },
            splitStructureStatus,
          )
        }
        return jsonResponse({ run_id: 'run-1', structure: STRUCTURE, validation: { is_valid: true } })
      }
      if (url.endsWith('/automotive/sales-layer')) return jsonResponse(LAYER)
      if (url === '/api/automotive/prompts/evaluate') return jsonResponse(REPORT)
      if (url === '/api/automotive/expectations') return jsonResponse(CATALOG)
      return jsonResponse({ detail: 'not found' }, 404)
    })
  }

  beforeEach(() => {
    vi.restoreAllMocks()
    installFetch()
  })

  function renderPage(initialEntry = '/cockpit/automotive?run=run-1') {
    return render(
      <MemoryRouter initialEntries={[initialEntry]}>
        <Automotive />
      </MemoryRouter>,
    )
  }

  it('shows the trajectory, structure, and catalog for the selected run', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('287.8')).toBeTruthy())
    expect(screen.getAllByText(/faw-vw/).length).toBeGreaterThan(0)
    expect(screen.getByText(/现有客户/)).toBeTruthy()
    expect(screen.getByText('行车域控制器意味着配备摄像头')).toBeTruthy()
    expect(screen.getAllByText('运行汽车模板').length).toBeGreaterThan(0)
  })

  it('computes the S-layer with equal OEM shares by default', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('计算 S 层')).toBeTruthy())
    fireEvent.click(screen.getByText('计算 S 层'))
    await waitFor(() => expect(screen.getAllByText('120000').length).toBeGreaterThan(0))
    const posted = requests.find((request) => request.url.endsWith('/automotive/sales-layer'))
    expect(posted).toBeTruthy()
    expect(posted?.body).toMatchObject({ oem_production_shares: { 'faw-vw': 1 } })
  })

  it('evaluates prompts over the run structure and flags anomalies', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('评估共生提示')).toBeTruthy())
    fireEvent.click(screen.getByText('评估共生提示'))
    await waitFor(() => expect(screen.getByText('逻辑异常')).toBeTruthy())
    expect(screen.getByText('Driving domain controller without cameras')).toBeTruthy()
    const posted = requests.find((request) => request.url === '/api/automotive/prompts/evaluate')
    expect(posted?.body).toMatchObject({ split_structure: STRUCTURE })
  })

  it('launches an automotive run with the builtin template', async () => {
    renderPage('/cockpit/automotive')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '运行汽车模板' })).toBeTruthy(),
    )
    fireEvent.click(screen.getByRole('button', { name: '运行汽车模板' }))
    await waitFor(() =>
      expect(
        requests.some((request) => request.url === '/api/simulation/runs' && request.method === 'POST'),
      ).toBe(true),
    )
    const posted = requests.find(
      (request) => request.url === '/api/simulation/runs' && request.method === 'POST',
    )
    expect(posted?.body).toMatchObject({
      domain_id: 'automotive',
      variable_template_id: 'builtin:automotive',
      tick_count: 6,
      seed: 7,
    })
  })

  it('rejects malformed split JSON in the launcher without posting', async () => {
    renderPage('/cockpit/automotive')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '运行汽车模板' })).toBeTruthy(),
    )
    fireEvent.change(screen.getByLabelText(/拆分结构 JSON/), { target: { value: '{not json' } })
    fireEvent.click(screen.getByRole('button', { name: '运行汽车模板' }))
    await waitFor(() => expect(screen.getByText(/JSON 解析失败/)).toBeTruthy())
    expect(
      requests.some((request) => request.url === '/api/simulation/runs' && request.method === 'POST'),
    ).toBe(false)
  })

  it('shows an empty state when the run carries no split structure', async () => {
    splitStructureStatus = 400
    // Reinstall with the failing status honored: the mock reads the
    // mutable variable, so flipping it before render is enough.
    renderPage()
    await waitFor(() => expect(screen.getByText('该推演未带拆分结构')).toBeTruthy())
  })
})
