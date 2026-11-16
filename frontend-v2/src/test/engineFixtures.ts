// Fixture payloads assembled from the recorded backend outputs in
// tests/fixtures/skill_outputs/ (Sprint 6) plus hand-built Sprint 1–5
// fragments that follow the backend Pydantic shapes exactly. Values
// are copied from the recorded fixtures; aggregates (tally,
// weighted directions, tournament wins) are the values the backend
// code computes from those outputs (see SPRINT6.md §4).

import type {
  AdvisoryBoardResult,
  CalibrationFitRead,
  DecisionGatesRead,
  DecisionNarrativeRead,
  DerivationRead,
  DeterminismRead,
  DirectionMappingRead,
  EnsembleComparison,
  FirewallRead,
  LoopEvaluationRead,
  LoopIterationRead,
  LoopObservationRead,
  LoopTimelineRead,
  MeceRunRead,
  MeceValidationResult,
  MonteCarloResult,
  MonteCarloTrialValues,
  RobustnessRead,
  SkillDeliberationRecord,
  StageRecord,
  StrategyLoopRead,
  StrategyTeamResult,
  ThresholdSearchResult,
  TriggerRegistration,
  VariableRunRead,
  VariableTemplateRead,
  VariableValidationResult,
} from '../api/engineTypes'

function stage(label: string, templateId: string, output: Record<string, unknown>): StageRecord {
  return {
    stage: label,
    template_id: templateId,
    template_version: '1',
    contract_version: '1',
    output,
    model: 'fixture-model',
  }
}

const INTAKE = {
  problem_statement: 'A 20-person SaaS team must decide whether to launch an AI customer-service line within 12 months.',
  decision_question: 'Should we launch the AI customer-service line, and in what form?',
  engagement_type: 'new market',
  audience: 'Founder and leadership team',
  constraints: ['20-person team', '12-month horizon', 'no new funding round'],
  stakes: 'standard',
  frameworks: ['Situation assessment', 'Market mapping', 'Strategic options'],
  wave_plan: ['Wave A: diagnose + market map in parallel', 'Wave B: bull + lean option generators', 'Panel: assumptions, war-game, execution, pre-mortem'],
  open_questions: ['What is the real willingness to pay?'],
} as const

const DIAGNOSIS = {
  findings: [
    'Support tickets grew 40% in two quarters while headcount stayed flat.',
    'Churn among high-touch accounts correlates with slow first response.',
  ],
  assumptions: [
    'Ticket growth continues at the current pace.',
    'The team can staff one launch pod without dropping core roadmap.',
  ],
  barriers: ['No dedicated ML hire; delivery capacity is the binding constraint.'],
  open_questions: ['Can the current stack serve AI replies under the latency budget?'],
}

const MARKET_MAP = {
  summary: 'The AI support market is crowded at the low end and thin at the high-trust end.',
  segments: ['SMB self-serve', 'Mid-market high-touch'],
  competitors: ['Incumbent helpdesk vendors adding AI tiers', 'Two well-funded AI-native entrants'],
  white_space: ['High-trust, auditable AI replies for regulated mid-market accounts'],
  profit_pools: ['Mid-market annual contracts with support SLAs'],
  threats: ['Price undercutting by AI-native entrants within one quarter of launch'],
}

const OPTION_SET_BULL = {
  options: [
    {
      name: 'Full launch',
      description: 'Launch the AI line to all segments at once with a dedicated pod.',
      upside: 'Fastest revenue ramp and market signal.',
      trade_off: 'Strains delivery capacity and risks quality.',
      what_must_be_true: ['Demand grows at least 20% year over year', 'Delivery capacity covers launch volume'],
    },
    {
      name: 'Acquire a small AI vendor',
      description: 'Buy capability instead of building it.',
      upside: 'Instant capability and customer base.',
      trade_off: 'Integration risk and cash outlay.',
      what_must_be_true: ['A suitable target is available at a sane price'],
    },
  ],
}

const OPTION_SET_LEAN = {
  options: [
    {
      name: 'Phased rollout',
      description: 'Launch to ten friendly mid-market accounts, then expand on evidence.',
      upside: 'Limits downside and generates proof before scale.',
      trade_off: 'Slower revenue ramp; rivals may move first.',
      what_must_be_true: ['Ten friendly accounts agree to the pilot', 'Pilot results generalize'],
    },
    {
      name: 'Partner-led',
      description: 'Deliver the AI line through an integration partner.',
      upside: 'No delivery build-out; partner carries scale.',
      trade_off: 'Margin share and less control of the experience.',
      what_must_be_true: ['A partner with the right customer base signs'],
    },
  ],
}

const OPTION_SET_CONTRARIAN = {
  options: [
    {
      name: 'Do nothing, double down on core',
      description: 'Refuse the AI line; invest the pod in core product quality.',
      upside: 'Protects the core and avoids a capacity crunch.',
      trade_off: 'Cedes the AI narrative to rivals.',
      what_must_be_true: ['Core churn is fixable without AI features'],
    },
  ],
}

const SHORTLIST = {
  ranked: [
    {
      name: 'Phased rollout',
      description: 'Launch to ten friendly mid-market accounts, then expand on evidence.',
      scores: { attractiveness: 8, economics: 7, feasibility: 8, risk: 7, strategic_fit: 8 },
      rationale: 'Best risk-adjusted path; generates proof before scale.',
    },
    {
      name: 'Full launch',
      description: 'Launch the AI line to all segments at once with a dedicated pod.',
      scores: { attractiveness: 9, economics: 7, feasibility: 4, risk: 3, strategic_fit: 7 },
      rationale: 'Highest upside, weakest feasibility given delivery capacity.',
    },
    {
      name: 'Partner-led',
      description: 'Deliver the AI line through an integration partner.',
      scores: { attractiveness: 6, economics: 5, feasibility: 7, risk: 6, strategic_fit: 5 },
      rationale: 'Viable fallback; margin and control costs keep it third.',
    },
  ],
  dropped: [
    { name: 'Acquire a small AI vendor', reason: 'Cash outlay breaks the no-new-funding constraint.' },
    { name: 'Do nothing, double down on core', reason: 'Cedes the market the decision is about.' },
  ],
}

const SYNTHESIS = {
  governing_thought: 'Launch in phases: prove the AI line with ten friendly accounts before committing the team.',
  arguments: [
    { claim: 'Demand is real but unpriced', backing: 'Ticket growth and churn correlation in the diagnosis.' },
    { claim: 'Capacity is the binding constraint', backing: 'No ML hire and a flat team; phased scope fits the pod.' },
    { claim: 'Proof before scale de-risks the bet', backing: 'Pilot results generalize or the kill criterion fires.' },
  ],
  recommended_option: 'Phased rollout',
  load_bearing_assumptions: [
    'Demand grows at least 20% year over year',
    'Ten friendly accounts agree to the pilot',
    'Delivery capacity covers launch volume',
  ],
  alternatives_considered: [
    'Full launch: upside real, feasibility too weak',
    'Partner-led: fallback if the pilot stalls',
  ],
}

const ASSUMPTION_AUDIT = {
  assumptions: [
    {
      assumption: 'Demand grows at least 20% year over year',
      category: 'market',
      importance: 5,
      evidence_strength: 'speculative',
      risk: 'If demand is flat, the pilot proves nothing and the ramp never comes.',
    },
    {
      assumption: 'Ten friendly accounts agree to the pilot',
      category: 'commercial',
      importance: 4,
      evidence_strength: 'weak',
      risk: 'Recruitment slip delays all learning.',
    },
  ],
  load_bearing: ['Demand grows at least 20% year over year'],
  tests: ['Pre-sell the pilot to ten accounts before building anything.'],
  fatal_flags: ['Demand growth assumption is untested'],
}

