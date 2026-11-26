// Variable-template editor page: list templates (built-ins read-only,
// calibrated versions flagged with their fit provenance), view built-in
// detail, and create/edit custom templates. Duplicate prefills a create
// form from a template's full stored content (the list response already
// carries it, including built-in synthesized presets).

import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  calibrationApi,
  parseApiError,
  parseValidationResult,
  variablesApi,
} from '../api/engine'
import type {
  CalibrationFitRead,
  VariableTemplateRead,
  VariableValidationResult,
} from '../api/engineTypes'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import { formatNumber } from '../components/cockpit/format'
import { TemplateForm, TemplateReadView } from '../components/cockpit/TemplateEditor'
import {
  draftFromTemplate,
  draftKey,
  draftToCreate,
  draftToUpdate,
  draftToVariableSet,
  emptyDraft,
} from '../components/cockpit/templateDraft'
import type { TemplateDraft } from '../components/cockpit/templateDraft'
import { Card, CardBody, CardHeader } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorBanner } from '../components/ui/ErrorBanner'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { StatusBadge } from '../components/ui/StatusBadge'
import { domainLabel } from '../components/ui/dataSurfaceUtils'
import { useApi } from '../hooks/useApi'

/** 内置预设名 → 中文显示名；自定义模板用后端返回的名字。 */
const BUILTIN_PRESET_NAMES: Record<string, string> = {
  'builtin:automotive': '内置汽车预设',
  'builtin:corporate': '内置企业预设',
}

function displayTemplateName(template: VariableTemplateRead): string {
  return BUILTIN_PRESET_NAMES[template.id] ?? template.name
}

type Mode =
  | { kind: 'none' }
  | { kind: 'view'; templateId: string }
  | { kind: 'edit'; templateId: string }
  | { kind: 'create' }

function isCalibratedFit(fit: CalibrationFitRead): fit is CalibrationFitRead & { calibrated_template_id: string } {
  return fit.kind === 'policy_thresholds' && fit.calibrated_template_id !== null
}

