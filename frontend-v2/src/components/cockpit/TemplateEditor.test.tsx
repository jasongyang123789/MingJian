import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import {
  builtinTemplate,
  calibratedTemplate,
  calibrationFits,
  customTemplate,
  invalidValidationResult,
  validValidationResult,
} from '../../test/engineFixtures'
import { TemplateForm, TemplateReadView, ValidationIssuesView } from './TemplateEditor'
import { draftFromTemplate } from './templateDraft'
import type { TemplateDraft } from './templateDraft'

function Harness({
  initial,
  validation = null,
  saveValidation = null,
  saveError = null,
}: {
  initial: TemplateDraft
  validation?: Parameters<typeof TemplateForm>[0]['validation']
  saveValidation?: Parameters<typeof TemplateForm>[0]['saveValidation']
  saveError?: string | null
}) {
  const [draft, setDraft] = useState(initial)
  return (
    <TemplateForm
      draft={draft}
      onChange={setDraft}
      domains={['corporate', 'military']}
      domainLocked={false}
      validation={validation}
      onValidate={vi.fn()}
      validating={false}
      saveError={saveError}
      saveValidation={saveValidation}
      onSave={vi.fn()}
      saving={false}
      saveLabel="保存模板"
      dirty={false}
    />
  )
}

describe('TemplateForm', () => {
  it('renders the draft: variables, formula, state fields, policies, internal', () => {
    render(<Harness initial={draftFromTemplate(customTemplate)} />)
    expect(screen.getByDisplayValue('AI line case')).toBeInTheDocument()
    expect(screen.getByLabelText('变量 1 id')).toHaveValue('cash')
    expect(screen.getByLabelText('变量 2 id')).toHaveValue('cac')
    expect(screen.getByDisplayValue('runway_months')).toBeInTheDocument()
    expect(screen.getByDisplayValue('9 months of cash')).toBeInTheDocument()
    expect(screen.getByLabelText('变量 1 最小值')).toHaveValue(60)
    expect(screen.getByLabelText('变量 1 众数')).toHaveValue(100)
    expect(screen.getByLabelText('策略 1 alert 阈值')).toHaveValue(50)
  })

  it('switches the visible distribution parameters with the distribution type', () => {
    render(<Harness initial={draftFromTemplate(customTemplate)} />)
    const select = screen.getByLabelText('变量 1 分布类型')
    expect(screen.getByLabelText('变量 1 最小值')).toBeInTheDocument()
    expect(screen.queryByLabelText('变量 1 值')).not.toBeInTheDocument()

    fireEvent.change(select, { target: { value: 'fixed' } })
    expect(screen.getByLabelText('变量 1 值')).toBeInTheDocument()
    expect(screen.queryByLabelText('变量 1 最小值')).not.toBeInTheDocument()

    fireEvent.change(select, { target: { value: 'bernoulli' } })
    expect(screen.getByLabelText('变量 1 概率 p')).toBeInTheDocument()
    expect(screen.queryByLabelText('变量 1 值')).not.toBeInTheDocument()
  })

  it('keeps edits in the draft (controlled fields)', () => {
    render(<Harness initial={draftFromTemplate(customTemplate)} />)
    fireEvent.change(screen.getByLabelText('变量 1 单位'), { target: { value: 'USD' } })
    expect(screen.getByLabelText('变量 1 单位')).toHaveValue('USD')
    fireEvent.change(screen.getByLabelText('变量 1 最小值'), { target: { value: '70' } })
    expect(screen.getByLabelText('变量 1 最小值')).toHaveValue(70)
  })

  it('adds and removes variable rows', () => {
    render(<Harness initial={draftFromTemplate(customTemplate)} />)
    fireEvent.click(screen.getByText('+ 添加变量'))
    expect(screen.getByLabelText('变量 3 id')).toBeInTheDocument()
    fireEvent.click(screen.getAllByText('删除该变量')[2])
    expect(screen.queryByLabelText('变量 3 id')).not.toBeInTheDocument()
  })

  it('renders the stored formula as an editable op tree', () => {
    render(<Harness initial={draftFromTemplate(customTemplate)} />)
    expect(screen.getByLabelText('表达式')).toHaveValue('op')
    expect(screen.getByLabelText('运算符')).toHaveValue('divide')
    expect(screen.getByLabelText('引用')).toHaveValue('cash')
    expect(screen.getByLabelText('字面量')).toHaveValue(12)
    const operatorOptions = [...(screen.getByLabelText('运算符') as HTMLSelectElement).options].map(
      (option) => option.value,
    )
    expect(operatorOptions).toEqual(['add', 'subtract', 'multiply', 'divide', 'min', 'max'])
  })

  it('limits ref options to sampled variables plus earlier formulas', () => {
    const draft = draftFromTemplate(customTemplate)
    draft.formulas = [
      { output: 'runway_months', expression: { ref: 'cash' }, description: '' },
      { output: 'runway_years', expression: { ref: 'cash' }, description: '' },
    ]
    render(<Harness initial={draft} />)
    const refSelects = screen.getAllByLabelText('引用') as HTMLSelectElement[]
    expect(refSelects).toHaveLength(2)
    const firstOptions = [...refSelects[0].options].map((option) => option.value)
    const secondOptions = [...refSelects[1].options].map((option) => option.value)
    expect(firstOptions).toEqual(['cash', 'cac'])
    expect(secondOptions).toEqual(['cash', 'cac', 'runway_months'])
  })

  it('keeps an unknown ref visible and flagged for the backend to reject', () => {
    const draft = draftFromTemplate(customTemplate)
    draft.formulas = [{ output: 'bad', expression: { ref: 'ghost' }, description: '' }]
    render(<Harness initial={draft} />)
    const select = screen.getByLabelText('引用') as HTMLSelectElement
    expect(select.value).toBe('ghost')
    expect(select.selectedOptions[0].text).toContain('不在已知 id 中')
  })

  it('shows out-of-vocabulary expressions read-only without discarding them', () => {
    const draft = draftFromTemplate(customTemplate)
    draft.formulas = [{ output: 'weird', expression: { op: 'power', args: [2, 3] }, description: '' }]
    render(<Harness initial={draft} />)
    expect(screen.getByText(/超出编辑器词汇表/)).toBeInTheDocument()
    expect(screen.getByText('{"op":"power","args":[2,3]}')).toBeInTheDocument()
  })

  it('renders backend validation issues inline', () => {
    render(
      <Harness
        initial={draftFromTemplate(customTemplate)}
        validation={invalidValidationResult}
        saveValidation={null}
      />,
    )
    expect(screen.getByText(/变量表校验（后端）：未通过/)).toBeInTheDocument()
    expect(screen.getByText(/missing_unit/)).toBeInTheDocument()
    expect(screen.getByText(/triangular bounds must satisfy/)).toBeInTheDocument()
  })

  it('renders a passing validation result', () => {
    render(<Harness initial={draftFromTemplate(customTemplate)} validation={validValidationResult} />)
    expect(screen.getByText(/变量表校验（后端）：通过/)).toBeInTheDocument()
  })

  it('renders save errors and save validation together', () => {
    render(
      <Harness
        initial={draftFromTemplate(customTemplate)}
        saveValidation={invalidValidationResult}
        saveError="API 400: variable_validation_failed"
      />,
    )
    expect(screen.getByText(/保存被拒（后端）：未通过/)).toBeInTheDocument()
    expect(screen.getByText('API 400: variable_validation_failed')).toBeInTheDocument()
  })
})