const WARGAME_ROUND_1 = {
  scenarios: [
    { name: 'Base: steady adoption', trigger: 'Pilot accounts convert on schedule', impact: 'Revenue ramp in month 7', likelihood: 'medium', severity: 'low' },
    { name: 'Adverse: rival undercuts', trigger: 'AI-native entrant drops price 40%', impact: 'Pilot accounts demand matching terms', likelihood: 'medium', severity: 'high' },
  ],
  vulnerabilities: [
    { weak_point: 'Demand growth assumption is untested', why_it_matters: 'The whole ramp rests on it.', mitigation: 'Pre-sell before building.' },
    { weak_point: 'Rival undercuts price within one quarter', why_it_matters: 'Price war destroys the pilot economics.', mitigation: 'Differentiate on auditability, not price.' },
  ],
  playbook: [{ signal: 'Rival announces price cut', response: 'Shift pitch to auditability and SLA terms', owner: 'Founder' }],
  fatal_flags: ['Demand growth assumption is untested', 'Rival undercuts price within one quarter'],
}

const WARGAME_ROUND_2 = {
  scenarios: [
    { name: 'Base: steady adoption', trigger: 'Pilot accounts convert on schedule', impact: 'Revenue ramp in month 7', likelihood: 'medium', severity: 'low' },
  ],
  vulnerabilities: [
    { weak_point: 'Demand growth assumption is untested', why_it_matters: 'Still the load-bearing unknown.', mitigation: 'Pre-sell before building.' },
  ],
  playbook: [],
  fatal_flags: ['Demand growth assumption is untested'],
}

const WARGAME_ROUND_3 = {
  scenarios: [
    { name: 'Base: steady adoption', trigger: 'Pilot accounts convert on schedule', impact: 'Revenue ramp in month 7', likelihood: 'medium', severity: 'low' },
  ],
  vulnerabilities: [],
  playbook: [],
  fatal_flags: [],
}

const EXECUTION_REVIEW = {
  feasibility: 'Executable only at phased scope; full launch exceeds delivery capacity.',
  risks: [
    { risk: 'Delivery capacity cannot cover launch volume', mitigation: 'Cap the pilot at ten accounts and staff one pod.', owner: 'Head of engineering' },
    { risk: 'Latency budget missed under load', mitigation: 'Load-test before the pilot expands.', owner: 'Head of engineering' },
  ],
  economics_survive_bad_case: 'Phased scope survives a flat-demand case; full launch does not.',
  fatal_flags: ['Delivery capacity cannot cover launch volume'],
}

const PREMORTEM = {
  failure_narrative: 'One year later the AI line is shut down: the pilot slipped two quarters, the pod burned out, and two friendly accounts churned.',
  failure_modes: [
    { mode: 'Delivery capacity cannot cover launch volume', cause: 'One pod, no ML hire, and scope creep from pilot accounts.', early_signal: 'Pilot tickets exceed pod throughput in week three.', prevention: 'Hard cap on pilot scope and a kill criterion at week six.' },
    { mode: 'Pilot accounts never convert', cause: 'Willingness to pay was assumed, never tested.', early_signal: 'No pre-sold commitments before build.', prevention: 'Pre-sell ten commitments before building.' },
  ],
  fatal_flags: ['Delivery capacity cannot cover launch volume'],
}

// Tally computed by the backend rule: a flag is must_address when ≥2
// DISTINCT lenses flag the same normalized statement as fatal.
const TALLY = {
  flags: [
    { flag: 'Demand growth assumption is untested', lenses: ['assumptions', 'wargame'], lens_count: 2, must_address: true },
    { flag: 'Delivery capacity cannot cover launch volume', lenses: ['execution', 'premortem'], lens_count: 2, must_address: true },
    { flag: 'Rival undercuts price within one quarter', lenses: ['wargame'], lens_count: 1, must_address: false },
  ],
  must_address: ['Demand growth assumption is untested', 'Delivery capacity cannot cover launch volume'],
}

const STANDARD_STAGES: StageRecord[] = [
  stage('intake', 'mckinsey.intake_classify', { ...INTAKE }),
  stage('diagnose', 'mckinsey.diagnose', DIAGNOSIS),
  stage('market_map', 'mckinsey.market_map', MARKET_MAP),
  stage('option_generate:bull', 'mckinsey.option_generate', OPTION_SET_BULL),
  stage('option_generate:lean', 'mckinsey.option_generate', OPTION_SET_LEAN),
  stage('filter_shortlist', 'mckinsey.filter_shortlist', SHORTLIST),
  stage('synthesize', 'mckinsey.synthesize', SYNTHESIS),
  stage('verify:assumptions', 'mckinsey.verify_assumptions', ASSUMPTION_AUDIT),
  stage('verify:wargame:round1', 'mckinsey.verify_wargame', WARGAME_ROUND_1),
  stage('verify:execution', 'mckinsey.verify_execution', EXECUTION_REVIEW),
  stage('verify:premortem', 'gambit.premortem', PREMORTEM),
]

export const strategyTeamResult: StrategyTeamResult = {
  pipeline: 'strategy_team',
  mode: 'standard',
  topic: 'Should we launch the AI customer-service line?',
  stages: STANDARD_STAGES,
  intake: {
    ...INTAKE,
    stakes: 'standard',
    constraints: [...INTAKE.constraints],
    frameworks: [...INTAKE.frameworks],
    wave_plan: [...INTAKE.wave_plan],
    open_questions: [...INTAKE.open_questions],
  },
  diagnosis: DIAGNOSIS,
  market_map: MARKET_MAP,
  option_sets: [OPTION_SET_BULL, OPTION_SET_LEAN],
  shortlist: SHORTLIST,
  synthesis: SYNTHESIS,
  synthesis_recommendation_in_shortlist: true,
  panel: {
    assumptions: { ...ASSUMPTION_AUDIT, assumptions: ASSUMPTION_AUDIT.assumptions.map((a) => ({ ...a, evidence_strength: a.evidence_strength as 'speculative' | 'weak' })) },
    wargame: WARGAME_ROUND_1,
    execution: EXECUTION_REVIEW,
    premortem: PREMORTEM,
  },
  wargame_rounds: [WARGAME_ROUND_1],
  tally: TALLY,
  tournament: null,
  wargame_loop_rounds: 0,
  wargame_loop_stop_reason: 'not_deep',
}

export const strategyTeamDeepResult: StrategyTeamResult = {
  ...strategyTeamResult,
  mode: 'deep',
  stages: [
    ...STANDARD_STAGES.slice(0, 5),
    stage('option_generate:contrarian', 'mckinsey.option_generate', OPTION_SET_CONTRARIAN),
    ...STANDARD_STAGES.slice(5, 9),
    stage('verify:wargame:round2', 'mckinsey.verify_wargame', WARGAME_ROUND_2),
    stage('verify:wargame:round3', 'mckinsey.verify_wargame', WARGAME_ROUND_3),
    ...STANDARD_STAGES.slice(9),
    stage('tournament:Phased rollout-vs-Full launch', 'mckinsey.tournament_judge', { winner: 'Phased rollout', loser: 'Full launch', rationale: 'Feasibility and risk dominate; upside alone does not carry Full launch.', criteria_scores: { attractiveness: 8, economics: 7, feasibility: 8, risk: 7, strategic_fit: 8 } }),
    stage('tournament:Phased rollout-vs-Partner-led', 'mckinsey.tournament_judge', { winner: 'Phased rollout', loser: 'Partner-led', rationale: 'Control of the experience and economics favor the phased path.', criteria_scores: { attractiveness: 8, economics: 7, feasibility: 8, risk: 7, strategic_fit: 8 } }),
    stage('tournament:Full launch-vs-Partner-led', 'mckinsey.tournament_judge', { winner: 'Full launch', loser: 'Partner-led', rationale: 'Upside beats the margin-and-control costs of the partner path.', criteria_scores: { attractiveness: 9, economics: 7, feasibility: 4, risk: 3, strategic_fit: 7 } }),
  ],
  option_sets: [OPTION_SET_BULL, OPTION_SET_LEAN, OPTION_SET_CONTRARIAN],
  panel: { ...strategyTeamResult.panel, wargame: WARGAME_ROUND_3 },
  wargame_rounds: [WARGAME_ROUND_1, WARGAME_ROUND_2, WARGAME_ROUND_3],
  tournament: {
    matches: [
      { option_a: 'Phased rollout', option_b: 'Full launch', winner: 'Phased rollout', rationale: 'Feasibility and risk dominate; upside alone does not carry Full launch.' },
      { option_a: 'Phased rollout', option_b: 'Partner-led', winner: 'Phased rollout', rationale: 'Control of the experience and economics favor the phased path.' },
      { option_a: 'Full launch', option_b: 'Partner-led', winner: 'Full launch', rationale: 'Upside beats the margin-and-control costs of the partner path.' },
    ],
    wins: { 'Phased rollout': 2, 'Full launch': 1, 'Partner-led': 0 },
    winner: 'Phased rollout',
  },
  wargame_loop_rounds: 2,
  wargame_loop_stop_reason: 'two_quiet_rounds',
}

