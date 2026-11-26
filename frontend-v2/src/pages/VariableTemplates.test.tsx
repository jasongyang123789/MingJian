import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  calibrationFits,
  customTemplate,
  invalidValidationResult,
  templateList,
  validValidationResult,
} from '../test/engineFixtures'
import VariableTemplates from './VariableTemplates'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

interface CapturedRequest {
  url: string
  method: string
  body: unknown
}

describe('VariableTemplates', () => {
  let requests: CapturedRequest[]
  let validateResult: unknown
  let saveStatus: number
  let saveBody: unknown
  let liveTemplates: typeof templateList
  let deleteStatus: number
  let deleteBody: unknown

  beforeEach(() => {
    vi.restoreAllMocks()
    requests = []
    validateResult = validValidationResult
    saveStatus = 200
    saveBody = null
    liveTemplates = [...templateList]
    deleteStatus = 204
    deleteBody = null
    vi.spyOn(window, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      let body: unknown = null
      if (typeof init?.body === 'string') {
        try {
          body = JSON.parse(init.body)
        } catch {
          body = init.body
        }
      }
      requests.push({ url, method, body })
      if (url === '/api/variable-templates' && method === 'GET') return jsonResponse(liveTemplates)
      if (url.startsWith('/api/calibration/fits')) return jsonResponse(calibrationFits)
      if (url === '/api/variables/validate') return jsonResponse(validateResult)
      if (url === '/api/variable-templates' && method === 'POST') {
        if (saveStatus !== 200) return jsonResponse(saveBody, saveStatus)
        const created = { ...(body as object), id: 'tmpl-new', is_builtin: false, created_at: '2026-11-13T09:00:00Z', updated_at: '2026-11-13T09:00:00Z' }
        return jsonResponse(created)
      }
      if (url.startsWith('/api/variable-templates/') && method === 'PUT') {
        if (saveStatus !== 200) return jsonResponse(saveBody, saveStatus)
        const id = url.split('/').pop()
        const existing = templateList.find((template) => template.id === id) ?? customTemplate
        return jsonResponse({ ...existing, ...(body as object), id })
      }
      if (url.startsWith('/api/variable-templates/') && method === 'DELETE') {
        if (deleteStatus !== 204) {
          // A 404 means another client deleted the template first: the
          // stored list no longer has it, so a reload converges.
          if (deleteStatus === 404) {
            const gone = url.split('/').pop()
            liveTemplates = liveTemplates.filter((template) => template.id !== gone)
          }
          return jsonResponse(deleteBody, deleteStatus)
        }
        const id = url.split('/').pop()
        liveTemplates = liveTemplates.filter((template) => template.id !== id)
        return new Response(null, { status: 204 })
      }
      return jsonResponse({})
    })
  })

  function renderPage() {
    return render(
      <MemoryRouter>
        <VariableTemplates />
      </MemoryRouter>,
    )
  }

  async function waitForList() {
    await waitFor(() => {
      expect(screen.getByText('AI line case')).toBeInTheDocument()
    })
  }

  function rowFor(name: string) {
    const cell = screen.getByText(name)
    const row = cell.closest('tr')
    if (!row) throw new Error(`no row for ${name}`)
    return row
  }

  it('lists templates with built-in and calibrated flags', async () => {
    renderPage()
    await waitForList()
    expect(screen.getAllByText('内置 · 只读')).toHaveLength(2)
    expect(screen.getByText('已校准')).toBeInTheDocument()
    expect(screen.getByText('Corporate (built-in) (calibrated)')).toBeInTheDocument()
  })

  it('shows a built-in template read-only with a duplicate affordance', async () => {
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('内置企业预设')).getByText('查看'))
    await waitFor(() => {
      expect(screen.getByText(/内置预设，由领域包代码合成，只读/)).toBeInTheDocument()
    })
    expect(screen.getByText('内置、只读——复制后编辑')).toBeInTheDocument()
    expect(screen.queryByText('保存模板')).not.toBeInTheDocument()
    expect(screen.queryByText('创建模板')).not.toBeInTheDocument()
  })

  it('duplicates a built-in into a prefilled create form', async () => {
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('内置企业预设')).getByText('复制为新模板'))
    await waitFor(() => {
      expect(screen.getByDisplayValue('内置企业预设（副本）')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('状态字段 1 字段名')).toHaveValue('cash')
    expect(screen.getByLabelText('状态字段 1 默认值')).toHaveValue(100)
    expect(screen.getByLabelText('领域')).toHaveValue('corporate')
    expect(screen.getByText('创建模板')).toBeInTheDocument()
  })

  it('edits a custom template and saves without domain_id in the payload', async () => {
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByLabelText('变量 1 id')).toHaveValue('cash')
    })
    fireEvent.change(screen.getByDisplayValue('AI line case'), { target: { value: 'AI line case v2' } })
    expect(screen.getAllByText('有未保存的更改').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByText('保存模板'))
    await waitFor(() => {
      expect(screen.getByText('已保存模板「AI line case v2」。')).toBeInTheDocument()
    })
    const put = requests.find((request) => request.method === 'PUT')
    expect(put?.url).toBe('/api/variable-templates/tmpl-1')
    expect(put?.body).toMatchObject({ name: 'AI line case v2' })
    expect(put?.body).not.toHaveProperty('domain_id')
  })

  it('surfaces a rejected save with server validation issues inline', async () => {
    saveStatus = 400
    saveBody = {
      detail: {
        code: 'variable_validation_failed',
        message: 'Variable validation failed',
        validation: invalidValidationResult,
      },
    }
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByLabelText('变量 1 id')).toHaveValue('cash')
    })
    fireEvent.click(screen.getByText('保存模板'))
    await waitFor(() => {
      expect(screen.getByText(/保存被拒（后端）：未通过/)).toBeInTheDocument()
    })
    expect(screen.getByText(/missing_unit/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toBeInTheDocument()
    // The form stays open with the draft intact.
    expect(screen.getByLabelText('变量 1 id')).toHaveValue('cash')
  })

  it('runs the pre-save backend check and shows its verdict', async () => {
    validateResult = invalidValidationResult
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByLabelText('变量 1 id')).toHaveValue('cash')
    })
    fireEvent.click(screen.getByText('校验变量表（后端）'))
    await waitFor(() => {
      expect(screen.getByText(/变量表校验（后端）：未通过/)).toBeInTheDocument()
    })
    const post = requests.find((request) => request.url === '/api/variables/validate')
    expect(post?.body).toMatchObject({ name: 'AI line case' })
    expect((post?.body as { variables: unknown[] }).variables).toHaveLength(2)
  })

  it('creates a new template from a blank form', async () => {
    renderPage()
    await waitForList()
    fireEvent.click(screen.getByText('+ 新建模板'))
    await waitFor(() => {
      expect(screen.getByText('创建模板')).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText('模板名称'), { target: { value: 'My template' } })
    fireEvent.click(screen.getByText('创建模板'))
    await waitFor(() => {
      expect(screen.getByText('已保存模板「My template」。')).toBeInTheDocument()
    })
    const post = requests.find((request) => request.method === 'POST' && request.url === '/api/variable-templates')
    expect(post?.body).toMatchObject({ name: 'My template', domain_id: 'corporate' })
  })

  it('asks before discarding unsaved changes', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByLabelText('变量 1 id')).toHaveValue('cash')
    })
    fireEvent.change(screen.getByDisplayValue('AI line case'), { target: { value: 'edited' } })
    fireEvent.click(within(rowFor('Corporate (built-in) (calibrated)')).getByText('编辑'))
    expect(confirm).toHaveBeenCalled()
    // Stayed on the edited draft.
    expect(screen.getByDisplayValue('edited')).toBeInTheDocument()

    confirm.mockReturnValue(true)
    fireEvent.click(within(rowFor('Corporate (built-in) (calibrated)')).getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByText(/该版本由校准拟合生成/)).toBeInTheDocument()
    })
  })

  it('shows the calibration note when editing a calibrated version', async () => {
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('Corporate (built-in) (calibrated)')).getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByText(/该版本由校准拟合生成/)).toBeInTheDocument()
    })
    expect(screen.getByText(/fit-1/)).toBeInTheDocument()
  })

  it('deletes a custom template only after inline confirmation and refreshes the list', async () => {
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('删除'))
    expect(screen.getByText('确认删除「AI line case」？')).toBeInTheDocument()
    expect(requests.some((request) => request.method === 'DELETE')).toBe(false)
    fireEvent.click(screen.getByText('确认删除'))
    await waitFor(() => {
      expect(
        screen.getByText('已删除模板「AI line case」。已有推演带有该模板的快照，不受影响。'),
      ).toBeInTheDocument()
    })
    const deleted = requests.find((request) => request.method === 'DELETE')
    expect(deleted?.url).toBe('/api/variable-templates/tmpl-1')
    expect(deleted?.body).toBeNull()
    await waitFor(() => {
      expect(
        within(screen.getByRole('table')).queryByText('AI line case'),
      ).not.toBeInTheDocument()
    })
  })

  it('cancelling the delete confirmation sends nothing', async () => {
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('删除'))
    fireEvent.click(screen.getByText('取消'))
    expect(requests.some((request) => request.method === 'DELETE')).toBe(false)
    expect(screen.queryByText('确认删除「AI line case」？')).not.toBeInTheDocument()
    expect(within(rowFor('AI line case')).getByText('删除')).toBeInTheDocument()
  })

  it('hides delete for built-in templates', async () => {
    renderPage()
    await waitForList()
    expect(within(rowFor('内置企业预设')).queryByText('删除')).not.toBeInTheDocument()
    expect(requests.some((request) => request.method === 'DELETE')).toBe(false)
  })

  it('surfaces a delete failure honestly and keeps the list', async () => {
    deleteStatus = 400
    deleteBody = { detail: 'Built-in template builtin:corporate is read-only; create a stored template instead.' }
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('删除'))
    fireEvent.click(screen.getByText('确认删除'))
    await waitFor(() => {
      expect(screen.getByText(/Built-in template builtin:corporate is read-only/)).toBeInTheDocument()
    })
    expect(within(rowFor('AI line case')).getByText('删除')).toBeInTheDocument()
    expect(screen.queryByText(/已删除模板/)).not.toBeInTheDocument()
  })

  it('reloads the list when the backend says the template is already gone', async () => {
    deleteStatus = 404
    deleteBody = { detail: 'Variable template tmpl-1 was not found.' }
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('删除'))
    fireEvent.click(screen.getByText('确认删除'))
    await waitFor(() => {
      expect(screen.getByText(/Variable template tmpl-1 was not found/)).toBeInTheDocument()
    })
    // The list re-synced with the backend: the already-gone row is gone.
    await waitFor(() => {
      expect(
        within(screen.getByRole('table')).queryByText('AI line case'),
      ).not.toBeInTheDocument()
    })
  })

  it('asks before discarding a dirty draft when deleting the open template', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByLabelText('变量 1 id')).toHaveValue('cash')
    })
    fireEvent.change(screen.getByDisplayValue('AI line case'), { target: { value: 'edited' } })
    fireEvent.click(within(rowFor('AI line case')).getByText('删除'))
    fireEvent.click(screen.getByText('确认删除'))
    expect(confirm).toHaveBeenCalled()
    expect(requests.some((request) => request.method === 'DELETE')).toBe(false)
    expect(screen.getByDisplayValue('edited')).toBeInTheDocument()

    confirm.mockReturnValue(true)
    fireEvent.click(screen.getByText('确认删除'))
    await waitFor(() => {
      expect(screen.getByText(/已删除模板「AI line case」/)).toBeInTheDocument()
    })
    expect(requests.some((request) => request.method === 'DELETE')).toBe(true)
    // The editor closed with its template.
    expect(screen.getByText('未选中模板')).toBeInTheDocument()
  })

  it('deleting another template leaves a dirty draft untouched', async () => {
    const confirm = vi.spyOn(window, 'confirm')
    renderPage()
    await waitForList()
    fireEvent.click(within(rowFor('AI line case')).getByText('编辑'))
    await waitFor(() => {
      expect(screen.getByLabelText('变量 1 id')).toHaveValue('cash')
    })
    fireEvent.change(screen.getByDisplayValue('AI line case'), { target: { value: 'edited' } })
    fireEvent.click(within(rowFor('Corporate (built-in) (calibrated)')).getByText('删除'))
    fireEvent.click(screen.getByText('确认删除'))
    await waitFor(() => {
      expect(screen.getByText(/已删除模板「Corporate \(built-in\) \(calibrated\)」/)).toBeInTheDocument()
    })
    expect(confirm).not.toHaveBeenCalled()
    expect(screen.getByDisplayValue('edited')).toBeInTheDocument()
  })
})
