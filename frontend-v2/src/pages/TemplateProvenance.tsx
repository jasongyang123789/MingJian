import { Card, CardHeader } from '../components/ui/Card'
import { CockpitNav } from '../components/cockpit/CockpitNav'
import { SKILL_TEMPLATES } from '../data/skillTemplates'

const PIPELINE_LABELS: Record<string, string> = {
  strategy_team: '策略团队',
  advisory_board: '顾问团',
  shared: '共用',
}

export default function TemplateProvenance() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-100">模板出处</h1>
        <p className="mt-1 text-sm text-slate-500">
          Sprint 6 嫁接的 17 个版本化提示词模板：来源仓库、文件与许可证注记
        </p>
      </div>

      <CockpitNav />

      <Card>
        <CardHeader title={`提示词模板清单（${SKILL_TEMPLATES.length} 个，均为 v1）`} />
        <div className="overflow-x-auto px-5 py-4">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wider text-slate-500">
                <th className="py-2 pr-3 font-medium">模板 id</th>
                <th className="py-2 pr-3 font-medium">用途</th>
                <th className="py-2 pr-3 font-medium">管线</th>
                <th className="py-2 pr-3 font-medium">来源文件</th>
                <th className="py-2 font-medium">许可证注记</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {SKILL_TEMPLATES.map((template) => (
                <tr key={template.id}>
                  <td className="py-2 pr-3 font-mono text-xs text-slate-200">
                    {template.id} <span className="text-slate-500">v{template.version}</span>
                  </td>
                  <td className="py-2 pr-3 text-slate-300">{template.title}</td>
                  <td className="py-2 pr-3 text-slate-400">{PIPELINE_LABELS[template.pipeline]}</td>
                  <td className="py-2 pr-3 text-xs leading-5 text-slate-400">
                    <span className="block">{template.sourceRepo}</span>
                    <span className="block font-mono text-[11px] text-slate-500">{template.sourceFile}</span>
                  </td>
                  <td className="py-2 text-xs leading-5 text-slate-400">{template.licenseNote}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-xs leading-5 text-slate-500">
        这份清单是随前端发布的静态数据：后端模板注册表没有设计读取端点（SPRINT6.md
        §7 的有意决定）。每条 deliberation 记录都带有产生它的模板 id
        + 版本，因此界面可以准确显示每段输出是由哪个版本的提示词产生的；模板版本若有变化，需同步更新这份清单。
      </p>
    </div>
  )
}
