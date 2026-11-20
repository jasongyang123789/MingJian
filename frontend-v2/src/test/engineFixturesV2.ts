// Directions fixtures v2 — REAL backtest data (e047f50 rerun, 2026-11-19).
//
// v1 -> v2: the Sprint 13/14 fixtures in engineFixtures.ts (narrativeRead,
// derivationRead, directionMappingDerived) are hand-built mock values for a
// generic SaaS launch case (metric `cash`, P50 10, rules `derivation-rules-v1`,
// family_size 2, candidates 4). They are RETAINED in engineFixtures.ts only
// for the generic UI-behaviour tests that do not depend on data values
// (button flows, refusal codes, review queue, override forms).
// The Directions DATA fixtures are now v2: every number below is copied from
// the e047f50 four-case rerun (seed 42, trials 20, rule path, no LLM):
//   ~/workspace/research/strategy-engine/backtest-rerun-2026-11-19-e047f50/
//   REPORT.md (+ raw-classic/ + raw-desay/ JSON evidence).
//
// Contents:
// - backtestScorecardV2: the REPORT.md §0 score table + key P50s, per case.
//   Verdicts (direction / milestone / magnitude) are SCORING judgements from
//   REPORT.md, not backend fields — the backend returns no verdict field.
// - derivationRead* (in engineFixturesV2Derivations.ts, GENERATED): verbatim
//   copies of each case's 11-derive.json body (rules derivation-rules-v2).
// - narrativeRead* (built below): DecisionNarrativeRead assembled from the
//   real revenue MC distributions (06b/03b files) + real derive linkage.
//   HONEST LIMIT: the rerun never generated narratives, so no backend-issued
//   narrative exists. The parts the rerun never produced are left EMPTY and
//   labelled in their note fields (drivers: no tornado probe; signals: no
//   gates/loops evaluated; premortem/first-step: no deliberation run;
//   mece_trace: the rerun stored only MECE validation counts, not the tree).
//   inputs_hash reuses the anchor run's real determinism input_hash and
//   content_hash reuses the real derivation_hash as provenance links —
//   neither is a backend-issued narrative hash; see the builder comments.
//
// Refresh warning: the A/C merge, the milestone band-rule rework and the
// profit-chain pack promotion (all pending at 2026-11-20 11:05) WILL move
// these scores. After they land and the four cases are re-run, regenerate
// this file from the new rerun evidence — do not hand-edit numbers.

import type {
  DecisionNarrativeRead,
  DerivationRead,
  NarrativeDistributionSection,
} from '../api/engineTypes'
import {
  derivationReadDesay2015,
  derivationReadDesay2020,
  derivationReadHuawei2000,
  derivationReadNokia2007,
  revenueDistributionAnchorDesay2015,
  revenueDistributionAnchorDesay2020,
  revenueDistributionAnchorHuawei2000,
  revenueDistributionAnchorNokia2007,
  revenueDistributionBDesay2015,
  revenueDistributionBDesay2020,
  revenueDistributionBHuawei2000,
  revenueDistributionBNokia2007,
} from './engineFixturesV2Derivations'

export {
  derivationReadDesay2015,
  derivationReadDesay2020,
  derivationReadHuawei2000,
  derivationReadNokia2007,
}

// ---------------------------------------------------------------------------
// Scorecard: REPORT.md §0 + §3 (verdicts are scoring judgements, see header)
// ---------------------------------------------------------------------------

export type BacktestVerdict = 'pass' | 'partial' | 'fail' | 'not_scored'

