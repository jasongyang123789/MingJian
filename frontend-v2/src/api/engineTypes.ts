// TypeScript mirrors of the Sprint 1–6 backend Pydantic shapes.
//
// Every interface below tracks its backend model field-for-field
// (services/mece, services/variables, services/distributions,
// services/robustness, services/calibration, services/skills). Field
// names are copied from the backend code, not guessed: the API serves
// exactly these shapes, and the stored fragments re-validate into the
// same models, so served and stored shapes cannot drift.
//
// Nullable fields use `T | null` because Pydantic serializes `None` as
// JSON null.

// ---------------------------------------------------------------------------
// Sprint 1 — MECE decomposition
// ---------------------------------------------------------------------------

export type MeceCheckKind = 'mutual_exclusion' | 'exhaustiveness' | 'structure'
export type MeceCheckStatus = 'PASS' | 'FAIL'
export type MeceIssueKind =
  | 'overlap'
  | 'gap'
  | 'extra'
  | 'duplicate_tag'
  | 'empty_branch'
  | 'empty_tree'
  | 'max_depth_exceeded'

export interface DecompositionBranch {
  name: string
  scope: string[]
  children: DecompositionBranch[]
}

export interface DecompositionTree {
  topic: string
  root: DecompositionBranch
}

export interface MeceCheckRecord {
  node: string
  check: MeceCheckKind
  status: MeceCheckStatus
  detail: string
}

export interface MeceIssue {
  kind: MeceIssueKind
  node: string
  detail: string
  tags: string[]
  branches: string[]
}

export interface MeceValidationResult {
  is_mece: boolean
  checks: MeceCheckRecord[]
  issues: MeceIssue[]
  scope_tag_count: number
  branch_count: number
}

export interface MeceRunRead {
  run_id: string
  decomposition: DecompositionTree
  validation: MeceValidationResult
}

// ---------------------------------------------------------------------------
// Sprint 2 — variable tables (+ Sprint 4 formula graph)
// ---------------------------------------------------------------------------

export type DistributionType = 'fixed' | 'normal' | 'triangular' | 'beta_pert' | 'bernoulli'
export type FormulaOperator = 'add' | 'subtract' | 'multiply' | 'divide' | 'min' | 'max'

export interface VariableDistribution {
  type: DistributionType
  value: number | null
  mean: number | null
  std: number | null
  min: number | null
  mode: number | null
  max: number | null
  p: number | null
}

export interface VariableDefinition {
  id: string
  unit: string
  distribution: VariableDistribution
  evidence_ref: string
  description: string
  scope_tags: string[]
}

export interface FormulaDefinition {
  output: string
  expression: unknown
  description: string
}

export interface VariableSet {
  name: string
  variables: VariableDefinition[]
  formulas: FormulaDefinition[]
  internal: Record<string, string>
}

export interface VariableValidationIssue {
  kind: string
  variable: string
  message: string
}

export interface VariableCheckRecord {
  variable: string
  check: string
  status: string
  detail: string
}

export interface VariableValidationResult {
  is_valid: boolean
  variable_count: number
  checks: VariableCheckRecord[]
  issues: VariableValidationIssue[]
}

export interface TemplateStateField {
  name: string
  description: string
  default: number
}

export interface MetricPolicySpec {
  preferred_direction: string
  alert_threshold: number
  critical_threshold: number
}

export interface VariableTemplate {
  id: string
  name: string
  domain_id: string
  description: string
  state_fields: TemplateStateField[]
  policies: Record<string, MetricPolicySpec>
  variables: VariableDefinition[]
  formulas: FormulaDefinition[]
  internal: Record<string, string>
  is_builtin: boolean
}

export interface VariableTemplateCreate {
  name: string
  domain_id: string
  description: string
  state_fields: TemplateStateField[]
  policies: Record<string, MetricPolicySpec>
  variables: VariableDefinition[]
  formulas: FormulaDefinition[]
  internal: Record<string, string>
}