export const strategyTeamRecord: SkillDeliberationRecord = {
  id: 'delib-st-1',
  run_id: 'run-1',
  pipeline: 'strategy_team',
  mode: 'standard',
  created_at: '2026-11-13T08:00:00Z',
  result: strategyTeamResult,
}

export const strategyTeamDeepRecord: SkillDeliberationRecord = {
  id: 'delib-st-2',
  run_id: 'run-1',
  pipeline: 'strategy_team',
  mode: 'deep',
  created_at: '2026-11-13T08:30:00Z',
  result: strategyTeamDeepResult,
}

// --- Advisory board ---------------------------------------------------------

const CRIT_INTAKE = {
  decision: 'Should we launch the AI customer-service line, and in what form?',
  options: ['Phased rollout', 'Full launch', 'Partner-led'],
  context: 'A 20-person SaaS team deciding whether to launch an AI customer-service line.',
  evidence: 'Known: ticket growth and churn correlation. Unknown: willingness to pay.',
  economics: 'Pilot costs one pod for a quarter; full launch doubles burn.',
  constraints: ['20-person team', '12-month horizon', 'no new funding round'],
  success: 'Ten pilot accounts live in 90 days with churn flat or better.',
  current_preference: 'Phased rollout',
  reversibility: 'The pilot is reversible; a full launch creates lasting hiring commitments.',
  assumptions: ['Pilot results generalize to the wider mid-market.'],
  questions: ['Which ten accounts would pre-commit to the pilot?'],
}

const POSITIONS = [
  {
    lens: 'product_clarity',
    option_scores: { 'Full launch': 5, 'Partner-led': 6, 'Phased rollout': 8 },
    confidence: 'high',
    decisive_evidence: 'Ticket growth with flat headcount makes the pain concrete.',
    primary_upside: 'A focused pilot proves the story before scale.',
    primary_failure_mode: 'Scope creep turns the pilot into a second product.',
    opening_recommendation: 'Phased rollout',
    risk_veto: null,
  },
  {
    lens: 'risk_capital',
    option_scores: { 'Full launch': 4, 'Partner-led': 6, 'Phased rollout': 7 },
    confidence: 'medium',
    decisive_evidence: 'No ML hire and a flat team; capacity is the constraint.',
    primary_upside: 'Phased spend keeps the downside bounded.',
    primary_failure_mode: 'A slipped launch burns the runway before revenue arrives.',
    opening_recommendation: 'Phased rollout',
    risk_veto: {
      failure_path: 'Cash runway collapses if launch slips two quarters',
      evidence: 'Cash covers 9 months; a two-quarter slip plus hiring leaves under 3 months.',
      severity: 'ruin-risk: runway below 3 months',
      mitigation: 'Cap pilot spend and pre-sell ten commitments before building.',
    },
  },
  {
    lens: 'scale_systems',
    option_scores: { 'Full launch': 7, 'Partner-led': 5, 'Phased rollout': 6 },
    confidence: 'medium',
    decisive_evidence: 'The stack can serve pilot volume but not launch volume.',
    primary_upside: 'Full launch forces the mechanism to exist.',
    primary_failure_mode: 'Pilot learnings never transfer because the mechanism is not built.',
    opening_recommendation: 'Full launch',
    risk_veto: null,
  },
  {
    lens: 'offer_strength',
    option_scores: { 'Full launch': 6, 'Partner-led': 7, 'Phased rollout': 8 },
    confidence: 'high',
    decisive_evidence: 'Friendly accounts already ask for faster first response.',
    primary_upside: 'A pilot offer with a clear result sells itself to friendly accounts.',
    primary_failure_mode: 'The offer is pitched on features instead of time-to-result.',
    opening_recommendation: 'Phased rollout',
    risk_veto: null,
  },
  {
    lens: 'future_self',
    option_scores: { 'Full launch': 6, 'Partner-led': 8, 'Phased rollout': 7 },
    confidence: 'medium',
    decisive_evidence: "The founder's stated goal is durable independence, not a fast exit.",
    primary_upside: 'A partner carries scale while the team keeps its freedom.',
    primary_failure_mode: 'Chasing the AI narrative distracts from the durable core.',
    opening_recommendation: 'Partner-led',
    risk_veto: null,
  },
] as const

const REVISIONS = [
  {
    lens: 'product_clarity',
    final_option: 'Phased rollout',
    revised_scores: { 'Full launch': 5, 'Partner-led': 6, 'Phased rollout': 8 },
    confidence: 'high',
    what_changed: 'Nothing material; the debate strengthened the pilot-first case.',
    required_conditions: ['Pilot scope capped at ten accounts'],
    kill_criterion: 'Fewer than six of ten pilot accounts convert by week twelve.',
    unresolved_objection: 'None.',
  },
  {
    lens: 'risk_capital',
    final_option: 'Phased rollout',
    revised_scores: { 'Full launch': 4, 'Partner-led': 7, 'Phased rollout': 7 },
    confidence: 'medium',
    what_changed: 'Partner-led rose on downside protection, but phased still wins on control.',
    required_conditions: ['Pre-sell ten commitments before building', 'Monthly runway review'],
    kill_criterion: 'Runway projection below 6 months at any monthly review.',
    unresolved_objection: 'The runway veto stands until commitments are pre-sold.',
  },
  {
    lens: 'scale_systems',
    final_option: 'Phased rollout',
    revised_scores: { 'Full launch': 7, 'Partner-led': 5, 'Phased rollout': 7 },
    confidence: 'medium',
    what_changed: 'Moved from Full launch to Phased rollout: the mechanism can be built at pilot scope.',
    required_conditions: ['Build the mechanism at pilot scope first'],
    kill_criterion: 'Pilot latency above budget for two consecutive weeks.',
    unresolved_objection: 'None.',
  },
  {
    lens: 'offer_strength',
    final_option: 'Phased rollout',
    revised_scores: { 'Full launch': 6, 'Partner-led': 7, 'Phased rollout': 8 },
    confidence: 'high',
    what_changed: 'Nothing material; the pilot offer case held.',
    required_conditions: ['Offer framed on time-to-result, not features'],
    kill_criterion: 'No pre-sold commitments within 30 days.',
    unresolved_objection: 'None.',
  },
  {
    lens: 'future_self',
    final_option: 'Partner-led',
    revised_scores: { 'Full launch': 5, 'Partner-led': 8, 'Phased rollout': 7 },
    confidence: 'medium',
    what_changed: 'Nothing material; still prefers Partner-led, accepts the pilot as a bounded test.',
    required_conditions: ['Pilot stays capped; any expansion is a new decision'],
    kill_criterion: 'Pilot scope grows beyond ten accounts without a new decision.',
    unresolved_objection: 'Independence: the pilot must not quietly become a full launch.',
  },
] as const

const FORCED_DEBATE = {
  disagreements: [
    {
      trade_off: 'Speed of mechanism vs cost of being wrong.',
      case_a: 'Full launch forces the delivery mechanism to exist now.',
      case_b: 'Forcing the mechanism before proof is how the runway dies.',
      rebuttals: ['The mechanism can be built at pilot scope and reused.', 'A forced build without demand evidence is the expensive path.'],
      settling_evidence: 'Whether ten accounts pre-commit.',
      cheapest_test: 'Pre-sell ten pilot commitments in 30 days.',
    },
    {
      trade_off: 'Partner scale vs independence and margin.',
      case_a: 'A partner carries scale without hiring.',
      case_b: 'Margin share and lost control compound over years.',
      rebuttals: ['Control matters only if the line is core to the story.', "Independence is the founder's stated goal."],
      settling_evidence: 'The partner term sheet and its renewal terms.',
      cheapest_test: 'Price the partner term sheet against pilot economics.',
    },
  ],
  minority_objection: 'The future-self lens still prefers Partner-led on independence grounds; the pilot must not quietly become a full launch.',
}

