import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  advisoryBoardRecord,
  advisoryBoardVetoRecord,
  strategyTeamDeepRecord,
  strategyTeamRecord,
} from '../../test/engineFixtures'
import { DeliberationRecordView } from './DeliberationResults'

describe('StrategyTeamResultView', () => {
  it('renders shortlist, synthesis pyramid, and panel tally', () => {
    render(<DeliberationRecordView record={strategyTeamRecord} />)
    expect(screen.getByText(/#1 Phased rollout/)).toBeInTheDocument()
    expect(screen.getByText(/Launch in phases: prove the AI line/)).toBeInTheDocument()
    expect(screen.getByText('Demand is real but unpriced')).toBeInTheDocument()
    expect(screen.getByText(/推荐选项：/)).toBeInTheDocument()
    expect(screen.getByText(/在 shortlist 内/)).toBeInTheDocument()
    expect(screen.getByText(/落选：Acquire a small AI vendor/)).toBeInTheDocument()
  })

  it('highlights must-address flags and shows single-lens flags without the badge', () => {
    render(<DeliberationRecordView record={strategyTeamRecord} />)
    expect(screen.getAllByText('必须处理')).toHaveLength(2)
    expect(screen.getByText('Demand growth assumption is untested')).toBeInTheDocument()
    // The capacity flag appears twice: once in the tally, once as a pre-mortem failure mode.
    expect(screen.getAllByText('Delivery capacity cannot cover launch volume')).toHaveLength(2)
    expect(screen.getByText('Rival undercuts price within one quarter')).toBeInTheDocument()
    expect(screen.getByText(/视角：假设审计、兵棋推演/)).toBeInTheDocument()
  })

  it('renders the war-game playbook and pre-mortem failure modes', () => {
    render(<DeliberationRecordView record={strategyTeamRecord} />)
    expect(screen.getByText('Adverse: rival undercuts')).toBeInTheDocument()
    expect(screen.getByText(/Rival announces price cut →/)).toBeInTheDocument()
    expect(screen.getByText(/One year later the AI line is shut down/)).toBeInTheDocument()
  })

  it('renders the tournament bracket and loop info in deep mode only', () => {
    const { unmount } = render(<DeliberationRecordView record={strategyTeamRecord} />)
    expect(screen.queryByText(/对决评判/)).not.toBeInTheDocument()
    unmount()

    render(<DeliberationRecordView record={strategyTeamDeepRecord} />)
    expect(screen.getByText(/对决评判（两两对决，深度模式）/)).toBeInTheDocument()
    expect(screen.getByText(/Phased rollout 2，Full launch 1，Partner-led 0/)).toBeInTheDocument()
    expect(screen.getByText(/Phased rollout vs Full launch → 胜者/)).toBeInTheDocument()
    expect(screen.getByText(/深度模式追加 2 轮，连续两轮无新增致命问题/)).toBeInTheDocument()
  })

  it('shows stage provenance with template id + version for every stage', () => {
    render(<DeliberationRecordView record={strategyTeamRecord} />)
    expect(screen.getByText(/mckinsey.intake_classify v1/)).toBeInTheDocument()
    expect(screen.getByText(/gambit.premortem v1/)).toBeInTheDocument()
    expect(screen.getByText('option_generate:bull')).toBeInTheDocument()
    expect(screen.getAllByText(/contract skills-v1/)).toHaveLength(11)
  })
})

describe('AdvisoryBoardResultView', () => {
  it('renders lens score tables, weighted directions, and the debate', () => {
    render(<DeliberationRecordView record={advisoryBoardRecord} />)
    expect(screen.getByText(/第一轮 · 各视角独立打分/)).toBeInTheDocument()
    expect(screen.getByText(/第三轮 · 修订后打分/)).toBeInTheDocument()
    expect(screen.getByText('#1 Phased rollout · 7.2')).toBeInTheDocument()
    expect(screen.getByText('#1 Phased rollout · 7.4545')).toBeInTheDocument()
    expect(screen.getByText('Speed of mechanism vs cost of being wrong.')).toBeInTheDocument()
    expect(screen.getByText(/少数派异议/)).toBeInTheDocument()
  })

  it('renders the decision contract card with verdict, criteria, owner, and dates', () => {
    render(<DeliberationRecordView record={advisoryBoardRecord} />)
    expect(screen.getByText('validate_first')).toBeInTheDocument()
    expect(screen.getByText(/At least six of ten pilot accounts convert/)).toBeInTheDocument()
    expect(screen.getByText(/Fewer than six conversions/)).toBeInTheDocument()
    expect(screen.getByText('Founder')).toBeInTheDocument()
    expect(screen.getByText(/Founder calls the ten friendly accounts/)).toBeInTheDocument()
    expect(screen.getByText(/30 days to pre-sell/)).toBeInTheDocument()
    expect(screen.getByText(/30 days from now/)).toBeInTheDocument()
    expect(screen.getByText(/Pre-sell ten commitments before building/)).toBeInTheDocument()
  })

  it('shows a recorded-but-mitigated veto as a note, not a blocking banner', () => {
    render(<DeliberationRecordView record={advisoryBoardRecord} />)
    expect(screen.getByText(/记录在案的否决（1）/)).toBeInTheDocument()
    expect(screen.getByText(/Cash runway collapses if launch slips two quarters/)).toBeInTheDocument()
    expect(screen.queryByText(/存在未缓解的否决/)).not.toBeInTheDocument()
  })

  it('shows a blocking veto banner when has_unmitigated_veto is true', () => {
    render(<DeliberationRecordView record={advisoryBoardVetoRecord} />)
    const banner = screen.getByRole('alert')
    expect(banner).toHaveTextContent('存在未缓解的否决')
    expect(banner).toHaveTextContent('Cash runway collapses if launch slips two quarters')
    expect(screen.getByText('choose')).toBeInTheDocument()
  })
})
