// Static copy of the Sprint 6 skill-template inventory.
//
// The backend registry has deliberately NO read endpoint (SPRINT6.md
// §7): stage records carry template id + version, and the cockpit
// ships the inventory from the report. This data was copied from
// `list_templates()` output on the sprint6-skills branch — id, source
// repo, source file, and version are verbatim. Titles and license notes
// are Chinese display translations of the upstream English text
// (ids/versions/source files unchanged). If a template version ever
// changes, this file must be updated with it; the provenance test
// pins all 17 ids.

export interface SkillTemplateInfo {
  id: string
  version: string
  title: string
  pipeline: 'strategy_team' | 'advisory_board' | 'shared'
  sourceRepo: string
  sourceFile: string
  licenseNote: string
}

export const SKILL_TEMPLATES: SkillTemplateInfo[] = [
  {
    id: 'mckinsey.intake_classify',
    version: '1',
    title: '接收并分类（第 0–1 步）',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Steps 0-1) + Framework index',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.diagnose',
    version: '1',
    title: '第一波——诊断（形势评估）',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/01-diagnosis-and-framing/situation-assessment.md',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.market_map',
    version: '1',
    title: '第一波——市场摸底（市场描绘与竞争情报）',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/02-market-and-competitive-intelligence/market-mapping.md + competitive-intel.md',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.option_generate',
    version: '1',
    title: '第二波——围绕一项任务生成备选方案',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Step 5) + references/03-strategic-choice-and-economics/strategic-options.md',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.filter_shortlist',
    version: '1',
    title: '第二波——筛选：去重、打分、入围（主推）',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Step 5, lead filter)',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.synthesize',
    version: '1',
    title: '综合形成建议初稿（金字塔 / SCQA 结构）',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Step 6) + references/06-alignment-and-executive-communication/narrative-builder.md',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.verify_assumptions',
    version: '1',
    title: '验证组——假设审计',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/01-diagnosis-and-framing/assumption-audit.md',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.verify_wargame',
    version: '1',
    title: '验证组——兵棋推演',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/05-risk-performance-and-value-governance/war-gaming.md',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.verify_execution',
    version: '1',
    title: '验证组——执行与经济性',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/04-operating-model-and-execution/operating-model-design.md + references/05-risk-performance-and-value-governance/risk-and-mitigation.md',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mckinsey.tournament_judge',
    version: '1',
    title: '深度模式——两两对决评判',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Step 7, deep mode tournament)',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'advisory.crit_intake',
    version: '1',
    title: 'CRIT 接收（背景、角色、访谈、任务）',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (CRIT Intake)',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'advisory.lens_position',
    version: '1',
    title: '第一轮——各视角独立表态',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (Five Lenses + Round 1)',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'advisory.lens_revision',
    version: '1',
    title: '第三轮——修订与确认',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (Round 3)',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'advisory.forced_debate',
    version: '1',
    title: '第二轮——强制辩论',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (Round 2 + anti-groupthink rule)',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'advisory.chair_synthesis',
    version: '1',
    title: '主席综合——决策契约',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (Decision Logic + Decision Contract)',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'gambit.premortem',
    version: '1',
    title: '事前验尸——前瞻性复盘',
    pipeline: 'strategy_team',
    sourceRepo: 'gambit (github.com/skyf0xx/gambit)',
    sourceFile: 'skills/premortem/SKILL.md',
    licenseNote: 'MIT——改编并署名；见源仓库 LICENSE。',
  },
  {
    id: 'mece.propose_tree',
    version: '1',
    title: 'MECE 编写助手——提议分解树',
    pipeline: 'shared',
    sourceRepo: 'flingjie/strategic-issue-tree',
    sourceFile: 'SKILL.md (Phases 1-2) + templates/issue_tree.md',
    licenseNote: '源仓库未声明许可证——流程结构为改编，措辞为原创，未复制源文本。',
  },
]

export function findTemplate(templateId: string): SkillTemplateInfo | undefined {
  return SKILL_TEMPLATES.find((template) => template.id === templateId)
}
