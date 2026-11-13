// Static copy of the Sprint 6 skill-template inventory.
//
// The backend registry has deliberately NO read endpoint (SPRINT6.md
// §7): stage records carry template id + version, and the cockpit
// ships the inventory from the report. This data was copied from
// `list_templates()` output on the sprint6-skills branch — id, title,
// source repo, source file, license note, and version are verbatim.
// If a template version ever changes, this file must be updated with
// it; the provenance test pins all 17 ids.

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
    title: 'Intake + classify (Steps 0-1)',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Steps 0-1) + Framework index',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.diagnose',
    version: '1',
    title: 'Wave A — diagnose (situation assessment)',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/01-diagnosis-and-framing/situation-assessment.md',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.market_map',
    version: '1',
    title: 'Wave A — map the market (market mapping + competitive intel)',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/02-market-and-competitive-intelligence/market-mapping.md + competitive-intel.md',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.option_generate',
    version: '1',
    title: 'Wave B — generate options from one mandate',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Step 5) + references/03-strategic-choice-and-economics/strategic-options.md',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.filter_shortlist',
    version: '1',
    title: 'Wave B — filter: dedupe, score, shortlist (lead)',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Step 5, lead filter)',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.synthesize',
    version: '1',
    title: 'Synthesize the draft recommendation (Pyramid / SCQA)',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Step 6) + references/06-alignment-and-executive-communication/narrative-builder.md',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.verify_assumptions',
    version: '1',
    title: 'Verifier panel — assumption audit',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/01-diagnosis-and-framing/assumption-audit.md',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.verify_wargame',
    version: '1',
    title: 'Verifier panel — war game',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/05-risk-performance-and-value-governance/war-gaming.md',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.verify_execution',
    version: '1',
    title: 'Verifier panel — execution + economics',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'references/04-operating-model-and-execution/operating-model-design.md + references/05-risk-performance-and-value-governance/risk-and-mitigation.md',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mckinsey.tournament_judge',
    version: '1',
    title: 'Deep mode — pairwise tournament judging',
    pipeline: 'strategy_team',
    sourceRepo: 'mckinsey-strategy-team (github.com, Joost de Leij)',
    sourceFile: 'SKILL.md (Step 7, deep mode tournament)',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'advisory.crit_intake',
    version: '1',
    title: 'CRIT intake (Context, Role, Interview, Task)',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (CRIT Intake)',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'advisory.lens_position',
    version: '1',
    title: 'Round 1 — independent lens position',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (Five Lenses + Round 1)',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'advisory.lens_revision',
    version: '1',
    title: 'Round 3 — revision and ratification',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (Round 3)',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'advisory.forced_debate',
    version: '1',
    title: 'Round 2 — forced debate',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (Round 2 + anti-groupthink rule)',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'advisory.chair_synthesis',
    version: '1',
    title: 'Chair synthesis — decision contract',
    pipeline: 'advisory_board',
    sourceRepo: '5-persona-advisory-board (MIT)',
    sourceFile: 'SKILL.md (Decision Logic + Decision Contract)',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'gambit.premortem',
    version: '1',
    title: 'Pre-mortem — prospective hindsight',
    pipeline: 'strategy_team',
    sourceRepo: 'gambit (github.com/skyf0xx/gambit)',
    sourceFile: 'skills/premortem/SKILL.md',
    licenseNote: 'MIT — adapted with attribution; see source LICENSE.',
  },
  {
    id: 'mece.propose_tree',
    version: '1',
    title: 'MECE authoring aid — propose a decomposition tree',
    pipeline: 'shared',
    sourceRepo: 'flingjie/strategic-issue-tree',
    sourceFile: 'SKILL.md (Phases 1-2) + templates/issue_tree.md',
    licenseNote: 'No license declared in the source repo — workflow structure adapted, wording is original; no source text copied.',
  },
]

export function findTemplate(templateId: string): SkillTemplateInfo | undefined {
  return SKILL_TEMPLATES.find((template) => template.id === templateId)
}