describe('ValidationIssuesView', () => {
  it('lists checks with pass/fail status', () => {
    render(<ValidationIssuesView result={invalidValidationResult} title="校验" />)
    expect(screen.getByText(/PASS · variable_set_nonempty/)).toBeInTheDocument()
    expect(screen.getByText(/FAIL · variables_valid/)).toBeInTheDocument()
  })
})

describe('TemplateReadView', () => {
  it('renders built-in content read-only with no inputs', () => {
    render(<TemplateReadView template={builtinTemplate} fit={null} />)
    expect(screen.getByText(/Built-in corporate preset/)).toBeInTheDocument()
    expect(screen.getAllByText('cash').length).toBeGreaterThan(0)
    expect(screen.getByText('是（只读）')).toBeInTheDocument()
    expect(document.querySelector('input')).toBeNull()
    expect(document.querySelector('select')).toBeNull()
    expect(document.querySelector('textarea')).toBeNull()
  })

  it('renders calibrated provenance from the fit record', () => {
    render(<TemplateReadView template={calibratedTemplate} fit={calibrationFits[0]} />)
    expect(screen.getByText(/校准来源/)).toBeInTheDocument()
    expect(screen.getByText('fit-1')).toBeInTheDocument()
    expect(screen.getByText('builtin:corporate')).toBeInTheDocument()
    expect(screen.getByText(/alert 50 → 86/)).toBeInTheDocument()
    expect(screen.getByText(/critical 25 → 52.5/)).toBeInTheDocument()
    expect(screen.getByText(/源模板未被修改/)).toBeInTheDocument()
  })
})