export interface BacktestScorecardEntry {
  caseKey: 'huawei2000' | 'nokia2007' | 'desay2015' | 'desay2020'
  label: string
  topic: string
  anchorRunId: string
  domainId: 'corporate' | 'automotive'
  tickCount: number
  trials: number
  seed: number
  direction: BacktestVerdict
  directionNote: string
  milestone: BacktestVerdict
  milestoneNote: string
  magnitudeShare: BacktestVerdict
  magnitudeShareNote: string
  magnitudeRevenue: BacktestVerdict
  magnitudeRevenueNote: string
  /** Highest-P50 (B) arm, revenue ensemble. */
  bRevenueP50: number
  bRevenueP10: number
  bRevenueP90: number
  /** Highest-P50 (B) arm, market-share ensemble. */
  bShareP50: number
  bShareP10: number
  bShareP90: number
  anchorRevenueP50: number
  anchorShareP50: number
  actualShare: number | null
  actualRevenue: number | null
  revenueUnit: string
  milestoneYr3: { replay: number; actual: number; errorPct: number } | null
  milestoneYr5: { replay: number; actual: number; errorPct: number } | null
  profitNote: string | null
  downsideNote: string
  morphologyNote: string
  reportRef: string
}

export const backtestScorecardV2: BacktestScorecardEntry[] = [
  {
    caseKey: 'huawei2000',
    label: '华为 2000',
    topic: '华为2000：冬天来了，收缩过冬还是坚持投入？',
    anchorRunId: '30e09171-a945-47ce-81d1-c444a5b95426',
    domainId: 'corporate',
    tickCount: 10,
    trials: 20,
    seed: 42,
    direction: 'pass',
    directionNote: 'derive highest_p50 → B 坚持投入 (c55451c1)，与 ensemble 排序一致',
    milestone: 'pass',
    milestoneNote: '定性通过',
    magnitudeShare: 'partial',
    magnitudeShareNote: 'B 份额 P50 0.1124 vs 实际 ~0.157，-28.4%',
    magnitudeRevenue: 'partial',
    magnitudeRevenueNote: 'B 收入 P50 1339.6083 vs 实际 1852，-27.7%',
    bRevenueP50: 1339.6083,
    bRevenueP10: 1218.2159,
    bRevenueP90: 1448.4684,
    bShareP50: 0.1124,
    bShareP10: 0.0908,
    bShareP90: 0.1409,
    anchorRevenueP50: 1137.1442,
    anchorShareP50: 0.0808,
    actualShare: 0.157,
    actualRevenue: 1852,
    revenueUnit: '亿元人民币',
    milestoneYr3: null,
    milestoneYr5: null,
    profitNote: null,
    downsideNote:
      'ON 观测：B 收入 P50 1339.61→1283.62（-4.2%），decline_p 0.0→0.30；方向不变',
    morphologyNote: 'B 回放份额 t0 0.0299 → t4 0.0521 → t9 0.1048；收入 t0 201.9708 → t9 1209.2805',
    reportRef: 'REPORT.md §0, §3.1',
  },
  {
    caseKey: 'nokia2007',
    label: '诺基亚 2007',
    topic: '诺基亚2007：iPhone来了，坚持Symbian还是转向全触屏生态？',
    anchorRunId: '453f8429-86bc-4d2b-bbd8-99894c28f1ac',
    domainId: 'corporate',
    tickCount: 10,
    trials: 20,
    seed: 42,
    direction: 'pass',
    directionNote: 'derive highest_p50 → B 转向触屏生态 (1c8d6804)，份额优势 17 倍',
    milestone: 'partial',
    milestoneNote:
      'yr3 回放份额 0.3229 vs 实际 0.27（+20%）；yr5 回放 0.1442 vs 实际 0.064（2.25 倍）；实际两次均在锚点带内',
    magnitudeShare: 'partial',
    magnitudeShareNote:
      '按已实现臂 A 计分：A 份额 P50 0.0086 vs 实际 ~0，在 0.05 容差内（不是 B 臂 0.1487）',
    magnitudeRevenue: 'not_scored',
    magnitudeRevenueNote:
      '10 年节点口径不可比；支撑观测：yr3 收入回放 40.4741 vs 实际 42.446，-4.5%',
    bRevenueP50: 39.8909,
    bRevenueP10: 34.5616,
    bRevenueP90: 44.589,
    bShareP50: 0.1487,
    bShareP10: 0.1289,
    bShareP90: 0.1697,
    anchorRevenueP50: 2.1489,
    anchorShareP50: 0.0041,
    actualShare: 0,
    actualRevenue: 42.446,
    revenueUnit: '十亿欧元（实际 42.446 为 2010 年净销售额，yr3 节点对照）',
    milestoneYr3: { replay: 40.4741, actual: 42.446, errorPct: -4.5 },
    milestoneYr5: null,
    profitNote: null,
    downsideNote: '未跑 ON 观测（重跑只对华为与德赛两案做了下行 ON 观测）',
    morphologyNote: '已实现臂 A 回放份额 0.4041 → 0.0096（10 年）；收入 41.8009 → 3.1782',
    reportRef: 'REPORT.md §0, §3.2',
  },
  {
    caseKey: 'desay2015',
    label: '德赛西威 2015',
    topic: '德赛西威2015：投智能座舱+ADAS，还是守传统导航/娱乐硬件？',
    anchorRunId: 'eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c',
    domainId: 'automotive',
    tickCount: 5,
    trials: 20,
    seed: 42,
    direction: 'pass',
    directionNote:
      'derive highest_p50 → B invest smart cockpit ADAS (a798c506)；Track 11 时为部分通过',
    milestone: 'fail',
    milestoneNote:
      '带规则失败：yr3 实际收入 5408.74 在锚点 tick-3 带之下；节点回放 5188.946 vs 实际 -4.1%',
    magnitudeShare: 'not_scored',
    magnitudeShareNote: '未评分',
    magnitudeRevenue: 'partial',
    magnitudeRevenueNote: 'B 收入 P50 8778.0068 vs 实际 6799.06，+29.1%',
    bRevenueP50: 8778.0068,
    bRevenueP10: 8407.7518,
    bRevenueP90: 9626.1575,
    bShareP50: 0.4093,
    bShareP10: 0.373,
    bShareP90: 0.4355,
    anchorRevenueP50: 11824.7343,
    anchorShareP50: 0.452,
    actualShare: null,
    actualRevenue: 6799.06,
    revenueUnit: '百万元人民币',
    milestoneYr3: { replay: 5188.946, actual: 5408.74, errorPct: -4.1 },
    milestoneYr5: { replay: 8260.8202, actual: 6799.06, errorPct: 21.5 },
    profitNote: '利润未入打分规则，如实记录：yr3 利润 457.747 vs 实际 416.12（+10.0%）；yr5 557.279 vs 518.15（+7.5%）',
    downsideNote:
      'ON 观测：B 收入 P50 8778.01→8587.64（-2.2%），decline_p 0.0→0.20；锚点 decline_p 0.0→0.30',
    morphologyNote:
      '形态缺陷：B 回放增速因子 [1.2316, 1.2614, 1.2613, 1.2622] 未递减（2015 小簿形态未修）',
    reportRef: 'REPORT.md §0, §3.3',
  },
  {
    caseKey: 'desay2020',
    label: '德赛西威 2020',
    topic: '德赛西威2020：加码智能驾驶+座舱域控，还是稳守座舱/适度投入？',
    anchorRunId: 'fc7550f4-2b1d-49f5-a859-10a98036d8de',
    domainId: 'automotive',
    tickCount: 5,
    trials: 20,
    seed: 42,
    direction: 'pass',
    directionNote:
      'derive highest_p50 → B aggressive intelligent driving push (53db6d63)；Track 11 时为部分通过',
    milestone: 'fail',
    milestoneNote:
      'yr3 节点 -24.6%：回放 16512.3574 vs 实际 21908，实际在锚点 tick-3 带之下',
    magnitudeShare: 'not_scored',
    magnitudeShareNote: '未评分',
    magnitudeRevenue: 'partial',
    magnitudeRevenueNote: 'B 收入 P50 38721.6944 vs 实际 32557.18，+18.9%',
    bRevenueP50: 38721.6944,
    bRevenueP10: 36137.8763,
    bRevenueP90: 43693.5005,
    bShareP50: 0.0978,
    bShareP10: 0.0838,
    bShareP90: 0.1074,
    anchorRevenueP50: 60303.1553,
    anchorShareP50: 0.119,
    actualShare: null,
    actualRevenue: 32557.18,
    revenueUnit: '百万元人民币',
    milestoneYr3: { replay: 16512.3574, actual: 21908, errorPct: -24.6 },
    milestoneYr5: { replay: 37287.2008, actual: 32557.18, errorPct: 14.5 },
    profitNote: '利润未入打分规则，如实记录：yr3 利润 717.1663 vs 实际 1547（-53.6%）；yr5 990.5039 vs 2453.58（-59.6%）',
    downsideNote:
      'ON 观测：B 收入 P50 38721.69→36376.64（-6.1%），headline 统计仍全 0.0（~1.5×/tick 增速淹没众数 0.20 冲击）；可见信号是 P10 展宽 -43.2%',
    morphologyNote: 'B 回放增速因子 [1.621, 1.5959, 1.5183, 1.4873] 递减',
    reportRef: 'REPORT.md §0, §3.4',
  },
]

