import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { SKILL_TEMPLATES } from '../data/skillTemplates'
import TemplateProvenance from './TemplateProvenance'

describe('TemplateProvenance', () => {
  it('pins the 17-template inventory with provenance', () => {
    expect(SKILL_TEMPLATES).toHaveLength(17)
    expect(new Set(SKILL_TEMPLATES.map((template) => template.id)).size).toBe(17)
    for (const template of SKILL_TEMPLATES) {
      expect(template.version).toBe('1')
      expect(template.sourceRepo.length).toBeGreaterThan(0)
      expect(template.sourceFile.length).toBeGreaterThan(0)
      expect(template.licenseNote.length).toBeGreaterThan(0)
    }
  })

  it('renders every template id with its license note', () => {
    render(
      <MemoryRouter>
        <TemplateProvenance />
      </MemoryRouter>,
    )
    expect(screen.getByText(/提示词模板清单（17 个/)).toBeInTheDocument()
    for (const template of SKILL_TEMPLATES) {
      expect(screen.getByText(new RegExp(template.id.replace('.', '\\.')))).toBeInTheDocument()
    }
    expect(screen.getByText(/No license declared in the source repo/)).toBeInTheDocument()
    expect(screen.getByText(/静态数据/)).toBeInTheDocument()
  })
})