const DECISION_CONTRACT = {
  verdict: 'validate_first',
  why_now: 'Demand pain is concrete and the pilot is cheap and reversible; waiting cedes the narrative.',
  conditions: ['Pre-sell ten commitments before building', 'Cap pilot scope at ten accounts', 'Monthly runway review'],
  minority_report: "The future-self lens prefers Partner-led on independence grounds; the pilot is accepted only as a bounded test.",
  cheapest_validation_test: 'Pre-sell ten pilot commitments in 30 days.',
  go_threshold: 'At least six of ten pilot accounts convert by week twelve.',
  kill_criterion: 'Fewer than six conversions, or runway projection below 6 months.',
  owner: 'Founder',
  deadline: '30 days to pre-sell; 90 days to pilot live',
  review_date: '30 days from now',
  next_action: 'Founder calls the ten friendly accounts this week.',
  do_not_do: 'Do not hire ahead of pilot evidence; do not let the pilot quietly become a full launch.',
  lens_weights: { future_self: 1, offer_strength: 2, product_clarity: 3, risk_capital: 3, scale_systems: 2 },
  assumptions: ['Pilot results generalize to the wider mid-market.', 'Ten friendly accounts will pre-commit.'],
} as const

const VETOES = [
  {
    lens: 'risk_capital',
    failure_path: 'Cash runway collapses if launch slips two quarters',
    evidence: 'Cash covers 9 months; a two-quarter slip plus hiring leaves under 3 months.',
    severity: 'ruin-risk: runway below 3 months',
    mitigation: 'Cap pilot spend and pre-sell ten commitments before building.',
  },
]

const ADVISORY_STAGES: StageRecord[] = [
  stage('crit_intake', 'advisory.crit_intake', { ...CRIT_INTAKE }),
  ...POSITIONS.map((position) =>
    stage(`lens_position:${position.lens}`, 'advisory.lens_position', { ...position }),
  ),
  stage('forced_debate', 'advisory.forced_debate', FORCED_DEBATE),
  ...REVISIONS.map((revision) =>
    stage(`lens_revision:${revision.lens}`, 'advisory.lens_revision', { ...revision }),
  ),
  stage('chair_synthesis', 'advisory.chair_synthesis', { ...DECISION_CONTRACT }),
]

export const advisoryBoardResult: AdvisoryBoardResult = {
  pipeline: 'advisory_board',
  mode: 'standard',
  decision: 'Should we launch the AI customer-service line, and in what form?',
  stages: ADVISORY_STAGES,
  intake: CRIT_INTAKE,
  positions: POSITIONS.map((p) => ({ ...p, confidence: p.confidence as 'low' | 'medium' | 'high' })),
  debate: FORCED_DEBATE,
  revisions: REVISIONS.map((r) => ({
    ...r,
    confidence: r.confidence as 'low' | 'medium' | 'high',
    revised_scores: { ...r.revised_scores },
    required_conditions: [...r.required_conditions],
  })),
  contract: {
    ...DECISION_CONTRACT,
    verdict: 'validate_first',
    conditions: [...DECISION_CONTRACT.conditions],
    lens_weights: { ...DECISION_CONTRACT.lens_weights },
    assumptions: [...DECISION_CONTRACT.assumptions],
  },
  weighted_direction_round1: {
    scores: { 'Phased rollout': 7.2, 'Partner-led': 6.4, 'Full launch': 5.6 },
    weights: { product_clarity: 2, risk_capital: 2, scale_systems: 2, offer_strength: 2, future_self: 2 },
    ranking: ['Phased rollout', 'Partner-led', 'Full launch'],
    top_option: 'Phased rollout',
  },
  weighted_direction_final: {
    scores: { 'Phased rollout': 82 / 11, 'Partner-led': 71 / 11, 'Full launch': 58 / 11 },
    weights: { future_self: 1, offer_strength: 2, product_clarity: 3, risk_capital: 3, scale_systems: 2 },
    ranking: ['Phased rollout', 'Partner-led', 'Full launch'],
    top_option: 'Phased rollout',
  },
  vetoes: VETOES,
  has_unmitigated_veto: false,
  unanimous_option: null,
}

export const advisoryBoardRecord: SkillDeliberationRecord = {
  id: 'delib-ab-1',
  run_id: 'run-1',
  pipeline: 'advisory_board',
  mode: 'standard',
  created_at: '2026-11-13T09:00:00Z',
  result: advisoryBoardResult,
}

/** Same run, chair verdict `choose`: the recorded veto is unmitigated. */
export const advisoryBoardVetoRecord: SkillDeliberationRecord = {
  id: 'delib-ab-2',
  run_id: 'run-1',
  pipeline: 'advisory_board',
  mode: 'standard',
  created_at: '2026-11-13T09:30:00Z',
  result: {
    ...advisoryBoardResult,
    contract: { ...advisoryBoardResult.contract, verdict: 'choose' },
    has_unmitigated_veto: true,
  },
}

// --- Sprint 1–5 fragments ---------------------------------------------------

export const meceRunRead: MeceRunRead = {
  run_id: 'run-1',
  decomposition: {
    topic: 'Should we launch the AI customer-service line?',
    root: {
      name: 'Launch decision',
      scope: ['demand', 'capability', 'economics'],
      children: [
        { name: 'Demand', scope: ['demand'], children: [] },
        { name: 'Capability', scope: ['capability'], children: [] },
        { name: 'Economics', scope: ['economics'], children: [] },
      ],
    },
  },
  validation: {
    is_mece: true,
    checks: [
      { node: 'Launch decision', check: 'mutual_exclusion', status: 'PASS', detail: 'Sibling scopes are disjoint.' },
      { node: 'Launch decision', check: 'exhaustiveness', status: 'PASS', detail: 'Child scopes cover the parent scope exactly.' },
    ],
    issues: [],
    scope_tag_count: 3,
    branch_count: 4,
  },
}

export const meceInvalidValidation: MeceValidationResult = {
  is_mece: false,
  checks: [
    { node: 'Launch decision', check: 'mutual_exclusion', status: 'FAIL', detail: "Scope tag 'capability' appears in more than one sibling branch." },
    { node: 'Launch decision', check: 'exhaustiveness', status: 'PASS', detail: 'Child scopes cover the parent scope exactly.' },
  ],
  issues: [
    { kind: 'overlap', node: 'Launch decision', detail: "Scope tag 'capability' is covered by multiple sibling branches.", tags: ['capability'], branches: ['Demand and capability', 'Capability and economics'] },
  ],
  scope_tag_count: 3,
  branch_count: 3,
}

export const variableRunRead: VariableRunRead = {
  run_id: 'run-1',
  template: {
    id: 'builtin:corporate',
    name: 'Corporate (built-in)',
    domain_id: 'corporate',
    description: 'Built-in corporate preset synthesized from the domain pack.',
    state_fields: [
      { name: 'cash', description: 'Cash on hand', default: 100 },
      { name: 'pipeline', description: 'Sales pipeline', default: 50 },
    ],
    policies: { cash: { preferred_direction: 'increase', alert_threshold: 50, critical_threshold: 25 } },
    variables: [],
    formulas: [],
    internal: {},
    is_builtin: true,
  },
  bindings: {
    name: 'AI line case',
    variables: [
      {
        id: 'cash',
        unit: 'k USD',
        distribution: { type: 'triangular', value: null, mean: null, std: null, min: 60, mode: 100, max: 140, p: null },
        evidence_ref: 'estimate: founder',
        description: 'Cash at decision time',
        scope_tags: ['economics'],
      },
      {
        id: 'cac',
        unit: 'USD/customer',
        distribution: { type: 'triangular', value: null, mean: null, std: null, min: 8000, mode: 12000, max: 20000, p: null },
        evidence_ref: 'crm:q3-actuals',
        description: 'Customer acquisition cost',
        scope_tags: ['economics'],
      },
    ],
    formulas: [
      { output: 'runway_months', expression: { op: 'divide', args: [{ ref: 'cash' }, 12] }, description: 'Cash divided by monthly burn' },
    ],
    internal: { runway: '9 months of cash', team: '20 people, no ML hire' },
  },
  validation: { is_valid: true, variable_count: 2, checks: [], issues: [] },
}

