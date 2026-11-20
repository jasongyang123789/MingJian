// Fixture-guard tests for the v2 Directions fixtures.
//
// Every expected value below is pinned to the e047f50 rerun report
// (~/workspace/research/strategy-engine/backtest-rerun-2026-11-19-e047f50/REPORT.md
// §0 + §3) and the raw JSON evidence (raw-classic/, raw-desay/). If a future
// re-run moves a score, these tests MUST be updated together with the
// fixtures — a failure here means fixture and report disagree, not that the
// test is stale.

import { describe, expect, it } from 'vitest'

import {
  backtestScorecardByKey,
  backtestScorecardV2,
  derivationReadV2ByKey,
  narrativeReadV2ByKey,
} from './engineFixturesV2'

const CASES = [
  {
    key: 'huawei2000',
    familySize: 4,
    candidates: 8,
    bRunId: 'c55451c1-0425-45b9-978c-94eed2ba0aba',
    bRevenueP50: 1339.6083,
    bRevenueP10: 1218.2159,
    bRevenueP90: 1448.4684,
    bRevenuePLoss: 0,
    anchorRevenuePLoss: 0,
    bExpectedShortfall: 1148.4527,
    anchorExpectedShortfall: 256.125,
    bShareP50: 0.1124,
    anchorRunId: '30e09171-a945-47ce-81d1-c444a5b95426',
    anchorRevenueP50: 1137.1442,
    anchorShareP50: 0.0808,
    rulesHash: 'sha256:1a15c44b64b72b8ffe3061d5cc7faa0c493f82b4e86f476e846a0eeba2146a60',
    meceBranchCount: 3,
    meceScopeTagCount: 2,
  },
  {
    key: 'nokia2007',
    familySize: 3,
    candidates: 6,
    bRunId: '1c8d6804-6fb2-4648-a30c-3627485594ea',
    bRevenueP50: 39.8909,
    bRevenueP10: 34.5616,
    bRevenueP90: 44.589,
    bRevenuePLoss: 0.6,
    anchorRevenuePLoss: 1,
    bExpectedShortfall: 30.2886,
    anchorExpectedShortfall: 0.236,
    bShareP50: 0.1487,
    anchorRunId: '453f8429-86bc-4d2b-bbd8-99894c28f1ac',
    anchorRevenueP50: 2.1489,
    anchorShareP50: 0.0041,
    rulesHash: 'sha256:791d36ba7474d0d92a7d4a2caf76273fecb14b60aa9256b43e58d903405c365b',
    meceBranchCount: 3,
    meceScopeTagCount: 2,
  },
  {
    key: 'desay2015',
    familySize: 4,
    candidates: 8,
    bRunId: 'a798c506-d352-48ac-ae66-54a0e26ad14e',
    bRevenueP50: 8778.0068,
    bRevenueP10: 8407.7518,
    bRevenueP90: 9626.1575,
    bRevenuePLoss: 0,
    anchorRevenuePLoss: 0,
    bExpectedShortfall: 8279.2851,
    anchorExpectedShortfall: 9567.1614,
    bShareP50: 0.4093,
    anchorRunId: 'eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c',
    anchorRevenueP50: 11824.7343,
    anchorShareP50: 0.452,
    rulesHash: 'sha256:9f53970edde931c0d0ed3d8f2e6418d7eea90cef1ba59fcd834b8872fa314213',
    meceBranchCount: 4,
    meceScopeTagCount: 3,
  },
  {
    key: 'desay2020',
    familySize: 4,
    candidates: 8,
    bRunId: '53db6d63-1a8d-43a2-b46c-16cdd86ef837',
    bRevenueP50: 38721.6944,
    bRevenueP10: 36137.8763,
    bRevenueP90: 43693.5005,
    bRevenuePLoss: 0,
    anchorRevenuePLoss: 0,
    bExpectedShortfall: 35802.3209,
    anchorExpectedShortfall: 48618.9141,
    bShareP50: 0.0978,
    anchorRunId: 'fc7550f4-2b1d-49f5-a859-10a98036d8de',
    anchorRevenueP50: 60303.1553,
    anchorShareP50: 0.119,
    rulesHash: 'sha256:3321f807d5a26646855a3de6bae3460b2ff6cafc266c9e56b3cf83243404a91b',
    meceBranchCount: 4,
    meceScopeTagCount: 3,
  },
] as const

