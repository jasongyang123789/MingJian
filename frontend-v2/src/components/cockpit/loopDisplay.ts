// Display helpers for the living-strategy loop views (Sprint 9).
// Kept in a component-free module so react-refresh stays happy:
// LoopViews.tsx exports components only.

import type { LoopTriggerDefinition, ReviewDecision } from '../../api/engineTypes'
import { formatNumber } from './format'

export function loopInputClassName() {
  return 'w-full rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none'
}

export const ITERATION_STATE_LABELS: Record<string, string> = {
  open: '待评估',
  evaluated: '已评估',
  resimulated: '已重模拟',
  compared: '已比较',
  decided: '已决策',
}

export const DECISION_LABELS: Record<ReviewDecision, string> = {
  continue: '继续',
  pivot: '转向',
  pause: '暂停',
  stop: '停止',
}

/** One-line human-readable summary of a trigger definition. */
export function triggerSummary(trigger: LoopTriggerDefinition): string {
  switch (trigger.kind) {
    case 'threshold':
      return `最新观测 ${trigger.field} ${trigger.operator} ${formatNumber(trigger.threshold)}`
    case 'gate':
      return `观测统计 ${trigger.gate.metric}(${trigger.field}) ${trigger.gate.operator} ${formatNumber(trigger.gate.threshold)}`
    case 'deviation':
      return `${trigger.field} 连续 ${trigger.consecutive} 次偏离${
        trigger.reference_value !== null ? ` ${formatNumber(trigger.reference_value)}` : '基线终值'
      } 超过 ${formatNumber(trigger.tolerance)}`
  }
}