export const backtestScorecardByKey: Record<string, BacktestScorecardEntry> =
  Object.fromEntries(backtestScorecardV2.map((entry) => [entry.caseKey, entry]))

// ---------------------------------------------------------------------------
// Narratives v2 — assembled from real distributions (see header honest limit)
// ---------------------------------------------------------------------------

interface BacktestNarrativeInput {
  caseKey: string
  topic: string
  anchorRunId: string
  domainId: 'corporate' | 'automotive'
  bName: string
  bRunId: string
  anchorInputHash: string
  derivationHash: string
  derivation: DerivationRead
  bDistribution: NarrativeDistributionSection
  anchorDistribution: NarrativeDistributionSection
  meceBranchCount: number
  meceScopeTagCount: number
  createdAt: string
  derivedMappingIds: string[]
  scoreLine: string
}

const NOT_GENERATED =
  '重跑未生成此项：此处为空是诚实的缺失，不是零值。'

function buildBacktestNarrative(input: BacktestNarrativeInput): DecisionNarrativeRead {
  const b = input.bDistribution
  const a = input.anchorDistribution
  return {
    id: `narrative-v2-${input.caseKey}`,
    run_id: input.anchorRunId,
    version: 1,
    topic: input.topic,
    // Provenance links, NOT backend-issued narrative hashes: the rerun never
    // generated a narrative, so no narrative inputs_hash / content_hash
    // exists. inputs_hash reuses the anchor run's real determinism hash;
    // content_hash reuses the real derivation hash (the narrative's content
    // IS the derivation + the two distributions below).
    inputs_hash: input.anchorInputHash,
    content_hash: input.derivationHash,
    created_at: input.createdAt,
    direction_mapping_ids: input.derivedMappingIds,
    body: {
      protocol: 'backtest-v2-e047f50',
      anchor_run_id: input.anchorRunId,
      domain_id: input.domainId,
      topic: input.topic,
      topic_source: 'request',
      mece: {
        provenance: 'computed',
        topic: input.topic,
        is_mece: true,
        branch_count: input.meceBranchCount,
        scope_tag_count: input.meceScopeTagCount,
        issue_count: 0,
      },
      calibration_context: [],
      loop_context: null,
      directions: [
        {
          rank: 1,
          name: input.bName,
          source_run_id: input.bRunId,
          arm: 'baseline',
          distribution: b,
          drivers: {
            provenance: 'computed',
            rows: [],
            ensemble_id: b.ensemble_id,
            note: '重跑未做 tornado 探针：驱动行未测得，不是零影响。',
          },
          signals: [],
          signals_note: NOT_GENERATED + '重跑未评估决策门槛或 loop 触发器。',
          premortem: {
            provenance: 'template',
            deliberation_id: null,
            template_id: null,
            failure_narrative: null,
            failure_modes: [],
            fatal_flags: [],
            note: NOT_GENERATED + '重跑未跑 premortem deliberation。',
          },
          first_step: {
            provenance: 'template',
            deliberation_id: null,
            template_id: null,
            next_action: null,
            cheapest_validation_test: null,
            conditions: [],
            note: NOT_GENERATED + '重跑未跑 advisory-board deliberation。',
          },
          mece_trace: null,
          mece_note:
            '重跑只存了 MECE 验证计数（分支数/范围标签数），未存分解树，无法还原 trace。',
        },
        {
          rank: 2,
          name: 'Baseline',
          source_run_id: input.anchorRunId,
          arm: 'baseline',
          distribution: a,
          drivers: {
            provenance: 'computed',
            rows: [],
            ensemble_id: a.ensemble_id,
            note: '重跑未做 tornado 探针：驱动行未测得，不是零影响。',
          },
          signals: [],
          signals_note: NOT_GENERATED + '重跑未评估决策门槛或 loop 触发器。',
          premortem: {
            provenance: 'template',
            deliberation_id: null,
            template_id: null,
            failure_narrative: null,
            failure_modes: [],
            fatal_flags: [],
            note: NOT_GENERATED + '重跑未跑 premortem deliberation。',
          },
          first_step: {
            provenance: 'template',
            deliberation_id: null,
            template_id: null,
            next_action: null,
            cheapest_validation_test: null,
            conditions: [],
            note: NOT_GENERATED + '重跑未跑 advisory-board deliberation。',
          },
          mece_trace: null,
          mece_note:
            '重跑只存了 MECE 验证计数（分支数/范围标签数），未存分解树，无法还原 trace。',
        },
      ],
      markdown:
        `# 决策方向简报：${input.topic}\n\n` +
        `方向 1：${input.bName}（最高 P50）——收入 P50 ${b.p50} [${b.p10}–${b.p90}]，n=${b.n}，seed ${b.seed}\n\n` +
        `方向 2：Baseline（锚点对照）——收入 P50 ${a.p50} [${a.p10}–${a.p90}]\n\n` +
        `${input.scoreLine}`,
    },
    polish: null,
  }
}

