// Directions page driven by the v2 fixtures: proves the page renders the
// REAL e047f50 backtest numbers (derive outcomes + narrative distributions),
// not the v1 mock values. The fetch mock is a lean copy of the harness in
// Directions.test.tsx, pointed at one backtest anchor run at a time.

import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// Resume fix (2026-11-20): the first derive case renders the full Directions
// page cold (~3.2s unloaded) and exceeds vitest's 5s default under any
// parallel CPU load — two consecutive timeout failures, both passing alone.
// The assertions themselves pass; this is a harness timeout, not a data
// failure. 15s leaves headroom without masking a real hang.
vi.setConfig({ testTimeout: 15_000 })

import type { DecisionNarrativeRead, DerivationRead } from '../api/engineTypes'
import {
  backtestScorecardByKey,
  derivationReadV2ByKey,
  narrativeReadV2ByKey,
} from '../test/engineFixturesV2'
import Directions from './Directions'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockFetchFor(anchorId: string, derivation: DerivationRead, narrative: DecisionNarrativeRead) {
  vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url === '/api/simulation/runs') {
      return jsonResponse([
        {
          id: anchorId,
          status: 'COMPLETED',
          domain_id: narrative.body.domain_id,
          company_id: `backtest-${narrative.body.domain_id}`,
          created_at: '2026-11-19T15:00:00Z',
          tick_count: backtestScorecardByKey[narrative.id.replace('narrative-v2-', '')]?.tickCount ?? 5,
        },
      ])
    }
    if (url === `/api/runs/${anchorId}/mece`) {
      return jsonResponse({
        run_id: anchorId,
        decomposition: {
          topic: narrative.topic,
          root: {
            name: narrative.topic,
            scope: ['growth'],
            children: [{ name: '增长', scope: ['growth'], children: [] }],
          },
        },
        validation: { is_mece: true, checks: [], issues: [], scope_tag_count: 2, branch_count: 3 },
      })
    }
    if (url === `/api/runs/${anchorId}/variables` && method === 'GET') {
      return jsonResponse({
        run_id: anchorId,
        template: null,
        bindings: { name: 'anchor-bindings', variables: [], formulas: [], internal: {} },
        validation: { is_valid: true, variable_count: 0, checks: [], issues: [] },
      })
    }
    if (url === `/api/runs/${anchorId}/directions/mappings` && method === 'GET') {
      return jsonResponse({ run_id: anchorId, mappings: derivation.mappings })
    }
    if (method === 'POST' && url === `/api/runs/${anchorId}/directions/derive`) {
      return jsonResponse(derivation)
    }
    if (url === `/api/runs/${anchorId}/narratives` && method === 'GET') {
      return jsonResponse({ run_id: anchorId, narratives: [narrative] })
    }
    return jsonResponse({ detail: `unexpected ${method} ${url}` }, 404)
  })
}

async function pickAnchorRun(anchorId: string) {
  render(
    <MemoryRouter>
      <Directions />
    </MemoryRouter>,
  )
  fireEvent.change(await screen.findByLabelText('锚定 Run'), { target: { value: anchorId } })
  await screen.findByRole('button', { name: '生成简报' })
}