export const monteCarloResult: MonteCarloResult = {
  ensemble_id: 'ens-1',
  base_run_id: 'run-1',
  trials: 50,
  seed: 42,
  metric: 'cash',
  loss_threshold: 90,
  strategy_levers: { cash: 140 },
  baseline: { n: 50, mean: 99.39, min: 62.1, max: 138.2, p10: 79.4, p50: 98.9, p90: 118.4, stddev: 15.7, p_loss: 0.3 },
  strategy: { n: 50, mean: 140, min: 140, max: 140, p10: 140, p50: 140, p90: 140, stddev: 0, p_loss: 0 },
  paired: { n: 50, mean_delta: 40.61, p10: 1.8, p50: 41.1, p90: 77.9, p_strategy_better: 1 },
  trial_run_ids: { baseline: ['t-b-1'], strategy: ['t-s-1'] },
  protocol: 'paired-seed-v1',
}

export const determinismRead: DeterminismRead = {
  run_id: 'run-1',
  seed: 42,
  protocol: 'canonical-json-v1',
  input_hash: 'sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
  state_hashes: { '0': 'sha256:aaaa', '1': 'sha256:bbbb', '2': 'sha256:cccc' },
  sampled_values: { cash: 98.9, cac: 12000 },
  sampled_applied: ['cash'],
  derived_values: { runway_months: 8.24 },
  derived_applied: [],
}

export const robustnessRead: RobustnessRead = {
  run_id: 'run-1',
  ensemble_id: 'ens-1',
  expected_shortfall: {
    run_id: 'run-1',
    ensemble_id: 'ens-1',
    metric: 'cash',
    alpha: 0.05,
    tail: 'lower',
    baseline: { value: 74.23, threshold: 76.1, tail_count: 2, n: 50 },
    strategy: { value: 140, threshold: 140, tail_count: 2, n: 50 },
    paired: { value: 3.2, threshold: 4.1, tail_count: 2, n: 50 },
    trial_values_hash: 'sha256:eeee',
    protocol: 'robustness-v1',
  },
  tornado: {
    run_id: 'run-1',
    ensemble_id: 'ens-1',
    metric: 'cash',
    seed: 42,
    low_quantile: 0.1,
    high_quantile: 0.9,
    base_run_id: 'run-1',
    rows: [
      { variable: 'cash', low_value: 68, high_value: 132, base_value: 100, outcome_low: 68, outcome_high: 132, outcome_base: 100, swing: 64 },
      { variable: 'cac', low_value: 9000, high_value: 18000, base_value: 12000, outcome_low: 100, outcome_high: 100, outcome_base: 100, swing: 0 },
    ],
    probe_run_ids: ['p-1', 'p-2'],
    protocol: 'robustness-v1',
  },
  threshold_search: {
    run_id: 'run-1',
    ensemble_id: 'ens-1',
    metric: 'cash',
    variable: 'cash',
    mode: 'p_loss',
    target: 0.3,
    direction: 'increasing',
    bounds: [60, 140],
    threshold: null,
    achieved_statistic: null,
    reachable: false,
    iterations: 8,
    evaluations: [{ value: 100, statistic: 0.5, trials: 20, probe_run_ids: ['p-3'] }],
    trials_per_evaluation: 20,
    tolerance: 0.001,
    loss_threshold: 90,
    seed: 42,
    protocol: 'robustness-v1',
  },
  bootstrap: {
    run_id: 'run-1',
    ensemble_id: 'ens-1',
    metric: 'cash',
    loss_threshold: 90,
    baseline: [
      { statistic: 'mean', estimate: 99.39, low: 95.3, high: 103.52, draws: 1000, seed: 42, level: 0.9, method: 'percentile' },
      { statistic: 'p_loss', estimate: 0.3, low: 0.18, high: 0.44, draws: 1000, seed: 42, level: 0.9, method: 'percentile' },
    ],
    strategy: [
      { statistic: 'mean', estimate: 140, low: 140, high: 140, draws: 1000, seed: 42, level: 0.9, method: 'percentile' },
    ],
    trial_values_hash: 'sha256:eeee',
    protocol: 'robustness-v1',
  },
}

export const decisionGatesRead: DecisionGatesRead = {
  run_id: 'run-1',
  registrations: [
    {
      id: 'reg-1',
      run_id: 'run-1',
      ensemble_id: null,
      gates: [{ name: 'p50-above-zero', metric: 'p50', operator: '>=', threshold: 0, arm: 'baseline', alpha: 0.05 }],
      supersedes: null,
      registered_at: '2026-11-13T07:00:00Z',
      ensemble_existed_at_registration: false,
      status: 'active',
    },
  ],
  evaluations: [
    {
      id: 'eval-1',
      registration_id: 'reg-1',
      run_id: 'run-1',
      ensemble_id: 'ens-1',
      evaluated_at: '2026-11-13T07:30:00Z',
      outcomes: [{ name: 'p50-above-zero', metric: 'p50', operator: '>=', threshold: 0, arm: 'baseline', alpha: null, observed: 98.9, passed: true }],
      all_passed: true,
      pre_registered: true,
    },
  ],
}

export const firewallRead: FirewallRead = {
  run_id: 'run-1',
  decision_time: '2026-03-01T00:00:00Z',
  cutoff_source: 'explicit',
  firewall_active: true,
  included_claim_ids: ['claim-early-1', 'claim-early-2'],
  excluded_claim_ids: ['claim-late-1', 'claim-late-2'],
  stored_evidence_ids: ['ev-1', 'ev-2'],
}

export const calibrationFits: CalibrationFitRead[] = [
  {
    id: 'fit-1',
    kind: 'policy_thresholds',
    domain_id: 'corporate',
    source_template_id: 'builtin:corporate',
    calibrated_template_id: 'tmpl-cal-1',
    metric: null,
    ridge_strength: 1,
    seed: 7,
    bootstrap_draws: 1000,
    level: 0.95,
    source_run_ids: ['run-1', 'run-2'],
    n_observations: 4,
    changes: {
      metrics: {
        cash: {
          metric: 'cash',
          preferred_direction: 'increase',
          prior_alert_threshold: 50,
          fitted_alert_threshold: 86,
          prior_critical_threshold: 25,
          fitted_critical_threshold: 52.5,
          alert_bootstrap: null,
          critical_bootstrap: null,
          n_observations: 4,
          n_tail: 1,
          unchanged_reason: null,
          rejected_fit: null,
        },
      },
    },
    inputs_hash: 'sha256:ffff',
    loo_rmse: null,
    application: {},
    created_at: '2026-11-13T08:00:00Z',
  },
  {
    id: 'fit-2',
    kind: 'rule_weights',
    domain_id: 'corporate',
    source_template_id: null,
    calibrated_template_id: null,
    metric: 'cash',
    ridge_strength: 5,
    seed: 7,
    bootstrap_draws: 1000,
    level: 0.95,
    source_run_ids: ['run-1', 'run-2', 'run-3'],
    n_observations: 3,
    changes: {
      rules: {
        'corp.cost_pressure': { rule_id: 'corp.cost_pressure', prior_weight: 1, fitted_weight: 2, bootstrap: {}, total_matches: 5 },
      },
      association_note: 'Fitted weights are an association signal between rule match counts and the target metric, not a causal estimate of rule effects.',
    },
    inputs_hash: 'sha256:gggg',
    loo_rmse: 45.31,
    application: {},
    created_at: '2026-11-13T08:15:00Z',
  },
]

// ---------------------------------------------------------------------------
// Sprint 8 fixtures: variable templates + monte-carlo trial values.
// ---------------------------------------------------------------------------

