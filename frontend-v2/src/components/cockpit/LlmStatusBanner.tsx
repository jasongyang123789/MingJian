import { isLlmContractFailure, isLlmUnavailable, parseApiError } from '../../api/engine'

// The honest LLM-boundary states (SPRINT6.md §7). The deliberation
// surfaces stay visible when no LLM is configured; only the launch
// action is blocked, and the banner says exactly why. A 502
// (malformed LLM output) is a different failure from a 503 (no LLM
// configured) and is rendered differently — never conflated.

export function LlmStatusBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const info = parseApiError(error)

  if (isLlmUnavailable(error)) {
    return (
      <div
        role="alert"
        className="flex items-center justify-between gap-4 rounded-[20px] border border-amber-500/20 bg-amber-500/5 px-4 py-3"
      >
        <div>
          <p className="text-sm font-medium text-amber-300">未配置 LLM，无法启动商议</p>
          <p className="mt-0.5 text-xs leading-5 text-amber-200/70">
            后端返回 503 skill_llm_unavailable：primary 目标没有配置密钥。历史记录与数值工件不受影响；配置密钥后即可启动。
          </p>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="shrink-0 rounded-full border border-amber-500/20 px-3 py-1 text-xs text-amber-300 transition hover:bg-amber-500/10"
          >
            重试
          </button>
        )}
      </div>
    )
  }

  if (isLlmContractFailure(error)) {
    return (
      <div
        role="alert"
        className="flex items-center justify-between gap-4 rounded-[20px] border border-red-500/20 bg-red-500/5 px-4 py-3"
      >
        <div>
          <p className="text-sm font-medium text-red-400">LLM 输出未通过契约校验（502）</p>
          <p className="mt-0.5 text-xs leading-5 text-red-300/80">{info.message}</p>
          <p className="mt-0.5 text-xs leading-5 text-slate-500">
            该阶段的输出不符合其 Pydantic 契约，已被拒绝且未写入任何记录。可以重试一次。
          </p>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="shrink-0 rounded-full border border-red-500/20 px-3 py-1 text-xs text-red-400 transition hover:bg-red-500/10 hover:text-red-300"
          >
            重试
          </button>
        )}
      </div>
    )
  }

  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-4 rounded-[20px] border border-red-500/20 bg-red-500/5 px-4 py-3"
    >
      <span className="text-sm text-red-400">{info.message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 rounded-full border border-red-500/20 px-3 py-1 text-xs text-red-400 transition hover:bg-red-500/10 hover:text-red-300"
        >
          重试
        </button>
      )}
    </div>
  )
}
