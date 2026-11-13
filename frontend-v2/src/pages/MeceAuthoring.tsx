import { useState } from 'react'
import { GitBranch } from 'lucide-react'

import { meceApi, skillsApi } from '../api/engine'
import type {
  DecompositionTree,
  MeceProposalRead,
  MeceValidationResult,
} from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import { LlmStatusBanner } from '../components/cockpit/LlmStatusBanner'
import { MeceTreeView, MeceValidationView } from '../components/cockpit/MeceViews'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

const DEFAULT_DIMENSIONS = ['Demand', 'Capability', 'Economics', 'Risk']

function splitLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
}

function inputClassName() {
  return 'w-full rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-blue-500/50 focus:outline-none'
}

export default function MeceAuthoring() {
  const [topic, setTopic] = useState('')
  const [contextText, setContextText] = useState('')
  const [dimensionsText, setDimensionsText] = useState(DEFAULT_DIMENSIONS.join('\n'))
  const [outputLanguage, setOutputLanguage] = useState('English')
  const [proposal, setProposal] = useState<MeceProposalRead | null>(null)
  const [proposalCount, setProposalCount] = useState(0)
  const [proposing, setProposing] = useState(false)
  const [proposeError, setProposeError] = useState<unknown>(null)
  const [copied, setCopied] = useState(false)

  const [validateJson, setValidateJson] = useState('')
  const [validation, setValidation] = useState<MeceValidationResult | null>(null)
  const [validating, setValidating] = useState(false)
  const [validateError, setValidateError] = useState<string | null>(null)

  async function propose(existingTree: DecompositionTree | null) {
    setProposing(true)
    setProposeError(null)
    try {
      const result = await skillsApi.proposeMece({
        topic: topic.trim(),
        context_lines: splitLines(contextText),
        suggested_dimensions: splitLines(dimensionsText),
        existing_tree: existingTree,
        output_language: outputLanguage.trim() || 'English',
      })
      setProposal(result)
      setProposalCount((count) => count + 1)
      setCopied(false)
    } catch (error) {
      setProposeError(error)
    } finally {
      setProposing(false)
    }
  }

  async function validateTree() {
    setValidating(true)
    setValidateError(null)
    setValidation(null)
    try {
      const parsed: unknown = JSON.parse(validateJson)
      if (typeof parsed !== 'object' || parsed === null || !('root' in parsed)) {
        setValidateError('JSON 必须是一个包含 root 的分解树对象（{ topic, root: { name, scope, children } }）。')
        return
      }
      const result = await meceApi.validate(parsed as DecompositionTree)
      setValidation(result)
    } catch (error) {
      setValidateError(error instanceof Error ? error.message : String(error))
    } finally {
      setValidating(false)
    }
  }

  async function copyProposalJson() {
    if (!proposal) return
    try {
      await navigator.clipboard.writeText(JSON.stringify(proposal.proposal, null, 2))
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">MECE 编写</h1>
        <p className="mt-1 text-sm text-slate-500">
          提示词提议分解树，Sprint 1 代码校验器拍板：提议的树必须通过校验才能挂到 Run 上
        </p>
      </div>

      <CockpitNav />

      {proposeError ? <LlmStatusBanner error={proposeError} /> : null}

      <Card>
        <CardHeader title="提议分解树" />
        <CardBody className="space-y-4">
          <div>
            <label htmlFor="mece-topic" className="mb-1.5 block text-xs text-slate-500">
              决策主题
            </label>
            <input
              id="mece-topic"
              value={topic}
              onChange={(event) => setTopic(event.target.value)}
              placeholder="例如：Should we launch the AI customer-service line?"
              className={inputClassName()}
            />
          </div>
          <div>
            <label htmlFor="mece-context" className="mb-1.5 block text-xs text-slate-500">
              上下文（每行一条）
            </label>
            <textarea
              id="mece-context"
              value={contextText}
              onChange={(event) => setContextText(event.target.value)}
              placeholder={'20-person SaaS team\n12-month horizon\nNo new funding round'}
              rows={3}
              className={inputClassName()}
            />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="mece-dimensions" className="mb-1.5 block text-xs text-slate-500">
                建议维度（每行一个，可覆盖默认四维）
              </label>
              <textarea
                id="mece-dimensions"
                value={dimensionsText}
                onChange={(event) => setDimensionsText(event.target.value)}
                rows={4}
                className={inputClassName()}
              />
            </div>
            <div>
              <label htmlFor="mece-language" className="mb-1.5 block text-xs text-slate-500">
                输出语言
              </label>
              <input
                id="mece-language"
                value={outputLanguage}
                onChange={(event) => setOutputLanguage(event.target.value)}
                className={inputClassName()}
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={() => void propose(null)}
              disabled={proposing || topic.trim().length === 0}
              className="flex items-center gap-2 rounded-lg bg-blue-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-600 disabled:opacity-50"
            >
              <GitBranch className="h-4 w-4" />
              {proposing ? '提议中…' : '提议分解树'}
            </button>
            {proposal && !proposal.validation.is_mece && (
              <button
                onClick={() => void propose(proposal.proposal)}
                disabled={proposing}
                className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm font-medium text-amber-300 transition-colors hover:bg-amber-500/20 disabled:opacity-50"
              >
                用这棵树再提议一次（existing_tree 修订）
              </button>
            )}
            {proposalCount > 0 && (
              <span className="text-xs text-slate-500">
                本次会话已提议 {proposalCount} 次（修订是单步的，没有自动 revise-until-valid 循环）
              </span>
            )}
          </div>
        </CardBody>
      </Card>

      {proposing && <LoadingSpinner />}

      {proposal && (
        <Card>
          <CardHeader
            title="提议结果"
            action={
              <button
                onClick={() => void copyProposalJson()}
                className="rounded-full border border-slate-700/60 px-3 py-1 text-xs text-slate-300 transition hover:bg-slate-800/50"
              >
                {copied ? '已复制' : '复制树 JSON'}
              </button>
            }
          />
          <CardBody className="space-y-5">
            <p className="font-mono text-[11px] text-slate-500">
              阶段 {proposal.stage.stage} · 模板 {proposal.stage.template_id} v{proposal.stage.template_version} ·
              契约 skills-v{proposal.stage.contract_version}
            </p>
            <MeceTreeView tree={proposal.proposal} />
            <MeceValidationView validation={proposal.validation} />
            {!proposal.validation.is_mece && (
              <p className="text-xs leading-5 text-slate-400">
                这棵树未通过校验：挂到 Run 上会被创建门禁拒绝（400 mece_validation_failed，零行写入）。可以用它作为
                existing_tree 再提议一次，或在下面手工校验修改后的 JSON。
              </p>
            )}
            <details className="rounded-lg border border-slate-800/60 p-3">
              <summary className="cursor-pointer text-xs text-slate-400">树 JSON（可用于 Run 创建请求）</summary>
              <pre className="mt-2 overflow-x-auto font-mono text-[11px] leading-5 text-slate-300">
                {JSON.stringify(proposal.proposal, null, 2)}
              </pre>
            </details>
          </CardBody>
        </Card>
      )}

      {!proposal && !proposing && (
        <EmptyState
          icon="🌳"
          title="尚未提议"
          description="填写决策主题并提议，LLM 返回的树会连同校验 verdict 一起显示在这里"
        />
      )}

      <Card>
        <CardHeader title="手工校验分解树 JSON（纯函数，无 LLM）" />
        <CardBody className="space-y-4">
          <textarea
            aria-label="分解树 JSON"
            value={validateJson}
            onChange={(event) => setValidateJson(event.target.value)}
            placeholder={'{\n  "topic": "...",\n  "root": { "name": "...", "scope": ["..."], "children": [] }\n}'}
            rows={6}
            className={`${inputClassName()} font-mono text-xs`}
          />
          <div className="flex items-center gap-3">
            <button
              onClick={() => void validateTree()}
              disabled={validating || validateJson.trim().length === 0}
              className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-4 py-2 text-sm font-medium text-blue-400 transition-colors hover:bg-blue-500/20 disabled:opacity-50"
            >
              {validating ? '校验中…' : '校验'}
            </button>
          </div>
          {validateError && <ErrorBanner message={validateError} />}
          {validation && <MeceValidationView validation={validation} />}
        </CardBody>
      </Card>
    </div>
  )
}