export interface VariableTemplateUpdate {
  name?: string | null
  description?: string | null
  state_fields?: TemplateStateField[] | null
  policies?: Record<string, MetricPolicySpec> | null
  variables?: VariableDefinition[] | null
  formulas?: FormulaDefinition[] | null
  internal?: Record<string, string> | null
}

export interface VariableTemplateRead extends VariableTemplate {
  created_at: string | null
  updated_at: string | null
}

export interface VariableRunRead {
  run_id: string
  template: VariableTemplate | null
  bindings: VariableSet | null
  validation: VariableValidationResult | null
}

// ---------------------------------------------------------------------------
// Sprint 3 — distribution layer + determinism
// ---------------------------------------------------------------------------

export interface MonteCarloRequest {
  trials: number
  seed: number | null
  metric: string
  loss_threshold: number
  strategy_levers: Record<string, number>
}

export interface DistributionSummary {
  n: number
  mean: number
  min: number
  max: number
  p10: number
  p50: number
  p90: number
  stddev: number
  p_loss: number
}

export interface PairedDeltaSummary {
  n: number
  mean_delta: number
  p10: number
  p50: number
  p90: number
  p_strategy_better: number
}

export interface MonteCarloResult {
  ensemble_id: string
  base_run_id: string
  trials: number
  seed: number
  metric: string
  loss_threshold: number
  strategy_levers: Record<string, number>
  baseline: DistributionSummary
  strategy: DistributionSummary
  paired: PairedDeltaSummary
  trial_run_ids: Record<string, string[]>
  protocol: string
}

export interface ReplayResult {
  original_run_id: string
  replay_run_id: string
  match: boolean
  first_diverging_tick: number | null
  tick_count: number
  original_state_hashes: Record<string, string>
  replay_state_hashes: Record<string, string>
  input_hash_match: boolean
}

export interface DeterminismRead {
  run_id: string
  seed: number
  protocol: string
  input_hash: string | null
  state_hashes: Record<string, string>
  sampled_values: Record<string, number>
  sampled_applied: string[]
  derived_values: Record<string, number>
  derived_applied: string[]
}

// ---------------------------------------------------------------------------
// Sprint 4 — robustness evaluation + decision gates
// ---------------------------------------------------------------------------

export type GateOperator = '>' | '>=' | '<' | '<='
export type GateMetric =
  | 'mean'
  | 'p10'
  | 'p50'
  | 'p90'
  | 'min'
  | 'max'
  | 'stddev'
  | 'p_loss'
  | 'expected_shortfall'
  | 'mean_delta'
  | 'p_strategy_better'
export type GateArm = 'baseline' | 'strategy' | 'paired'

export interface GateDefinition {
  name: string
  metric: GateMetric
  operator: GateOperator
  threshold: number
  arm: GateArm
  alpha: number
}

export interface GateRegistrationRequest {
  gates: GateDefinition[]
  supersedes: string | null
}

export interface GateRegistration {
  id: string
  run_id: string
  ensemble_id: string | null
  gates: GateDefinition[]
  supersedes: string | null
  registered_at: string
  ensemble_existed_at_registration: boolean
  status: 'active' | 'superseded'
}

export interface GateOutcome {
  name: string
  metric: GateMetric
  operator: GateOperator
  threshold: number
  arm: GateArm
  alpha: number | null
  observed: number
  passed: boolean
}

export interface GateEvaluation {
  id: string
  registration_id: string
  run_id: string
  ensemble_id: string
  evaluated_at: string
  outcomes: GateOutcome[]
  all_passed: boolean
  pre_registered: boolean
}

export interface GateEvaluationRequest {
  registration_id: string | null
}

export interface DecisionGatesRead {
  run_id: string
  registrations: GateRegistration[]
  evaluations: GateEvaluation[]
}

export interface ExpectedShortfallDetail {
  value: number
  threshold: number
  tail_count: number
  n: number
}

export interface ExpectedShortfallRequest {
  alpha: number
  tail: 'lower' | 'upper'
}