export const narrativeReadHuawei2000: DecisionNarrativeRead = buildBacktestNarrative({
  caseKey: 'huawei2000',
  topic: '华为2000：冬天来了，收缩过冬还是坚持投入？',
  anchorRunId: '30e09171-a945-47ce-81d1-c444a5b95426',
  domainId: 'corporate',
  bName: 'B 坚持投入',
  bRunId: 'c55451c1-0425-45b9-978c-94eed2ba0aba',
  anchorInputHash: 'sha256:639d59d29c3f97bb08b7abe04e53a20f9f9daa45216f02c70a2641bab15b75da',
  derivationHash: 'sha256:1a15c44b64b72b8ffe3061d5cc7faa0c493f82b4e86f476e846a0eeba2146a60',
  derivation: derivationReadHuawei2000,
  bDistribution: revenueDistributionBHuawei2000,
  anchorDistribution: revenueDistributionAnchorHuawei2000,
  meceBranchCount: 3,
  meceScopeTagCount: 2,
  createdAt: '2026-11-19T15:36:23.575393Z',
  derivedMappingIds: [
    '3a994b14-27ad-45b9-a584-aff71d1e0030',
    'f1193272-5856-4e5a-b481-645e7fea1246',
  ],
  scoreLine:
    '打分（e047f50 重跑）：方向 通过；里程碑 通过（定性）；量级-份额 部分通过（-28.4%）；量级-收入 部分通过（-27.7%）。',
})