export const builtinTemplate: VariableTemplateRead = {
  id: 'builtin:corporate',
  name: 'Corporate (built-in)',
  domain_id: 'corporate',
  description: 'Built-in corporate preset synthesized from the domain pack.',
  state_fields: [
    { name: 'cash', description: 'Cash on hand', default: 100 },
    { name: 'pipeline', description: 'Sales pipeline', default: 50 },
  ],
  policies: {
    cash: { preferred_direction: 'increase', alert_threshold: 50, critical_threshold: 25 },
  },
  variables: [],
  formulas: [],
  internal: {},
  is_builtin: true,
  created_at: null,
  updated_at: null,
}

export const builtinMilitaryTemplate: VariableTemplateRead = {
  id: 'builtin:military',
  name: 'Military (built-in)',
  domain_id: 'military',
  description: 'Built-in military preset synthesized from the domain pack.',
  state_fields: [{ name: 'readiness', description: 'Force readiness', default: 80 }],
  policies: {
    readiness: { preferred_direction: 'increase', alert_threshold: 60, critical_threshold: 40 },
  },
  variables: [],
  formulas: [],
  internal: {},
  is_builtin: true,
  created_at: null,
  updated_at: null,
}

export const customTemplate: VariableTemplateRead = {
  id: 'tmpl-1',
  name: 'AI line case',
  domain_id: 'corporate',
  description: 'Custom template for the AI customer-service line case.',
  state_fields: [
    { name: 'cash', description: 'Cash on hand', default: 100 },
    { name: 'pipeline', description: 'Sales pipeline', default: 50 },
  ],
  policies: {
    cash: { preferred_direction: 'increase', alert_threshold: 50, critical_threshold: 25 },
  },
  variables: [
    {
      id: 'cash',
      unit: 'k USD',
      distribution: { type: 'triangular', value: null, mean: null, std: null, min: 60, mode: 100, max: 140, p: null },
      evidence_ref: 'estimate: founder',
      description: 'Cash at decision time',
      scope_tags: ['economics'],
    },
    {
      id: 'cac',
      unit: 'USD/customer',
      distribution: { type: 'triangular', value: null, mean: null, std: null, min: 8000, mode: 12000, max: 20000, p: null },
      evidence_ref: 'crm:q3-actuals',
      description: 'Customer acquisition cost',
      scope_tags: ['economics'],
    },
  ],
  formulas: [
    { output: 'runway_months', expression: { op: 'divide', args: [{ ref: 'cash' }, 12] }, description: 'Cash divided by monthly burn' },
  ],
  internal: { runway: '9 months of cash', team: '20 people, no ML hire' },
  is_builtin: false,
  created_at: '2026-11-13T06:00:00Z',
  updated_at: '2026-11-13T06:00:00Z',
}

export const calibratedTemplate: VariableTemplateRead = {
  id: 'tmpl-cal-1',
  name: 'Corporate (built-in) (calibrated)',
  domain_id: 'corporate',
  description: 'Calibrated from template builtin:corporate by ridge-to-prior fit (ridge_strength=1, seed=7) over 4 run(s). Source description: Built-in corporate preset synthesized from the domain pack.',
  state_fields: [
    { name: 'cash', description: 'Cash on hand', default: 100 },
    { name: 'pipeline', description: 'Sales pipeline', default: 50 },
  ],
  policies: {
    cash: { preferred_direction: 'increase', alert_threshold: 86, critical_threshold: 52.5 },
  },
  variables: [],
  formulas: [],
  internal: {},
  is_builtin: false,
  created_at: '2026-11-13T08:15:00Z',
  updated_at: '2026-11-13T08:15:00Z',
}

export const templateList: VariableTemplateRead[] = [
  builtinTemplate,
  builtinMilitaryTemplate,
  customTemplate,
  calibratedTemplate,
]

export const invalidValidationResult: VariableValidationResult = {
  is_valid: false,
  variable_count: 1,
  checks: [
    { check: 'variable_set_nonempty', status: 'pass', variable: '', detail: '' },
    { check: 'variables_valid', status: 'fail', variable: '', detail: '2 issue(s)' },
  ],
  issues: [
    { kind: 'missing_unit', variable: 'cac', message: 'Variable "cac" is missing a unit.' },
    { kind: 'invalid_bounds', variable: 'cac', message: 'triangular bounds must satisfy min <= mode <= max.' },
  ],
}

export const validValidationResult: VariableValidationResult = {
  is_valid: true,
  variable_count: 2,
  checks: [
    { check: 'variable_set_nonempty', status: 'pass', variable: '', detail: '' },
    { check: 'variables_valid', status: 'pass', variable: '', detail: '' },
  ],
  issues: [],
}

export const trialValues: MonteCarloTrialValues = {
  ensemble_id: 'ens-1',
  base_run_id: 'run-1',
  metric: 'cash',
  loss_threshold: 90,
  baseline: [79.4, 98.9, 118.4, 92.0, 105.5],
  strategy: [140, 140, 140, 140, 140],
  trial_values_hash: 'sha256:aaaa',
  protocol: 'sprint3-v1',
}

export const reachableThresholdSearch: ThresholdSearchResult = {
  ...(robustnessRead.threshold_search as ThresholdSearchResult),
  threshold: 105,
  achieved_statistic: 0.29,
  reachable: true,
  iterations: 6,
  evaluations: [
    { value: 60, statistic: 0.9, trials: 20, probe_run_ids: ['p-1'] },
    { value: 80, statistic: 0.6, trials: 20, probe_run_ids: ['p-2'] },
    { value: 100, statistic: 0.35, trials: 20, probe_run_ids: ['p-3'] },
    { value: 110, statistic: 0.25, trials: 20, probe_run_ids: ['p-4'] },
    { value: 105, statistic: 0.29, trials: 20, probe_run_ids: ['p-5'] },
  ],
}

export const robustnessReadReachable: RobustnessRead = {
  ...robustnessRead,
  threshold_search: reachableThresholdSearch,
}

// ---------------------------------------------------------------------------
// Sprint 9 — living-strategy loop fixtures
// ---------------------------------------------------------------------------
//
// Values mirror the verified backend walkthrough (tests/test_loops_api.py):
// cash observations 95/65/60 in the window, all three triggers firing,
// identical ensembles (same bindings, same seed, no new evidence), so
// every delta is exactly 0. The fixture proves the display, not a
// forecast.

export const loopRegistration: TriggerRegistration = {
  id: 'registration-1',
  loop_id: 'loop-1',
  triggers: [
    { kind: 'threshold', name: 'cash-floor', field: 'cash', operator: '<', threshold: 70 },
    {
      kind: 'gate',
      name: 'cash-mean',
      field: 'cash',
      gate: { name: 'cash-mean-gate', metric: 'mean', operator: '<', threshold: 90, arm: 'baseline', alpha: 0.05 },
      loss_threshold: null,
    },
    {
      kind: 'deviation',
      name: 'cash-drift',
      field: 'cash',
      tolerance: 20,
      consecutive: 2,
      reference_value: 100,
    },
  ],
  supersedes: null,
  registered_at: '2026-01-02T00:00:00Z',
  observation_count_at_registration: 0,
  status: 'active',
}

export const loopRead: StrategyLoopRead = {
  id: 'loop-1',
  name: 'AI 客服线',
  baseline_run_id: 'run-baseline',
  domain_id: 'corporate',
  status: 'active',
  triggers: [loopRegistration],
  created_at: '2026-01-02T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
}

export const loopObservations: LoopObservationRead[] = [
  {
    id: 'obs-1',
    loop_id: 'loop-1',
    field: 'cash',
    value: 95,
    observed_at: '2026-01-10T00:00:00Z',
    source_claim_id: null,
    source_note: '月度结算',
    recorded_at: '2026-01-11T00:00:00Z',
  },
  {
    id: 'obs-2',
    loop_id: 'loop-1',
    field: 'cash',
    value: 65,
    observed_at: '2026-01-20T00:00:00Z',
    source_claim_id: null,
    source_note: null,
    recorded_at: '2026-01-21T00:00:00Z',
  },
  {
    id: 'obs-3',
    loop_id: 'loop-1',
    field: 'cash',
    value: 60,
    observed_at: '2026-01-25T00:00:00Z',
    source_claim_id: null,
    source_note: null,
    recorded_at: '2026-01-26T00:00:00Z',
  },
]