export interface ExpectedShortfallResult {
  run_id: string
  ensemble_id: string
  metric: string
  alpha: number
  tail: 'lower' | 'upper'
  baseline: ExpectedShortfallDetail
  strategy: ExpectedShortfallDetail
  paired: ExpectedShortfallDetail
  trial_values_hash: string
  protocol: string
}

export interface TornadoRequest {
  low_quantile: number
  high_quantile: number
  seed: number | null
  variables: string[] | null
}

export interface TornadoRow {
  variable: string
  low_value: number
  high_value: number
  base_value: number
  outcome_low: number
  outcome_high: number
  outcome_base: number
  swing: number
}

export interface TornadoResult {
  run_id: string
  ensemble_id: string
  metric: string
  seed: number
  low_quantile: number
  high_quantile: number
  base_run_id: string
  rows: TornadoRow[]
  probe_run_ids: string[]
  protocol: string
}

export interface ThresholdSearchRequest {
  variable: string
  mode: 'p_loss' | 'arm_flip'
  target: number
  direction: 'increasing' | 'decreasing'
  bounds: [number, number] | null
  trials_per_evaluation: number
  max_iterations: number
  tolerance: number
  seed: number | null
  loss_threshold: number | null
}

export interface ThresholdEvaluation {
  value: number
  statistic: number
  trials: number
  probe_run_ids: string[]
}

export interface ThresholdSearchResult {
  run_id: string
  ensemble_id: string
  metric: string
  variable: string
  mode: 'p_loss' | 'arm_flip'
  target: number
  direction: 'increasing' | 'decreasing'
  bounds: [number, number]
  threshold: number | null
  achieved_statistic: number | null
  reachable: boolean
  iterations: number
  evaluations: ThresholdEvaluation[]
  trials_per_evaluation: number
  tolerance: number
  loss_threshold: number
  seed: number
  protocol: string
}

export type BootstrapStatistic = 'mean' | 'median' | 'p_loss'

export interface BootstrapRequest {
  statistics: BootstrapStatistic[]
  draws: number
  seed: number | null
  level: number
}

export interface BootstrapInterval {
  statistic: string
  estimate: number
  low: number
  high: number
  draws: number
  seed: number
  level: number
  method: string
}

export interface BootstrapResult {
  run_id: string
  ensemble_id: string
  metric: string
  loss_threshold: number
  baseline: BootstrapInterval[]
  strategy: BootstrapInterval[]
  trial_values_hash: string
  protocol: string
}

export interface RobustnessRead {
  run_id: string
  ensemble_id: string | null
  expected_shortfall: ExpectedShortfallResult | null
  tornado: TornadoResult | null
  threshold_search: ThresholdSearchResult | null
  bootstrap: BootstrapResult | null
}

// ---------------------------------------------------------------------------
// Sprint 5 — calibration + hindsight firewall
// ---------------------------------------------------------------------------

export interface PolicyFitRequest {
  template_id: string
  ridge_strength: number
  seed: number
  bootstrap_draws: number
  level: number
  source_run_ids: string[] | null
}

export interface RuleWeightFitRequest {
  domain_id: string
  metric: string
  ridge_strength: number
  seed: number
  bootstrap_draws: number
  level: number
  source_run_ids: string[] | null
}

export interface ThresholdChange {
  metric: string
  preferred_direction: string
  prior_alert_threshold: number
  fitted_alert_threshold: number
  prior_critical_threshold: number
  fitted_critical_threshold: number
  alert_bootstrap: Record<string, unknown> | null
  critical_bootstrap: Record<string, unknown> | null
  n_observations: number
  n_tail: number
  unchanged_reason: string | null
  rejected_fit: Record<string, number> | null
}

export interface RuleWeightChange {
  rule_id: string
  prior_weight: number
  fitted_weight: number
  bootstrap: Record<string, unknown>
  total_matches: number
}

export interface CalibrationFitRead {
  id: string
  kind: string
  domain_id: string
  source_template_id: string | null
  calibrated_template_id: string | null
  metric: string | null
  ridge_strength: number
  seed: number
  bootstrap_draws: number
  level: number
  source_run_ids: string[]
  n_observations: number
  changes: Record<string, unknown>
  inputs_hash: string
  loo_rmse: number | null
  application: Record<string, unknown>
  created_at: string
}