describe('Directions with v2 backtest fixtures', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it.each([
    {
      key: 'huawei2000',
      bShort: 'c55451c1',
      bP50: 'P50 1339.6083',
      bLoss: '亏损概率 0',
      anchorShort: '30e09171',
      anchorP50: 'P50 1137.1442',
    },
    {
      key: 'nokia2007',
      bShort: '1c8d6804',
      bP50: 'P50 39.8909',
      bLoss: '亏损概率 0.6',
      anchorShort: '453f8429',
      anchorP50: 'P50 2.1489',
    },
    {
      key: 'desay2015',
      bShort: 'a798c506',
      bP50: 'P50 8778.0068',
      bLoss: '亏损概率 0',
      anchorShort: 'eb32fb20',
      anchorP50: 'P50 11824.7343',
    },
    {
      key: 'desay2020',
      bShort: '53db6d63',
      bP50: 'P50 38721.6944',
      bLoss: '亏损概率 0',
      anchorShort: 'fc7550f4',
      anchorP50: 'P50 60303.1553',
    },
  ])('$key: derive shows the real v2 rule outcomes', async (c) => {
    const derivation = derivationReadV2ByKey[c.key]
    const narrative = narrativeReadV2ByKey[c.key]
    mockFetchFor(derivation.anchor_run_id, derivation, narrative)
    await pickAnchorRun(derivation.anchor_run_id)
    fireEvent.click(screen.getByRole('button', { name: '推导方向' }))
    expect(await screen.findByText(/规则版本 derivation-rules-v2/)).toBeTruthy()
    expect(screen.getByText(new RegExp(`场景家族 ${derivation.family_size} 个 Run`))).toBeTruthy()
    expect(screen.getByText(new RegExp(`${derivation.candidates_considered} 个候选`))).toBeTruthy()
    expect(screen.getByText(new RegExp(`已选 ${c.bShort}.*${c.bP50}，${c.bLoss}`))).toBeTruthy()
    expect(screen.getByText(/与规则 最高 P50 重复/)).toBeTruthy()
    expect(screen.getByText(new RegExp(`已选 ${c.anchorShort}.*${c.anchorP50}`))).toBeTruthy()
    expect(await screen.findByText('Highest P50')).toBeTruthy()
    expect(screen.getByText('Baseline')).toBeTruthy()
  })

  it('desay2020: reading view shows the real B and anchor revenue distributions', async () => {
    const derivation = derivationReadV2ByKey.desay2020
    const narrative = narrativeReadV2ByKey.desay2020
    mockFetchFor(derivation.anchor_run_id, derivation, narrative)
    await pickAnchorRun(derivation.anchor_run_id)
    expect(await screen.findByText('方向 1：B aggressive intelligent driving push')).toBeTruthy()
    expect(screen.getByText(/P10 36137.8763 \/ P50 38721.6944 \/ P90 43693.5005/)).toBeTruthy()
    expect(screen.getByText(/均值 39472.6814；亏损概率 0.0%；n=20/)).toBeTruthy()
    expect(screen.getByText(/ensemble 9d5263f2-0eee-4e0a-8155-7c9f53aa4110 · 20 trials · seed 42/)).toBeTruthy()
    expect(screen.getByText(/期望损失（ES）：35802.3209/)).toBeTruthy()
    expect(screen.getByText('方向 2：Baseline')).toBeTruthy()
    expect(screen.getByText(/P10 50560.3128 \/ P50 60303.1553 \/ P90 72479.4756/)).toBeTruthy()
    // Honest gaps are visible, not silently zero-filled.
    expect(screen.getAllByText(/重跑未做 tornado 探针/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/重跑未生成此项/).length).toBeGreaterThan(0)
    expect(screen.getByText(/里程碑 失败（节点 -24.6%）/)).toBeTruthy()
  })

  it('huawei2000: reading view shows the real B distribution and score line', async () => {
    const derivation = derivationReadV2ByKey.huawei2000
    const narrative = narrativeReadV2ByKey.huawei2000
    mockFetchFor(derivation.anchor_run_id, derivation, narrative)
    await pickAnchorRun(derivation.anchor_run_id)
    expect(await screen.findByText('方向 1：B 坚持投入')).toBeTruthy()
    expect(screen.getByText(/P10 1218.2159 \/ P50 1339.6083 \/ P90 1448.4684/)).toBeTruthy()
    expect(screen.getByText(/量级-收入 部分通过（-27.7%）/)).toBeTruthy()
  })

  it('desay2015: reading view shows the real B distribution', async () => {
    const derivation = derivationReadV2ByKey.desay2015
    const narrative = narrativeReadV2ByKey.desay2015
    mockFetchFor(derivation.anchor_run_id, derivation, narrative)
    await pickAnchorRun(derivation.anchor_run_id)
    expect(await screen.findByText('方向 1：B invest smart cockpit ADAS')).toBeTruthy()
    expect(screen.getByText(/P10 8407.7518 \/ P50 8778.0068 \/ P90 9626.1575/)).toBeTruthy()
    expect(screen.getByText(/量级-收入 部分通过（\+29.1%）/)).toBeTruthy()
  })

  it('nokia2007: reading view shows the real B distribution with its 0.6 loss', async () => {
    const derivation = derivationReadV2ByKey.nokia2007
    const narrative = narrativeReadV2ByKey.nokia2007
    mockFetchFor(derivation.anchor_run_id, derivation, narrative)
    await pickAnchorRun(derivation.anchor_run_id)
    expect(await screen.findByText('方向 1：B 转向触屏生态')).toBeTruthy()
    expect(screen.getByText(/P10 34.5616 \/ P50 39.8909 \/ P90 44.589/)).toBeTruthy()
    expect(screen.getByText(/亏损概率 60.0%/)).toBeTruthy()
  })
})
