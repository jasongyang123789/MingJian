import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ApiError } from '../../api/client'
import { LlmStatusBanner } from './LlmStatusBanner'

describe('LlmStatusBanner', () => {
  it('renders the honest unconfigured-LLM state for a 503', () => {
    const error = new ApiError(
      503,
      JSON.stringify({ detail: { code: 'skill_llm_unavailable', message: 'No LLM is configured.' } }),
    )
    render(<LlmStatusBanner error={error} />)
    expect(screen.getByRole('alert')).toHaveTextContent('未配置 LLM，无法启动商议')
    expect(screen.getByRole('alert')).toHaveTextContent('503 skill_llm_unavailable')
    expect(screen.queryByText(/契约校验/)).not.toBeInTheDocument()
  })

  it('renders the contract-failure state for a 502, distinct from 503', () => {
    const error = new ApiError(
      502,
      JSON.stringify({ detail: { code: 'skill_contract_failed', message: 'stage output failed contract', template_id: 'mckinsey.synthesize' } }),
    )
    render(<LlmStatusBanner error={error} />)
    expect(screen.getByRole('alert')).toHaveTextContent('LLM 输出未通过契约校验（502）')
    expect(screen.getByRole('alert')).toHaveTextContent('stage output failed contract')
    expect(screen.queryByText(/未配置 LLM/)).not.toBeInTheDocument()
  })

  it('renders a generic message for other errors', () => {
    render(<LlmStatusBanner error={new Error('boom')} />)
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
  })

  it('offers retry when a handler is given', () => {
    render(<LlmStatusBanner error={new Error('boom')} onRetry={() => undefined} />)
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })
})