export default function VariableTemplates() {
  const { data: templates, loading, error, reload } = useApi(() =>
    variablesApi.listTemplates(),
  )
  const [fits, setFits] = useState<CalibrationFitRead[]>([])
  const [fitsNote, setFitsNote] = useState<string | null>(null)
  const [mode, setMode] = useState<Mode>({ kind: 'none' })
  const [draft, setDraft] = useState<TemplateDraft | null>(null)
  const [baseline, setBaseline] = useState<string>('')
  const [validation, setValidation] = useState<VariableValidationResult | null>(null)
  const [validating, setValidating] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveValidation, setSaveValidation] = useState<VariableValidationResult | null>(null)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    calibrationApi
      .listFits({ limit: 100 })
      .then((fits) => setFits(fits))
      .catch((error: unknown) => {
        setFits([])
        setFitsNote(`校准记录未能加载（${parseApiError(error).message}），校准旗标暂不可用；模板列表不受影响。`)
      })
  }, [])

  const fitByTemplate = useMemo(() => {
    const map = new Map<string, CalibrationFitRead>()
    for (const fit of fits) {
      if (isCalibratedFit(fit)) map.set(fit.calibrated_template_id, fit)
    }
    return map
  }, [fits])

  const domains = useMemo(() => {
    const seen = new Set<string>()
    for (const template of templates ?? []) seen.add(template.domain_id)
    return [...seen].sort()
  }, [templates])

  const selected = useMemo(() => {
    if (mode.kind !== 'view' && mode.kind !== 'edit') return null
    return (templates ?? []).find((template) => template.id === mode.templateId) ?? null
  }, [mode, templates])

  const dirty = draft !== null && (mode.kind === 'edit' || mode.kind === 'create') && draftKey(draft) !== baseline

  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const guardUnsaved = useCallback(
    (next: () => void) => {
      if (dirty && !window.confirm('有未保存的更改，离开将丢失。确定要离开吗？')) return
      next()
    },
    [dirty],
  )

  const openTemplate = useCallback(
    (template: VariableTemplateRead) => {
      guardUnsaved(() => {
        setNotice(null)
        setValidation(null)
        setSaveError(null)
        setSaveValidation(null)
        setConfirmingDeleteId(null)
        setDeleteError(null)
        if (template.is_builtin) {
          setMode({ kind: 'view', templateId: template.id })
          setDraft(null)
        } else {
          const next = draftFromTemplate(template)
          setDraft(next)
          setBaseline(draftKey(next))
          setMode({ kind: 'edit', templateId: template.id })
        }
      })
    },
    [guardUnsaved],
  )

  const startCreate = useCallback(
    (seed?: VariableTemplateRead) => {
      guardUnsaved(() => {
        setNotice(null)
        setValidation(null)
        setSaveError(null)
        setSaveValidation(null)
        setConfirmingDeleteId(null)
        setDeleteError(null)
        const next = seed
          ? { ...draftFromTemplate(seed), name: `${displayTemplateName(seed)}（副本）` }
          : emptyDraft(domains[0] ?? 'corporate')
        setDraft(next)
        setBaseline(draftKey(next))
        setMode({ kind: 'create' })
      })
    },
    [guardUnsaved, domains],
  )

  const handleValidate = useCallback(async () => {
    if (!draft) return
    setValidating(true)
    setValidation(null)
    try {
      const result = await variablesApi.validate(draftToVariableSet(draft))
      setValidation(result)
    } catch (error: unknown) {
      setValidation(null)
      setSaveError(parseApiError(error).message)
    } finally {
      setValidating(false)
    }
  }, [draft])

  const handleSave = useCallback(async () => {
    if (!draft) return
    setSaving(true)
    setSaveError(null)
    setSaveValidation(null)
    try {
      if (mode.kind === 'create') {
        const created = await variablesApi.createTemplate(draftToCreate(draft))
        reload()
        const next = draftFromTemplate(created)
        setDraft(next)
        setBaseline(draftKey(next))
        setMode({ kind: 'edit', templateId: created.id })
        setNotice(`已保存模板「${created.name}」。`)
      } else if (mode.kind === 'edit') {
        const updated = await variablesApi.updateTemplate(mode.templateId, draftToUpdate(draft))
        reload()
        const next = draftFromTemplate(updated)
        setDraft(next)
        setBaseline(draftKey(next))
        setNotice(`已保存模板「${updated.name}」。`)
      }
    } catch (error: unknown) {
      const restored = parseValidationResult(error)
      setSaveValidation(restored)
      setSaveError(parseApiError(error).message)
    } finally {
      setSaving(false)
    }
  }, [draft, mode, reload])

  // Deletion is a two-step inline confirmation (no window.confirm): the
  // first click arms the row, the second executes. The list is never
  // updated optimistically — it reloads only after the backend answers.
  // Deleting the template open in the editor goes through the same
  // unsaved-changes guard as leaving the form; deleting any other
  // template never touches the draft. A 404 means the list was stale,
  // so the list reloads to the truth and the error still shows.
  const handleDelete = useCallback(
    async (template: VariableTemplateRead) => {
      const execute = async () => {
        setDeleting(true)
        setDeleteError(null)
        try {
          await variablesApi.deleteTemplate(template.id)
          reload()
          if (mode.kind === 'edit' && mode.templateId === template.id) {
            setMode({ kind: 'none' })
            setDraft(null)
            setBaseline('')
            setValidation(null)
            setSaveError(null)
            setSaveValidation(null)
          }
          setNotice(`已删除模板「${template.name}」。已有推演带有该模板的快照，不受影响。`)
        } catch (error: unknown) {
          const info = parseApiError(error)
          setDeleteError(info.code ? `${info.code}：${info.message}` : info.message)
          if (info.status === 404) reload()
        } finally {
          setDeleting(false)
          setConfirmingDeleteId(null)
        }
      }
      if (mode.kind === 'edit' && mode.templateId === template.id) {
        guardUnsaved(() => {
          void execute()
        })
      } else {
        await execute()
      }
    },
    [guardUnsaved, mode, reload],
  )

  return (
    <div className="space-y-6">
      <CockpitNav />
      <div>
        <h2 className="text-2xl font-bold text-slate-100">变量模板</h2>
        <p className="mt-1 text-sm text-slate-400">
          模板承载状态默认值、策略阈值、变量表与公式图。内置预设只读，可复制后编辑；校准生成的版本由拟合记录溯源。校验以
          后端为准：保存前可校验变量表，保存时服务端的问题会原样 inline 显示。
        </p>
      </div>

      {fitsNote && <p className="text-xs text-amber-300">{fitsNote}</p>}
      {notice && (
        <div role="status" className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2">
          <p className="text-sm text-emerald-300">{notice}</p>
        </div>
      )}

      <Card>
        <CardHeader
          title="模板列表"
          action={
            <button
              onClick={() => startCreate()}
              className="rounded-lg bg-blue-500 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-blue-600"
            >
              + 新建模板
            </button>
          }
        />
        <CardBody>
          {loading && <LoadingSpinner />}
          {error && <ErrorBanner message={error} onRetry={reload} />}
          {deleteError && <ErrorBanner message={deleteError} />}
          {templates && templates.length === 0 && (
            <EmptyState title="暂无模板" description="内置预设未返回——后端可能未正确注册领域包。" />
          )}
          {templates && templates.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
                  <th className="py-2 pr-3 font-medium">名称</th>
                  <th className="py-2 pr-3 font-medium">领域</th>
                  <th className="py-2 pr-3 font-medium">变量</th>
                  <th className="py-2 pr-3 font-medium">公式</th>
                  <th className="py-2 pr-3 font-medium">标识</th>
                  <th className="py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {templates.map((template) => {
                  const fit = fitByTemplate.get(template.id)
                  const isSelected =
                    (mode.kind === 'view' || mode.kind === 'edit') && mode.templateId === template.id
                  return (
                    <tr key={template.id} className={isSelected ? 'bg-slate-800/30' : undefined}>
                      <td className="py-2 pr-3">
                        <span className="font-medium text-slate-200">{displayTemplateName(template)}</span>
                      </td>
                      <td className="py-2 pr-3 text-xs">{domainLabel(template.domain_id) || '默认'}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{formatNumber(template.variables.length)}</td>
                      <td className="py-2 pr-3 font-mono text-xs">{formatNumber(template.formulas.length)}</td>
                      <td className="py-2 pr-3">
                        <span className="flex flex-wrap gap-1.5">
                          {template.is_builtin && <StatusBadge status="内置 · 只读" />}
                          {fit && <StatusBadge status="已校准" />}
                        </span>
                      </td>
                      <td className="py-2">
                        {confirmingDeleteId === template.id ? (
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="text-xs text-amber-300">确认删除「{template.name}」？</span>
                            <button
                              onClick={() => void handleDelete(template)}
                              disabled={deleting}
                              className="rounded-lg bg-red-500 px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-red-600 disabled:opacity-50"
                            >
                              {deleting ? '删除中…' : '确认删除'}
                            </button>
                            <button
                              onClick={() => setConfirmingDeleteId(null)}
                              disabled={deleting}
                              className="text-xs text-slate-400 hover:text-slate-300 disabled:opacity-50"
                            >
                              取消
                            </button>
                          </span>
                        ) : (
                          <span className="flex flex-wrap gap-2">
                            <button
                              onClick={() => openTemplate(template)}
                              className="text-xs text-blue-400 hover:text-blue-300"
                            >
                              {template.is_builtin ? '查看' : '编辑'}
                            </button>
                            <button
                              onClick={() => startCreate(template)}
                              className="text-xs text-blue-400 hover:text-blue-300"
                            >
                              复制为新模板
                            </button>
                            {!template.is_builtin && (
                              <button
                                onClick={() => {
                                  setDeleteError(null)
                                  setConfirmingDeleteId(template.id)
                                }}
                                className="text-xs text-red-400 hover:text-red-300"
                              >
                                删除
                              </button>
                            )}
                          </span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              </table>
            </div>
          )}
        </CardBody>
      </Card>

      {mode.kind === 'view' && selected && (
        <Card>
          <CardHeader
            title={`模板详情：${displayTemplateName(selected)}`}
            action={
              <button
                onClick={() => startCreate(selected)}
                className="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-1.5 text-xs font-medium text-blue-400 transition-colors hover:bg-blue-500/20"
              >
                内置、只读——复制后编辑
              </button>
            }
          />
          <CardBody>
            <p className="mb-4 text-xs leading-5 text-amber-300">
              该模板为内置预设，由领域包代码合成，只读。点「复制后编辑」可新建一个内容相同的自定义模板。
            </p>
            <TemplateReadView template={selected} fit={fitByTemplate.get(selected.id) ?? null} />
          </CardBody>
        </Card>
      )}

      {(mode.kind === 'edit' || mode.kind === 'create') && draft && (
        <Card>
          <CardHeader
            title={mode.kind === 'create' ? '新建模板' : `编辑模板：${draft.name}`}
            action={
              dirty ? (
                <span className="text-xs text-amber-300">有未保存的更改</span>
              ) : (
                <span className="text-xs text-slate-500">无未保存更改</span>
              )
            }
          />
          <CardBody>
            {mode.kind === 'edit' && fitByTemplate.get(mode.templateId) && (
              <p className="mb-4 rounded-lg border border-violet-500/20 bg-violet-500/5 px-3 py-2 text-xs leading-5 text-slate-300">
                该版本由校准拟合生成（拟合记录 {fitByTemplate.get(mode.templateId)?.id}）。编辑保存后，拟合记录仍指向编辑前的版本内容；如需重新校准，请重新拟合生成新版本。
              </p>
            )}
            <TemplateForm
              draft={draft}
              onChange={setDraft}
              domains={domains}
              domainLocked={mode.kind === 'edit'}
              validation={validation}
              onValidate={handleValidate}
              validating={validating}
              saveError={saveError}
              saveValidation={saveValidation}
              onSave={handleSave}
              saving={saving}
              saveLabel={mode.kind === 'create' ? '创建模板' : '保存模板'}
              dirty={dirty}
            />
          </CardBody>
        </Card>
      )}

      {mode.kind === 'none' && (
        <EmptyState title="未选中模板" description="在列表中点「查看」或「编辑」，或点「新建模板」创建一个自定义模板。" />
      )}
    </div>
  )
}