export interface FirewallRead {
  run_id: string
  decision_time: string | null
  cutoff_source: string | null
  firewall_active: boolean
  included_claim_ids: string[]
  excluded_claim_ids: string[]
  stored_evidence_ids: string[]
}

// ---------------------------------------------------------------------------
// Sprint 6 — skill deliberations
// ---------------------------------------------------------------------------

export interface StageRecord {
  stage: string
  template_id: string
  template_version: string
  contract_version: string
  output: Record<string, unknown>
  model: string | null
}

export interface StrategyTeamRequest {
  topic: string
  decision_question: string
  context_lines: string[]
  mode: 'standard' | 'deep'
  output_language: string
  include_premortem: boolean
  failure_date: string
}

export interface AdvisoryBoardRequest {
  decision: string
  options: string[]
  context_lines: string[]
  mode: 'quick' | 'standard'
  output_language: string
}

export interface MeceProposeRequest {
  topic: string
  context_lines: string[]
  suggested_dimensions: string[]
  existing_tree: DecompositionTree | null
  output_language: string
}

// Stage output contracts (services/skills/contracts.py).

export interface IntakeClassification {
  problem_statement: string
  decision_question: string
  engagement_type: string
  audience: string
  constraints: string[]
  stakes: 'standard' | 'deep'
  frameworks: string[]
  wave_plan: string[]
  open_questions: string[]
}

export interface Diagnosis {
  findings: string[]
  assumptions: string[]
  barriers: string[]
  open_questions: string[]
}

export interface MarketMap {
  summary: string
  segments: string[]
  competitors: string[]
  white_space: string[]
  profit_pools: string[]
  threats: string[]
}

export interface OptionCandidate {
  name: string
  description: string
  upside: string
  trade_off: string
  what_must_be_true: string[]
}

export interface OptionSet {
  options: OptionCandidate[]
}

export interface ShortlistEntry {
  name: string
  description: string
  scores: Record<string, number>
  rationale: string
}

export interface DroppedOption {
  name: string
  reason: string
}

export interface Shortlist {
  ranked: ShortlistEntry[]
  dropped: DroppedOption[]
}

export interface SynthesisArgument {
  claim: string
  backing: string
}

export interface Synthesis {
  governing_thought: string
  arguments: SynthesisArgument[]
  recommended_option: string
  load_bearing_assumptions: string[]
  alternatives_considered: string[]
}

export interface AuditedAssumption {
  assumption: string
  category: string
  importance: number
  evidence_strength: 'strong' | 'moderate' | 'weak' | 'speculative'
  risk: string
}

export interface AssumptionAudit {
  assumptions: AuditedAssumption[]
  load_bearing: string[]
  tests: string[]
  fatal_flags: string[]
}

export interface WarGameScenario {
  name: string
  trigger: string
  impact: string
  likelihood: string
  severity: string
}

export interface Vulnerability {
  weak_point: string
  why_it_matters: string
  mitigation: string
}

export interface PlaybookEntry {
  signal: string
  response: string
  owner: string
}

export interface WarGame {
  scenarios: WarGameScenario[]
  vulnerabilities: Vulnerability[]
  playbook: PlaybookEntry[]
  fatal_flags: string[]
}

export interface ExecutionRisk {
  risk: string
  mitigation: string
  owner: string
}

export interface ExecutionReview {
  feasibility: string
  risks: ExecutionRisk[]
  economics_survive_bad_case: string
  fatal_flags: string[]
}

export interface FailureMode {
  mode: string
  cause: string
  early_signal: string
  prevention: string
}

export interface PreMortem {
  failure_narrative: string
  failure_modes: FailureMode[]
  fatal_flags: string[]
}

export interface PanelFlag {
  flag: string
  lenses: string[]
  lens_count: number
  must_address: boolean
}

