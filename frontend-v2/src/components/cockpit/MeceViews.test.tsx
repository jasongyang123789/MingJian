import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { meceInvalidValidation, meceRunRead } from '../../test/engineFixtures'
import { MeceTreeView, MeceValidationView } from './MeceViews'

describe('MeceTreeView', () => {
  it('renders the tree recursively with scope tags', () => {
    render(<MeceTreeView tree={meceRunRead.decomposition} />)
    expect(screen.getByText('Launch decision')).toBeInTheDocument()
    expect(screen.getByText('Demand')).toBeInTheDocument()
    expect(screen.getByText('Capability')).toBeInTheDocument()
    expect(screen.getByText('Economics')).toBeInTheDocument()
    expect(screen.getAllByText('demand').length).toBeGreaterThan(0)
    expect(screen.getByText('Should we launch the AI customer-service line?')).toBeInTheDocument()
  })
})

describe('MeceValidationView', () => {
  it('shows the PASS verdict with check records', () => {
    render(<MeceValidationView validation={meceRunRead.validation} />)
    expect(screen.getByText('MECE 通过')).toBeInTheDocument()
    expect(screen.getByText('mutual_exclusion')).toBeInTheDocument()
    expect(screen.getByText('exhaustiveness')).toBeInTheDocument()
    expect(screen.getAllByText('PASS').length).toBe(2)
  })

  it('shows issues inline with kind, node, tags, and branches', () => {
    render(<MeceValidationView validation={meceInvalidValidation} />)
    expect(screen.getByText('MECE 未通过')).toBeInTheDocument()
    expect(screen.getByText(/重叠 · 节点「Launch decision」/)).toBeInTheDocument()
    expect(screen.getByText(/标签：capability/)).toBeInTheDocument()
    expect(screen.getByText(/分支：Demand and capability, Capability and economics/)).toBeInTheDocument()
    expect(screen.getByText('FAIL')).toBeInTheDocument()
  })
})