export const narrativeReadNokia2007: DecisionNarrativeRead = buildBacktestNarrative({
  caseKey: 'nokia2007',
  topic: '诺基亚2007：iPhone来了，坚持Symbian还是转向全触屏生态？',
  anchorRunId: '453f8429-86bc-4d2b-bbd8-99894c28f1ac',
  domainId: 'corporate',
  bName: 'B 转向触屏生态',
  bRunId: '1c8d6804-6fb2-4648-a30c-3627485594ea',
  anchorInputHash: 'sha256:7964f2519f406b8f7e1d71a18644fbcf6d98e5cc7c2b36b4d10f0447692b7ebc',
  derivationHash: 'sha256:791d36ba7474d0d92a7d4a2caf76273fecb14b60aa9256b43e58d903405c365b',
  derivation: derivationReadNokia2007,
  bDistribution: revenueDistributionBNokia2007,
  anchorDistribution: revenueDistributionAnchorNokia2007,
  meceBranchCount: 3,
  meceScopeTagCount: 2,
  createdAt: '2026-11-19T15:36:31.724099Z',
  derivedMappingIds: [
    '5d9a916b-4436-470c-b8ce-7825dd2582fa',
    '38ec481e-fe43-4564-84a4-b3c878be9972',
  ],
  scoreLine:
    '打分（e047f50 重跑）：方向 通过；里程碑 部分通过；量级-份额 部分通过（按已实现臂 A 计）；量级-收入 未评分（10 年节点口径不可比）。',
})

