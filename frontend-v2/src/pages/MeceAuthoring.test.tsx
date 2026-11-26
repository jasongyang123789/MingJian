import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { MeceProposalRead } from '../api/engineTypes'
import { meceInvalidValidation, meceRunRead } from '../test/engineFixtures'
import MeceAuthoring from './MeceAuthoring'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const VALID_PROPOSAL: MeceProposalRead = {
  proposal: meceRunRead.decomposition,
  validation: meceRunRead.validation,
  stage: {
    stage: 'propose_tree',
    template_id: 'mece.propose_tree',
    template_version: '1',
    contract_version: '1',
    output: {},
    model: 'fixture-model',
  },
}

const INVALID_TREE = {
  topic: 'Should we launch the AI customer-service line?',
  root: {
    name: 'Launch decision',
    scope: ['demand', 'capability', 'economics'],
    children: [
      { name: 'Demand and capability', scope: ['demand', 'capability'], children: [] },
      { name: 'Capability and economics', scope: ['capability', 'economics'], children: [] },
    ],
  },
}

const INVALID_PROPOSAL: MeceProposalRead = {
  proposal: INVALID_TREE,
  validation: meceInvalidValidation,
  stage: VALID_PROPOSAL.stage,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <MeceAuthoring />
    </MemoryRouter>,
  )
}

describe('MeceAuthoring', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('proposes a tree and shows the proposal with its PASS verdict', async () => {
    vi.spyOn(window, 'fetch').mockResolvedValue(jsonResponse(VALID_PROPOSAL))
    renderPage()

    fireEvent.change(screen.getByLabelText('决策主题'), { target: { value: 'Launch?' } })
    fireEvent.click(screen.getByRole('button', { name: /提议分解树/ }))

    expect(await screen.findByText('MECE 通过')).toBeInTheDocument()
    // 'Launch decision' appears 3 times: the tree root plus two check rows.
    expect(screen.getAllByText('Launch decision')).toHaveLength(3)
    expect(screen.getByText(/mece.propose_tree v1/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /再提议一次/ })).not.toBeInTheDocument()
  })

  it('shows validation issues inline and re-proposes with the failing tree as existing_tree', async () => {
    const fetchMock = vi
      .spyOn(window, 'fetch')
      .mockResolvedValueOnce(jsonResponse(INVALID_PROPOSAL))
      .mockResolvedValueOnce(jsonResponse(VALID_PROPOSAL))
    renderPage()

    fireEvent.change(screen.getByLabelText('决策主题'), { target: { value: 'Launch?' } })
    fireEvent.click(screen.getByRole('button', { name: /提议分解树/ }))

    expect(await screen.findByText('MECE 未通过')).toBeInTheDocument()
    expect(screen.getByText(/重叠 · 节点「Launch decision」/)).toBeInTheDocument()
    expect(screen.getByText(/会被创建门禁拒绝/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /再提议一次/ }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2)
    })
    const secondBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body))
    expect(secondBody.existing_tree).toEqual(INVALID_TREE)
    expect(await screen.findByText('MECE 通过')).toBeInTheDocument()
    expect(screen.getByText(/本次会话已提议 2 次/)).toBeInTheDocument()
  })

  it('surfaces the honest 503 banner when no LLM is configured', async () => {
    vi.spyOn(window, 'fetch').mockResolvedValue(
      jsonResponse({ detail: { code: 'skill_llm_unavailable', message: 'No LLM is configured.' } }, 503),
    )
    renderPage()

    fireEvent.change(screen.getByLabelText('决策主题'), { target: { value: 'Launch?' } })
    fireEvent.click(screen.getByRole('button', { name: /提议分解树/ }))

    expect(await screen.findByText('未配置 LLM，无法启动商议')).toBeInTheDocument()
  })

  it('validates pasted tree JSON without an LLM call', async () => {
    const fetchMock = vi.spyOn(window, 'fetch').mockResolvedValue(jsonResponse(meceRunRead.validation))
    renderPage()

    fireEvent.change(screen.getByLabelText('分解树 JSON'), {
      target: { value: JSON.stringify(meceRunRead.decomposition) },
    })
    fireEvent.click(screen.getByRole('button', { name: '校验' }))

    expect(await screen.findByText('MECE 通过')).toBeInTheDocument()
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/mece/validate')
  })

  it('rejects malformed JSON and non-tree JSON inline', async () => {
    renderPage()
    fireEvent.change(screen.getByLabelText('分解树 JSON'), { target: { value: '{not json' } })
    fireEvent.click(screen.getByRole('button', { name: '校验' }))
    expect(await screen.findByText(/Expected property name/)).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('分解树 JSON'), { target: { value: '{"topic": "x"}' } })
    fireEvent.click(screen.getByRole('button', { name: '校验' }))
    expect(await screen.findByText(/必须是一个包含 root 的分解树对象/)).toBeInTheDocument()
  })
})
