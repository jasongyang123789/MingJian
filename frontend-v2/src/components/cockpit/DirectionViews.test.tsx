import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { narrativeRead, narrativeReadPolished } from '../../test/engineFixtures'
import { DirectionView, NarrativeView, ProvenanceBadge } from './DirectionViews'

describe('ProvenanceBadge', () => {
  it('labels each provenance kind', () => {
    const { rerender } = render(<ProvenanceBadge provenance="computed" />)
    expect(screen.getByText('计算')).toBeTruthy()
    rerender(<ProvenanceBadge provenance="deliberated" />)
    expect(screen.getByText('商议引用')).toBeTruthy()
    rerender(<ProvenanceBadge provenance="template" />)
    expect(screen.getByText('模板措辞')).toBeTruthy()
  })
})

describe('DirectionView', () => {
  it('renders distribution, drivers, signals, premortem, first step, and MECE trace', () => {
    render(<DirectionView direction={narrativeRead.body.directions[0]} />)
    expect(screen.getByText('方向 1：Go all in')).toBeTruthy()
    expect(screen.getByText(/P10 2 \/ P50 10 \/ P90 18/)).toBeTruthy()
    expect(screen.getByText(/亏损概率 20\.0%/)).toBeTruthy()
    expect(screen.getByText(/期望损失（ES）：-3/)).toBeTruthy()
    expect(screen.getByText(/Bootstrap p50：估计 10，区间 \[8, 12\]/)).toBeTruthy()
    expect(screen.getByText(/demand：0 → 1 时结果 0 → 20/)).toBeTruthy()
    expect(screen.getByText(/Gate floor: p50 >= 5/)).toBeTruthy()
    expect(screen.getByText(/Loop trigger cash-floor: cash < 70/)).toBeTruthy()
    expect(screen.getByText('The launch failed in month three.')).toBeTruthy()
    expect(screen.getByText(/失败模式：Support overload/)).toBeTruthy()
    expect(screen.getByText(/致命标记：No fallback vendor/)).toBeTruthy()
    expect(screen.getByText(/引自 deliberation delib-strategy-1/)).toBeTruthy()
    expect(screen.getByText('No advisory-board deliberation is recorded for this direction.')).toBeTruthy()
    expect(screen.getByText(/MECE 分支：Demand（demand）/)).toBeTruthy()
  })

  it('shows template notes when drivers and signals are absent', () => {
    const direction = {
      ...narrativeRead.body.directions[0],
      drivers: { provenance: 'computed' as const, rows: [], ensemble_id: null, note: 'No tornado stored.' },
      signals: [],
      signals_note: 'No signals yet.',
    }
    render(<DirectionView direction={direction} />)
    expect(screen.getByText('No tornado stored.')).toBeTruthy()
    expect(screen.getByText('No signals yet.')).toBeTruthy()
  })
})

describe('NarrativeView', () => {
  it('renders header context, directions, deterministic markdown, and the unpolished notice', () => {
    render(
      <NarrativeView narrative={narrativeRead} onPolish={() => {}} polishing={false} polishError={null} />,
    )
    expect(screen.getByText('简报：Launch decision')).toBeTruthy()
    expect(screen.getByText(/版本 v2/)).toBeTruthy()
    expect(screen.getByText(/MECE：Should we launch\?；校验通过/)).toBeTruthy()
    expect(screen.getByText(/校准拟合 fit-1/)).toBeTruthy()
    expect(screen.getByText(/监测循环：Watch/)).toBeTruthy()
    expect(screen.getByText(/# 决策方向简报：Launch decision/)).toBeTruthy()
    expect(screen.getByText(/尚未润色/)).toBeTruthy()
  })

  it('renders polished text with the LLM-generated label and calls onPolish', () => {
    const onPolish = vi.fn()
    render(
      <NarrativeView narrative={narrativeReadPolished} onPolish={onPolish} polishing={false} polishError={null} />,
    )
    expect(screen.getByText(/# Polished launch brief/)).toBeTruthy()
    expect(screen.getByText(/由 LLM 生成/)).toBeTruthy()
    expect(screen.getByText(/fixture-model/)).toBeTruthy()
    fireEvent.click(screen.getByText('请求润色'))
    expect(onPolish).toHaveBeenCalledTimes(1)
  })

  it('shows the polish error and disables the button while polishing', () => {
    render(
      <NarrativeView narrative={narrativeRead} onPolish={() => {}} polishing polishError="LLM 未配置，无法润色；确定性简报不受影响。" />,
    )
    expect(screen.getByText(/LLM 未配置/)).toBeTruthy()
    expect((screen.getByText('润色中…') as HTMLButtonElement).disabled).toBe(true)
  })
})