export const loopComparison: EnsembleComparison = {
  baseline_run_id: 'run-baseline',
  baseline_ensemble_id: 'ensemble-old',
  new_run_id: 'run-resim',
  new_ensemble_id: 'ensemble-new',
  metric: 'cash',
  loss_threshold: 90,
  baseline_arm: {
    arm: 'baseline',
    old: { n: 10, mean: 100, min: 62, max: 138, p10: 70, p50: 100, p90: 130, stddev: 22, p_loss: 0.3 },
    new: { n: 10, mean: 100, min: 62, max: 138, p10: 70, p50: 100, p90: 130, stddev: 22, p_loss: 0.3 },
    delta_p10: 0,
    delta_p50: 0,
    delta_p90: 0,
    delta_mean: 0,
    delta_p_loss: 0,
  },
  strategy_arm: {
    arm: 'strategy',
    old: { n: 10, mean: 140, min: 140, max: 140, p10: 140, p50: 140, p90: 140, stddev: 0, p_loss: 0 },
    new: { n: 10, mean: 140, min: 140, max: 140, p10: 140, p50: 140, p90: 140, stddev: 0, p_loss: 0 },
    delta_p10: 0,
    delta_p50: 0,
    delta_p90: 0,
    delta_mean: 0,
    delta_p_loss: 0,
  },
  paired_mean_delta_old: 40,
  paired_mean_delta_new: 40,
  paired_mean_delta_change: 0,
  paired_p_strategy_better_old: 1,
  paired_p_strategy_better_new: 1,
  paired_p_strategy_better_change: 0,
  same_seed: true,
  same_trials: true,
  seeds_paired: true,
  evidence_caveat:
    'The two ensembles ran under different evidence cutoffs: the re-simulation saw claims ingested after the baseline decision time. Identical seeds pair the sampling draws, but they do not make this a pure sampling comparison — outcome differences may come from the evidence, not the draws.',
  gate_reevaluation: null,
  threshold_drift: [],
  compared_at: '2026-02-01T01:00:00Z',
}

export const loopIterationDecided: LoopIterationRead = {
  id: 'iteration-1',
  loop_id: 'loop-1',
  index: 0,
  state: 'decided',
  decision_time: '2026-02-01T00:00:00Z',
  previous_cutoff: '2026-01-01T00:00:00Z',
  window_from: '2026-01-01T00:00:00Z',
  window_to: '2026-02-01T00:00:00Z',
  observation_ids: ['obs-1', 'obs-2', 'obs-3'],
  trigger_evaluations: [
    {
      name: 'cash-floor',
      kind: 'threshold',
      field: 'cash',
      fired: true,
      status: 'fired',
      observed_value: 60,
      threshold: 70,
      tolerance: null,
      reference_value: null,
      consecutive_breaches: null,
      observation_ids: ['obs-1', 'obs-2', 'obs-3'],
      observed_values: [95, 65, 60],
      note: 'Latest observed cash 60 breached threshold 70.',
    },
    {
      name: 'cash-mean',
      kind: 'gate',
      field: 'cash',
      fired: true,
      status: 'fired',
      observed_value: 73.3333,
      threshold: 90,
      tolerance: null,
      reference_value: null,
      consecutive_breaches: null,
      observation_ids: ['obs-1', 'obs-2', 'obs-3'],
      observed_values: [95, 65, 60],
      note: 'Gate statistic mean 73.3333 breached threshold 90.',
    },
    {
      name: 'cash-drift',
      kind: 'deviation',
      field: 'cash',
      fired: true,
      status: 'fired',
      observed_value: 40,
      threshold: null,
      tolerance: 20,
      reference_value: 100,
      consecutive_breaches: 2,
      observation_ids: ['obs-1', 'obs-2', 'obs-3'],
      observed_values: [95, 65, 60],
      note: '2 consecutive observations deviated from 100 by more than 20.',
    },
  ],
  resimulation: {
    run_id: 'run-resim',
    previous_cutoff: '2026-01-01T00:00:00Z',
    new_cutoff: '2026-02-01T00:00:00Z',
    previous_input_hash: 'sha256:aaaa1111',
    new_input_hash: 'sha256:bbbb2222',
    template_id: null,
    template_snapshot_hash: null,
    resolved_template_snapshot_hash: null,
    seed: 7,
    tick_count: 2,
    changes: {},
    claims_visible: 0,
    claims_excluded: 0,
    created_at: '2026-02-01T00:30:00Z',
  },
  comparison: loopComparison,
  decision: {
    decision: 'continue',
    rationale: '分布未变，继续执行。',
    decided_at: '2026-02-01T02:00:00Z',
  },
  created_at: '2026-02-01T00:00:00Z',
  updated_at: '2026-02-01T02:00:00Z',
}

export const loopIterationOpen: LoopIterationRead = {
  id: 'iteration-open',
  loop_id: 'loop-1',
  index: 1,
  state: 'open',
  decision_time: '2026-03-01T00:00:00Z',
  previous_cutoff: '2026-02-01T00:00:00Z',
  window_from: null,
  window_to: null,
  observation_ids: [],
  trigger_evaluations: [],
  resimulation: null,
  comparison: null,
  decision: null,
  created_at: '2026-03-01T00:00:00Z',
  updated_at: '2026-03-01T00:00:00Z',
}

export const loopIterationEvaluated: LoopIterationRead = {
  ...loopIterationDecided,
  id: 'iteration-evaluated',
  index: 1,
  state: 'evaluated',
  decision_time: '2026-03-01T00:00:00Z',
  previous_cutoff: '2026-02-01T00:00:00Z',
  window_from: '2026-02-01T00:00:00Z',
  window_to: '2026-03-01T00:00:00Z',
  resimulation: null,
  comparison: null,
  decision: null,
}

export const loopTimeline: LoopTimelineRead = {
  loop: loopRead,
  observations: loopObservations,
  iterations: [loopIterationDecided],
}

export const loopEvaluationFired: LoopEvaluationRead = {
  id: 'evaluation-1',
  loop_id: 'loop-1',
  cycle_id: 'cycle-1',
  evaluated_at: '2026-02-05T00:00:00Z',
  observation_fingerprint: 'sha256:0123456789abcdef',
  registration_id: 'registration-1',
  observation_ids: ['obs-1', 'obs-2', 'obs-3'],
  outcomes: loopIterationDecided.trigger_evaluations,
  summary: 'fired',
  error_code: null,
  error_message: null,
  created_at: '2026-02-05T00:00:00Z',
}

export const loopEvaluationError: LoopEvaluationRead = {
  id: 'evaluation-2',
  loop_id: 'loop-1',
  cycle_id: 'cycle-2',
  evaluated_at: '2026-02-02T00:00:00Z',
  observation_fingerprint: 'sha256:fedcba9876543210',
  registration_id: 'registration-1',
  observation_ids: ['obs-1'],
  outcomes: [],
  summary: 'error',
  error_code: 'loop_trigger_evaluation_failed',
  error_message: "Deviation trigger 'cash-drift' has no reference value for field 'cash'.",
  created_at: '2026-02-02T00:00:00Z',
}

export const loopEvaluationQuiet: LoopEvaluationRead = {
  id: 'evaluation-3',
  loop_id: 'loop-1',
  cycle_id: 'cycle-3',
  evaluated_at: '2026-02-03T00:00:00Z',
  observation_fingerprint: 'sha256:abcdef0123456789',
  registration_id: 'registration-1',
  observation_ids: ['obs-1'],
  outcomes: [
    {
      name: 'cash-floor',
      kind: 'threshold',
      field: 'cash',
      fired: false,
      status: 'quiet',
      observed_value: 95,
      threshold: 70,
      tolerance: null,
      reference_value: null,
      consecutive_breaches: null,
      observation_ids: ['obs-1'],
      observed_values: [95],
      note: 'Latest observed cash 95 did not breach threshold 70.',
    },
  ],
  summary: 'quiet',
  error_code: null,
  error_message: null,
  created_at: '2026-02-03T00:00:00Z',
}