export const narrativeReadDesay2015: DecisionNarrativeRead = buildBacktestNarrative({
  caseKey: 'desay2015',
  topic: '德赛西威2015：投智能座舱+ADAS，还是守传统导航/娱乐硬件？',
  anchorRunId: 'eb32fb20-e4cd-4bcb-b8cf-a171e0f9d77c',
  domainId: 'automotive',
  bName: 'B invest smart cockpit ADAS',
  bRunId: 'a798c506-d352-48ac-ae66-54a0e26ad14e',
  anchorInputHash: 'sha256:846dea113a3fb2e7cf9c5f037e815d00380509190b7705a90d7ec019c711a577',
  derivationHash: 'sha256:9f53970edde931c0d0ed3d8f2e6418d7eea90cef1ba59fcd834b8872fa314213',
  derivation: derivationReadDesay2015,
  bDistribution: revenueDistributionBDesay2015,
  anchorDistribution: revenueDistributionAnchorDesay2015,
  meceBranchCount: 4,
  meceScopeTagCount: 3,
  createdAt: '2026-11-19T15:37:16.772773Z',
  derivedMappingIds: [
    '75266231-2baa-441e-8fae-4c3b452c0bad',
    '28a7222f-b47b-4ea6-8ea4-dea82eaf76c0',
  ],
  scoreLine:
    '打分（e047f50 重跑）：方向 通过；里程碑 失败（带规则；节点 -4.1%）；量级-收入 部分通过（+29.1%）；量级-份额 未评分。',
})

export const narrativeReadDesay2020: DecisionNarrativeRead = buildBacktestNarrative({
  caseKey: 'desay2020',
  topic: '德赛西威2020：加码智能驾驶+座舱域控，还是稳守座舱/适度投入？',
  anchorRunId: 'fc7550f4-2b1d-49f5-a859-10a98036d8de',
  domainId: 'automotive',
  bName: 'B aggressive intelligent driving push',
  bRunId: '53db6d63-1a8d-43a2-b46c-16cdd86ef837',
  anchorInputHash: 'sha256:a46af49c351c500c9ea0f892bc7ebfe480b5c7d50db97df14745e86ef8516ad6',
  derivationHash: 'sha256:3321f807d5a26646855a3de6bae3460b2ff6cafc266c9e56b3cf83243404a91b',
  derivation: derivationReadDesay2020,
  bDistribution: revenueDistributionBDesay2020,
  anchorDistribution: revenueDistributionAnchorDesay2020,
  meceBranchCount: 4,
  meceScopeTagCount: 3,
  createdAt: '2026-11-19T15:37:37.608138Z',
  derivedMappingIds: [
    '5f5d3588-6c8d-47ef-bf11-e45d5c8b9eed',
    'd3aefb89-f980-403f-940e-76266d1a6984',
  ],
  scoreLine:
    '打分（e047f50 重跑）：方向 通过；里程碑 失败（节点 -24.6%）；量级-收入 部分通过（+18.9%）；量级-份额 未评分。',
})

export const narrativeReadV2ByKey: Record<string, DecisionNarrativeRead> = {
  huawei2000: narrativeReadHuawei2000,
  nokia2007: narrativeReadNokia2007,
  desay2015: narrativeReadDesay2015,
  desay2020: narrativeReadDesay2020,
}

export const derivationReadV2ByKey: Record<string, DerivationRead> = {
  huawei2000: derivationReadHuawei2000,
  nokia2007: derivationReadNokia2007,
  desay2015: derivationReadDesay2015,
  desay2020: derivationReadDesay2020,
}