describe('Directions fixtures v2 (e047f50 rerun)', () => {
  it('covers all four backtest cases', () => {
    expect(backtestScorecardV2.map((entry) => entry.caseKey)).toEqual([
      'huawei2000',
      'nokia2007',
      'desay2015',
      'desay2020',
    ])
  })

  it.each(CASES)('$key: derivation is the verbatim v2 derive response', (c) => {
    const derivation = derivationReadV2ByKey[c.key]
    expect(derivation.rules_version).toBe('derivation-rules-v2')
    expect(derivation.derivation_hash).toBe(c.rulesHash)
    expect(derivation.anchor_run_id).toBe(c.anchorRunId)
    expect(derivation.family_size).toBe(c.familySize)
    expect(derivation.candidates_considered).toBe(c.candidates)
    const [highest, robust, baseline] = derivation.outcomes
    expect(highest.rule_id).toBe('highest_p50')
    expect(highest.status).toBe('produced')
    expect(highest.source_run_id).toBe(c.bRunId)
    expect(highest.arm).toBe('baseline')
    expect(highest.p50).toBe(c.bRevenueP50)
    expect(highest.p_loss).toBe(c.bRevenuePLoss)
    expect(highest.expected_shortfall).toBe(c.bExpectedShortfall)
    // most_robust never forks in this rerun (REPORT.md §6.5): duplicate of B.
    expect(robust.rule_id).toBe('most_robust')
    expect(robust.status).toBe('duplicate')
    expect(robust.duplicate_of_rule).toBe('highest_p50')
    expect(robust.source_run_id).toBe(c.bRunId)
    expect(robust.p50).toBe(c.bRevenueP50)
    expect(baseline.rule_id).toBe('baseline_control')
    expect(baseline.status).toBe('produced')
    expect(baseline.source_run_id).toBe(c.anchorRunId)
    expect(baseline.p50).toBe(c.anchorRevenueP50)
    expect(baseline.p_loss).toBe(c.anchorRevenuePLoss)
    expect(baseline.expected_shortfall).toBe(c.anchorExpectedShortfall)
    // The derived mappings stored by the derive call are present.
    const derived = derivation.mappings.filter((m) => m.origin === 'derived')
    expect(derived.map((m) => m.name)).toEqual(['Highest P50', 'Baseline'])
    expect(derived[0].source_run_id).toBe(c.bRunId)
    expect(derived[0].rule_id).toBe('highest_p50')
    expect(derived[0].rules_version).toBe('derivation-rules-v2')
    expect(derived[1].source_run_id).toBe(c.anchorRunId)
    expect(derived[1].rule_id).toBe('baseline_control')
  })

  it.each(CASES)('$key: scorecard P50s agree with the derivation', (c) => {
    const entry = backtestScorecardByKey[c.key]
    expect(entry.anchorRunId).toBe(c.anchorRunId)
    expect(entry.trials).toBe(20)
    expect(entry.seed).toBe(42)
    expect(entry.bRevenueP50).toBe(c.bRevenueP50)
    expect(entry.bRevenueP10).toBe(c.bRevenueP10)
    expect(entry.bRevenueP90).toBe(c.bRevenueP90)
    expect(entry.bShareP50).toBe(c.bShareP50)
    expect(entry.anchorRevenueP50).toBe(c.anchorRevenueP50)
    expect(entry.anchorShareP50).toBe(c.anchorShareP50)
    const derivation = derivationReadV2ByKey[c.key]
    expect(entry.bRevenueP50).toBe(derivation.outcomes[0].p50)
    expect(entry.anchorRevenueP50).toBe(derivation.outcomes[2].p50)
  })

  it('scorecard verdicts match REPORT.md §0', () => {
    expect(
      backtestScorecardV2.map((e) => [
        e.caseKey,
        e.direction,
        e.milestone,
        e.magnitudeShare,
        e.magnitudeRevenue,
      ]),
    ).toEqual([
      ['huawei2000', 'pass', 'pass', 'partial', 'partial'],
      ['nokia2007', 'pass', 'partial', 'partial', 'not_scored'],
      ['desay2015', 'pass', 'fail', 'not_scored', 'partial'],
      ['desay2020', 'pass', 'fail', 'not_scored', 'partial'],
    ])
  })

  it('milestone node error percentages recompute from replay vs actual', () => {
    for (const entry of backtestScorecardV2) {
      for (const node of [entry.milestoneYr3, entry.milestoneYr5]) {
        if (!node) continue
        const recomputed = ((node.replay - node.actual) / node.actual) * 100
        expect(recomputed).toBeCloseTo(node.errorPct, 0)
      }
    }
  })

  it.each(CASES)('$key: narrative carries the real distributions', (c) => {
    const narrative = narrativeReadV2ByKey[c.key]
    expect(narrative.run_id).toBe(c.anchorRunId)
    expect(narrative.body.anchor_run_id).toBe(c.anchorRunId)
    expect(narrative.body.protocol).toBe('backtest-v2-e047f50')
    expect(narrative.body.mece?.branch_count).toBe(c.meceBranchCount)
    expect(narrative.body.mece?.scope_tag_count).toBe(c.meceScopeTagCount)
    expect(narrative.body.mece?.is_mece).toBe(true)
    const [first, second] = narrative.body.directions
    expect(first.rank).toBe(1)
    expect(first.source_run_id).toBe(c.bRunId)
    expect(first.distribution.metric).toBe('revenue')
    expect(first.distribution.trials).toBe(20)
    expect(first.distribution.seed).toBe(42)
    expect(first.distribution.p50).toBe(c.bRevenueP50)
    expect(first.distribution.p10).toBe(c.bRevenueP10)
    expect(first.distribution.p90).toBe(c.bRevenueP90)
    expect(second.rank).toBe(2)
    expect(second.name).toBe('Baseline')
    expect(second.source_run_id).toBe(c.anchorRunId)
    expect(second.distribution.p50).toBe(c.anchorRevenueP50)
    // Honest gaps: the rerun never produced these, so they stay empty and
    // labelled — never filled with invented values.
    for (const direction of narrative.body.directions) {
      expect(direction.drivers.rows).toEqual([])
      expect(direction.signals).toEqual([])
      expect(direction.premortem.failure_narrative).toBeNull()
      expect(direction.premortem.failure_modes).toEqual([])
      expect(direction.first_step.next_action).toBeNull()
      expect(direction.mece_trace).toBeNull()
      expect(direction.mece_note).toContain('未存分解树')
    }
  })

  it('narrative markdown carries the real P50s and the score line', () => {
    const desay2020 = narrativeReadV2ByKey.desay2020
    expect(desay2020.body.markdown).toContain('收入 P50 38721.6944 [36137.8763–43693.5005]')
    expect(desay2020.body.markdown).toContain('收入 P50 60303.1553 [50560.3128–72479.4756]')
    expect(desay2020.body.markdown).toContain('里程碑 失败（节点 -24.6%）')
    const huawei = narrativeReadV2ByKey.huawei2000
    expect(huawei.body.markdown).toContain('收入 P50 1339.6083 [1218.2159–1448.4684]')
    expect(huawei.body.markdown).toContain('方向 通过')
  })
})