// ---------------------------------------------------------------------------
// Sprint 13 — decision-direction narrative
// ---------------------------------------------------------------------------

export const narrativeRead: DecisionNarrativeRead = {
  id: 'narrative-1',
  run_id: 'run-anchor',
  version: 2,
  topic: 'Launch decision',
  inputs_hash: 'sha256:inputs0000000000000000000000000000000000000000000000000000',
  content_hash: 'sha256:content000000000000000000000000000000000000000000000000000',
  created_at: '2026-11-15T10:00:00Z',
  direction_mapping_ids: [],
  body: {
    protocol: 'sprint13-v1',
    anchor_run_id: 'run-anchor',
    domain_id: 'corporate',
    topic: 'Launch decision',
    topic_source: 'request',
    mece: {
      provenance: 'computed',
      topic: 'Should we launch?',
      is_mece: true,
      branch_count: 3,
      scope_tag_count: 2,
      issue_count: 0,
    },
    calibration_context: [
      {
        fit_id: 'fit-1',
        kind: 'policy',
        loo_rmse: 11.5,
        inputs_hash: 'sha256:fit',
        calibrated_template_id: 'tpl-2',
        n_observations: 8,
        created_at: '2026-11-14T00:00:00Z',
      },
    ],
    loop_context: {
      provenance: 'computed',
      loop_id: 'loop-1',
      loop_name: 'Watch',
      registration_id: 'trig-reg-1',
      trigger_count: 1,
    },
    directions: [
      {
        rank: 1,
        name: 'Go all in',
        source_run_id: 'run-anchor',
        arm: 'baseline',
        distribution: {
          provenance: 'computed',
          run_id: 'run-anchor',
          ensemble_id: 'ens-1',
          metric: 'cash',
          loss_threshold: 0,
          trials: 20,
          seed: 42,
          arm: 'baseline',
          n: 20,
          mean: 10,
          min: 0,
          max: 20,
          p10: 2,
          p50: 10,
          p90: 18,
          stddev: 5,
          p_loss: 0.2,
          expected_shortfall: { value: -3, threshold: -2, tail_count: 1, n: 20, alpha: 0.05, tail: 'lower' },
          bootstrap_intervals: [
            { statistic: 'p50', estimate: 10, low: 8, high: 12, draws: 200, seed: 7, level: 0.9, method: 'percentile' },
          ],
          trial_values_hash: 'sha256:trials',
        },
        drivers: {
          provenance: 'computed',
          rows: [
            { variable: 'demand', low_value: 0, high_value: 1, outcome_low: 0, outcome_high: 20, swing: 20 },
          ],
          ensemble_id: 'ens-1',
          note: null,
        },
        signals: [
          {
            kind: 'decision_gate',
            provenance: 'computed',
            text: 'Gate floor: p50 >= 5 (observed 10, passed)',
            source_ids: { gate_evaluation_id: 'eval-1' },
            name: 'floor',
            metric: 'p50',
            operator: '>=',
            threshold: 5,
            observed: 10,
            passed: true,
          },
          {
            kind: 'loop_trigger',
            provenance: 'computed',
            text: 'Loop trigger cash-floor: cash < 70',
            source_ids: { loop_id: 'loop-1' },
            name: 'cash-floor',
            metric: null,
            operator: null,
            threshold: null,
            observed: null,
            passed: null,
          },
        ],
        signals_note: null,
        premortem: {
          provenance: 'deliberated',
          deliberation_id: 'delib-strategy-1',
          template_id: 'gambit.premortem',
          failure_narrative: 'The launch failed in month three.',
          failure_modes: [
            { mode: 'Support overload', cause: 'Ticket volume tripled', early_signal: 'Queue depth rising', prevention: 'Hire ahead' },
          ],
          fatal_flags: ['No fallback vendor'],
          note: null,
        },
        first_step: {
          provenance: 'template',
          deliberation_id: null,
          template_id: null,
          next_action: null,
          cheapest_validation_test: null,
          conditions: [],
          note: 'No advisory-board deliberation is recorded for this direction.',
        },
        mece_trace: {
          provenance: 'computed',
          branches: [{ name: 'Demand', scope: ['demand'] }],
          tree_topic: 'Should we launch?',
        },
        mece_note: null,
      },
    ],
    markdown: '# 决策方向简报：Launch decision\n\n方向 1：Go all in',
  },
  polish: null,
}

export const narrativeReadPolished: DecisionNarrativeRead = {
  ...narrativeRead,
  polish: {
    id: 'polish-1',
    narrative_id: 'narrative-1',
    model: 'fixture-model',
    template_id: 'narrative.polish',
    template_version: '1',
    polished_markdown: '# Polished launch brief',
    created_at: '2026-11-15T11:00:00Z',
  },
}

// ---------------------------------------------------------------------------
// Sprint 14 — direction mappings + derivation
// ---------------------------------------------------------------------------

export const directionMappingDerived: DirectionMappingRead = {
  id: 'mapping-1',
  anchor_run_id: 'run-anchor',
  name: 'Highest P50',
  source_run_id: 'run-anchor',
  arm: 'strategy',
  mece_branches: [],
  deliberation_id: null,
  origin: 'derived',
  rule_id: 'highest_p50',
  rules_version: 'derivation-rules-v1',
  rule_record: {
    rule_id: 'highest_p50',
    status: 'produced',
    reason: 'Selected (run-anchor, strategy).',
    direction_name: 'Highest P50',
    source_run_id: 'run-anchor',
    arm: 'strategy',
    p50: 10,
    p_loss: 0.2,
    derivation_hash: 'sha256:derive0000000000000000000000000000000000000000000000000000',
    rules_version: 'derivation-rules-v1',
  },
  user_edited: false,
  position: 0,
  created_at: '2026-11-16T09:00:00Z',
  updated_at: '2026-11-16T09:00:00Z',
}

export const directionMappingAuthored: DirectionMappingRead = {
  id: 'mapping-2',
  anchor_run_id: 'run-anchor',
  name: 'My pick',
  source_run_id: 'run-other',
  arm: 'baseline',
  mece_branches: ['Demand'],
  deliberation_id: null,
  origin: 'authored',
  rule_id: null,
  rules_version: null,
  rule_record: null,
  user_edited: true,
  position: 1,
  created_at: '2026-11-16T09:05:00Z',
  updated_at: '2026-11-16T09:06:00Z',
}

export const derivationRead: DerivationRead = {
  anchor_run_id: 'run-anchor',
  rules_version: 'derivation-rules-v1',
  derivation_hash: 'sha256:derive0000000000000000000000000000000000000000000000000000',
  family_size: 2,
  candidates_considered: 4,
  outcomes: [
    {
      rule_id: 'highest_p50',
      status: 'produced',
      reason: 'Selected (run-anchor, strategy).',
      direction_name: 'Highest P50',
      source_run_id: 'run-anchor',
      arm: 'strategy',
      duplicate_of_rule: null,
      p50: 10,
      p_loss: 0.2,
      expected_shortfall: null,
      expected_shortfall_alpha: null,
    },
    {
      rule_id: 'most_robust',
      status: 'duplicate',
      reason: "Selected (run-anchor, strategy), already taken by rule 'highest_p50'.",
      direction_name: null,
      source_run_id: 'run-anchor',
      arm: 'strategy',
      duplicate_of_rule: 'highest_p50',
      p50: 10,
      p_loss: 0.2,
      expected_shortfall: null,
      expected_shortfall_alpha: null,
    },
    {
      rule_id: 'baseline_control',
      status: 'produced',
      reason: 'Selected (run-anchor, baseline).',
      direction_name: 'Baseline',
      source_run_id: 'run-anchor',
      arm: 'baseline',
      duplicate_of_rule: null,
      p50: 2,
      p_loss: 0.4,
      expected_shortfall: null,
      expected_shortfall_alpha: null,
    },
  ],
  mappings: [directionMappingDerived],
}