export interface PanelTally {
  flags: PanelFlag[]
  must_address: string[]
}

export interface TournamentMatch {
  option_a: string
  option_b: string
  winner: string
  rationale: string
}

export interface TournamentResult {
  matches: TournamentMatch[]
  wins: Record<string, number>
  winner: string | null
}

/** Verifier-panel outputs keyed by lens (assumptions/wargame/execution/premortem). */
export interface StrategyTeamPanel {
  assumptions?: AssumptionAudit
  wargame?: WarGame
  execution?: ExecutionReview
  premortem?: PreMortem
}

export interface StrategyTeamResult {
  pipeline: 'strategy_team'
  mode: 'standard' | 'deep'
  topic: string
  stages: StageRecord[]
  intake: IntakeClassification
  diagnosis: Diagnosis
  market_map: MarketMap
  option_sets: OptionSet[]
  shortlist: Shortlist
  synthesis: Synthesis
  synthesis_recommendation_in_shortlist: boolean
  panel: StrategyTeamPanel
  wargame_rounds: WarGame[]
  tally: PanelTally
  tournament: TournamentResult | null
  wargame_loop_rounds: number
  wargame_loop_stop_reason: string
}

export interface CritIntake {
  decision: string
  options: string[]
  context: string
  evidence: string
  economics: string
  constraints: string[]
  success: string
  current_preference: string
  reversibility: string
  assumptions: string[]
  questions: string[]
}

export interface RiskVeto {
  failure_path: string
  evidence: string
  severity: string
  mitigation: string
}

export interface LensPosition {
  lens: string
  option_scores: Record<string, number>
  confidence: 'low' | 'medium' | 'high'
  decisive_evidence: string
  primary_upside: string
  primary_failure_mode: string
  opening_recommendation: string
  risk_veto: RiskVeto | null
}

export interface LensRevision {
  lens: string
  final_option: string
  revised_scores: Record<string, number>
  confidence: 'low' | 'medium' | 'high'
  what_changed: string
  required_conditions: string[]
  kill_criterion: string
  unresolved_objection: string
}

export interface DebateDisagreement {
  trade_off: string
  case_a: string
  case_b: string
  rebuttals: string[]
  settling_evidence: string
  cheapest_test: string
}

export interface ForcedDebate {
  disagreements: DebateDisagreement[]
  minority_objection: string
}

export interface DecisionContract {
  verdict: 'choose' | 'reject' | 'validate_first'
  why_now: string
  conditions: string[]
  minority_report: string
  cheapest_validation_test: string
  go_threshold: string
  kill_criterion: string
  owner: string
  deadline: string
  review_date: string
  next_action: string
  do_not_do: string
  lens_weights: Record<string, number>
  assumptions: string[]
}

export interface WeightedDirection {
  scores: Record<string, number>
  weights: Record<string, number>
  ranking: string[]
  top_option: string | null
}

export interface RiskVetoRecord {
  lens: string
  failure_path: string
  evidence: string
  severity: string
  mitigation: string
}

export interface AdvisoryBoardResult {
  pipeline: 'advisory_board'
  mode: 'quick' | 'standard'
  decision: string
  stages: StageRecord[]
  intake: CritIntake
  positions: LensPosition[]
  debate: ForcedDebate | null
  revisions: LensRevision[]
  contract: DecisionContract
  weighted_direction_round1: WeightedDirection
  weighted_direction_final: WeightedDirection
  vetoes: RiskVetoRecord[]
  has_unmitigated_veto: boolean
  unanimous_option: string | null
}

export type DeliberationResult = StrategyTeamResult | AdvisoryBoardResult

export interface SkillDeliberationRecord {
  id: string
  run_id: string
  pipeline: 'strategy_team' | 'advisory_board'
  mode: string
  created_at: string
  result: DeliberationResult
}

export interface SkillDeliberationListRead {
  run_id: string
  deliberations: SkillDeliberationRecord[]
}

export interface MeceProposalRead {
  proposal: DecompositionTree
  validation: MeceValidationResult
  stage: StageRecord
}
