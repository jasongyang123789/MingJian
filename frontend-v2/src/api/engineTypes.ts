// TypeScript mirrors of the Sprint 1–9 backend Pydantic shapes.
//
// Every interface below tracks its backend model field-for-field
// (services/mece, services/variables, services/distributions,
// services/robustness, services/calibration, services/skills,
// services/living_loop). Field names are copied from the backend code, not guessed: the API serves
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
export type FormulaOperator = 'add' | 'subtract' | 'multiply' | 'divide' | 'min' | 'max' | 'pow' | 'logistic'

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

export interface MonteCarloTrialValues {
  ensemble_id: string
  base_run_id: string
  metric: string
  loss_threshold: number
  baseline: number[]
  strategy: number[]
  trial_values_hash: string
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

// ---------------------------------------------------------------------------
// Sprint 9 — Living-strategy loop (services/living_loop)
// ---------------------------------------------------------------------------

export type TriggerKind = 'threshold' | 'gate' | 'deviation'
export type TriggerOperator = '>' | '>=' | '<' | '<='

export interface ThresholdTrigger {
  kind: 'threshold'
  name: string
  field: string
  operator: TriggerOperator
  threshold: number
}

export interface GateTrigger {
  kind: 'gate'
  name: string
  field: string
  gate: GateDefinition
  loss_threshold: number | null
}

export interface DeviationTrigger {
  kind: 'deviation'
  name: string
  field: string
  tolerance: number
  consecutive: number
  reference_value: number | null
}

export type LoopTriggerDefinition = ThresholdTrigger | GateTrigger | DeviationTrigger

export interface TriggerRegistrationRequest {
  triggers: LoopTriggerDefinition[]
  supersedes: string | null
}

export interface TriggerRegistration {
  id: string
  loop_id: string
  triggers: LoopTriggerDefinition[]
  supersedes: string | null
  registered_at: string
  observation_count_at_registration: number
  status: 'active' | 'superseded'
}

export interface LoopObservationCreate {
  field: string
  value: number
  observed_at: string
  source_claim_id: string | null
  source_note: string | null
}

export interface LoopObservationRead {
  id: string
  loop_id: string
  field: string
  value: number
  observed_at: string
  source_claim_id: string | null
  source_note: string | null
  recorded_at: string
}

export type TriggerEvaluationStatus = 'fired' | 'quiet' | 'no_data'

export interface TriggerEvaluationOutcome {
  name: string
  kind: TriggerKind
  field: string
  fired: boolean
  status: TriggerEvaluationStatus
  observed_value: number | null
  threshold: number | null
  tolerance: number | null
  reference_value: number | null
  consecutive_breaches: number | null
  observation_ids: string[]
  observed_values: number[]
  note: string
}

export interface StrategyLoopCreate {
  baseline_run_id: string
  name: string
  triggers: LoopTriggerDefinition[]
}

export interface StrategyLoopRead {
  id: string
  name: string
  baseline_run_id: string
  domain_id: string
  status: 'active'
  triggers: TriggerRegistration[]
  created_at: string
  updated_at: string
}

export interface StartIterationRequest {
  decision_time: string
}

export interface ResimulateRequest {
  variable_template_id: string | null
  variable_set: VariableSet | null
  seed: number | null
  tick_count: number | null
  note: string | null
}

export interface ResimulationRecord {
  run_id: string
  previous_cutoff: string | null
  new_cutoff: string
  previous_input_hash: string | null
  new_input_hash: string | null
  template_id: string | null
  template_snapshot_hash: string | null
  resolved_template_snapshot_hash: string | null
  seed: number
  tick_count: number
  changes: Record<string, unknown>
  claims_visible: number
  claims_excluded: number
  created_at: string
}

export interface ArmDelta {
  arm: 'baseline' | 'strategy'
  old: DistributionSummary
  new: DistributionSummary
  delta_p10: number
  delta_p50: number
  delta_p90: number
  delta_mean: number
  delta_p_loss: number
}

export interface GateReevaluation {
  registration_id: string
  ensemble_id: string
  outcomes: GateOutcome[]
  all_passed: boolean
  pre_registered: boolean
}

export interface ThresholdDriftRow {
  variable: string
  mode: 'p_loss' | 'arm_flip'
  old_threshold: number | null
  old_reachable: boolean
  new_threshold: number | null
  new_reachable: boolean
}

export interface EnsembleComparison {
  baseline_run_id: string
  baseline_ensemble_id: string
  new_run_id: string
  new_ensemble_id: string
  metric: string
  loss_threshold: number
  baseline_arm: ArmDelta
  strategy_arm: ArmDelta
  paired_mean_delta_old: number
  paired_mean_delta_new: number
  paired_mean_delta_change: number
  paired_p_strategy_better_old: number
  paired_p_strategy_better_new: number
  paired_p_strategy_better_change: number
  same_seed: boolean
  same_trials: boolean
  seeds_paired: boolean
  evidence_caveat: string | null
  gate_reevaluation: GateReevaluation | null
  threshold_drift: ThresholdDriftRow[]
  compared_at: string
}

export type ReviewDecision = 'continue' | 'pivot' | 'pause' | 'stop'

export interface ReviewDecisionRecord {
  decision: ReviewDecision
  rationale: string
  decided_at: string
}

export interface DecideRequest {
  decision: ReviewDecision
  rationale: string
}

export type LoopIterationState = 'open' | 'evaluated' | 'resimulated' | 'compared' | 'decided'

export interface LoopIterationRead {
  id: string
  loop_id: string
  index: number
  state: LoopIterationState
  decision_time: string
  previous_cutoff: string | null
  window_from: string | null
  window_to: string | null
  observation_ids: string[]
  trigger_evaluations: TriggerEvaluationOutcome[]
  resimulation: ResimulationRecord | null
  comparison: EnsembleComparison | null
  decision: ReviewDecisionRecord | null
  created_at: string
  updated_at: string
}

export interface LoopTimelineRead {
  loop: StrategyLoopRead
  observations: LoopObservationRead[]
  iterations: LoopIterationRead[]
}

export type LoopEvaluationSummary = 'fired' | 'quiet' | 'no_data' | 'error'

export interface LoopEvaluationRead {
  id: string
  loop_id: string
  cycle_id: string
  evaluated_at: string
  observation_fingerprint: string
  registration_id: string | null
  observation_ids: string[]
  outcomes: TriggerEvaluationOutcome[]
  summary: LoopEvaluationSummary
  error_code: string | null
  error_message: string | null
  created_at: string
}

export interface MonitoringCycleLoopResult {
  loop_id: string
  result: 'evaluated' | 'skipped_unchanged'
  evaluation_id: string
  summary: LoopEvaluationSummary
}

export interface MonitoringCycleResult {
  cycle_id: string
  evaluated_at: string
  loops_evaluated: number
  loops_skipped: number
  loops_fired: number
  loops_errored: number
  loops: MonitoringCycleLoopResult[]
  errors: string[]
}


// ---------------------------------------------------------------------------
// Sprint 13 — decision-direction narratives
// ---------------------------------------------------------------------------

export type NarrativeProvenance = 'computed' | 'deliberated' | 'template'

export interface NarrativeDirectionDefinition {
  name: string
  source_run_id: string
  arm: 'baseline' | 'strategy'
  mece_branches: string[]
  deliberation_id: string | null
}

export interface NarrativeGenerateRequest {
  topic: string | null
  directions?: NarrativeDirectionDefinition[]
  loop_id: string | null
}

export interface NarrativeDistributionSection {
  provenance: 'computed'
  run_id: string
  ensemble_id: string
  metric: string
  loss_threshold: number
  trials: number
  seed: number
  arm: 'baseline' | 'strategy'
  n: number
  mean: number
  min: number
  max: number
  p10: number
  p50: number
  p90: number
  stddev: number
  p_loss: number
  expected_shortfall: Record<string, unknown> | null
  bootstrap_intervals: Record<string, unknown>[]
  trial_values_hash: string | null
}

export interface NarrativeDriverRow {
  variable: string
  low_value: number
  high_value: number
  outcome_low: number
  outcome_high: number
  swing: number
}

export interface NarrativeDriversSection {
  provenance: 'computed'
  rows: NarrativeDriverRow[]
  ensemble_id: string | null
  note: string | null
}

export interface NarrativeTripwireSignal {
  kind: 'decision_gate' | 'threshold_search' | 'loop_trigger' | 'advisory_contract' | 'wargame_playbook'
  provenance: NarrativeProvenance
  text: string
  source_ids: Record<string, string>
  name: string | null
  metric: string | null
  operator: string | null
  threshold: number | null
  observed: number | null
  passed: boolean | null
}

export interface NarrativeFailureModeQuote {
  mode: string
  cause: string
  early_signal: string
  prevention: string
}

export interface NarrativePremortemSection {
  provenance: 'deliberated' | 'template'
  deliberation_id: string | null
  template_id: string | null
  failure_narrative: string | null
  failure_modes: NarrativeFailureModeQuote[]
  fatal_flags: string[]
  note: string | null
}

export interface NarrativeFirstStepSection {
  provenance: 'deliberated' | 'template'
  deliberation_id: string | null
  template_id: string | null
  next_action: string | null
  cheapest_validation_test: string | null
  conditions: string[]
  note: string | null
}

export interface NarrativeMeceBranchTrace {
  name: string
  scope: string[]
}

export interface NarrativeMeceTrace {
  provenance: 'computed'
  branches: NarrativeMeceBranchTrace[]
  tree_topic: string
}

export interface NarrativeDirection {
  rank: number
  name: string
  source_run_id: string
  arm: 'baseline' | 'strategy'
  distribution: NarrativeDistributionSection
  drivers: NarrativeDriversSection
  signals: NarrativeTripwireSignal[]
  signals_note: string | null
  premortem: NarrativePremortemSection
  first_step: NarrativeFirstStepSection
  mece_trace: NarrativeMeceTrace | null
  mece_note: string | null
}

export interface NarrativeMeceContext {
  provenance: 'computed'
  topic: string
  is_mece: boolean
  branch_count: number
  scope_tag_count: number
  issue_count: number
}

export interface NarrativeCalibrationContextEntry {
  fit_id: string
  kind: string
  loo_rmse: number | null
  inputs_hash: string
  calibrated_template_id: string | null
  n_observations: number
  created_at: string
}

export interface NarrativeLoopContext {
  provenance: 'computed'
  loop_id: string
  loop_name: string
  registration_id: string | null
  trigger_count: number
}

export interface NarrativeBody {
  protocol: string
  anchor_run_id: string
  domain_id: string
  topic: string
  topic_source: 'request' | 'mece_tree' | 'run_id'
  mece: NarrativeMeceContext | null
  calibration_context: NarrativeCalibrationContextEntry[]
  loop_context: NarrativeLoopContext | null
  directions: NarrativeDirection[]
  markdown: string
}

export interface NarrativePolishRead {
  id: string
  narrative_id: string
  model: string | null
  template_id: string
  template_version: string
  polished_markdown: string
  created_at: string
}

export interface DecisionNarrativeRead {
  id: string
  run_id: string
  version: number
  topic: string
  inputs_hash: string
  content_hash: string
  created_at: string
  body: NarrativeBody
  polish: NarrativePolishRead | null
  direction_mapping_ids: string[]
}

export interface DecisionNarrativeListRead {
  run_id: string
  narratives: DecisionNarrativeRead[]
}

// ==================== Sprint 14 — 方向推导 + 已存映射 ====================

export type DirectionMappingOrigin = 'derived' | 'authored' | 'llm_proposal' | 'override'
export type DirectionMappingStatus = 'active' | 'proposed' | 'rejected'

export interface DirectionMappingRead {
  id: string
  anchor_run_id: string
  name: string
  source_run_id: string
  arm: 'baseline' | 'strategy'
  mece_branches: string[]
  deliberation_id: string | null
  origin: DirectionMappingOrigin
  rule_id: string | null
  rules_version: string | null
  rule_record: Record<string, unknown> | null
  status: DirectionMappingStatus
  proposal_record: Record<string, unknown> | null
  override_record: Record<string, unknown> | null
  user_edited: boolean
  position: number
  created_at: string
  updated_at: string
}

export interface DirectionMappingListRead {
  run_id: string
  mappings: DirectionMappingRead[]
}

export type DirectionMappingCreate = NarrativeDirectionDefinition

export interface DirectionMappingUpdate {
  name?: string
  source_run_id?: string
  arm?: 'baseline' | 'strategy'
  mece_branches?: string[]
  deliberation_id?: string | null
}

export type DerivationRuleId = 'highest_p50' | 'most_robust' | 'baseline_control'
export type DerivationOutcomeStatus = 'produced' | 'none' | 'duplicate' | 'skipped'

export interface DerivationRuleOutcome {
  rule_id: DerivationRuleId
  status: DerivationOutcomeStatus
  reason: string
  direction_name: string | null
  source_run_id: string | null
  arm: 'baseline' | 'strategy' | null
  duplicate_of_rule: string | null
  p50: number | null
  p_loss: number | null
  expected_shortfall: number | null
  expected_shortfall_alpha: number | null
}

export interface DerivationRead {
  anchor_run_id: string
  rules_version: string
  derivation_hash: string
  family_size: number
  candidates_considered: number
  outcomes: DerivationRuleOutcome[]
  mappings: DirectionMappingRead[]
}

// ==================== Option B — 变量覆盖方向 ====================
// Mirrors services/narratives/models.py: DirectionOverrideSpec/
// DirectionOverrideRequest/DirectionOverrideOutcome/DirectionOverrideRead.
// `fork_step` is optional: omitted, the backend applies the
// scenario-branch midpoint default.

export interface DirectionOverrideSpec {
  name: string
  overrides: Record<string, number>
  arm: 'baseline' | 'strategy'
  mece_branches: string[]
  fork_step?: number
}

export interface DirectionOverrideRequest {
  directions: DirectionOverrideSpec[]
}

export type DirectionOverrideOutcomeStatus = 'stored' | 'skipped' | 'failed'

export interface DirectionOverrideOutcome {
  name: string
  status: DirectionOverrideOutcomeStatus
  reason: string
  mapping_id: string | null
  branch_id: string | null
  child_run_id: string | null
  fork_step: number | null
  child_status: string | null
  arm: 'baseline' | 'strategy'
  mece_branches: string[]
}

export interface DirectionOverrideRead {
  anchor_run_id: string
  override_hash: string
  directions_considered: number
  outcomes: DirectionOverrideOutcome[]
  mappings: DirectionMappingRead[]
}

// Mirrors services/narratives/models.py:
// DirectionOverrideReforkRequest/DirectionOverrideReforkRead.
// Re-forking repoints the SAME mapping at a new branch run; the old
// branch run is left untouched. `fork_step` is optional: omitted, the
// backend applies the scenario-branch midpoint default.
export interface DirectionOverrideReforkRequest {
  overrides: Record<string, number>
  fork_step?: number
}

export interface DirectionOverrideReforkRead {
  mapping: DirectionMappingRead
  branch_id: string
  child_run_id: string
  fork_step: number
  child_status: string | null
  override_hash: string
  reason: string
}

// ==================== Phase 2 — 汽车包 ====================

export interface AutomotiveTrajectoryPoint {
  tick: number
  actor_id: string
  state: Record<string, number>
}

export interface AutomotiveTrajectoryRead {
  run_id: string
  domain_id: string
  run_status: string
  tick_count: number
  multiple_actors: boolean
  actor_ids: string[]
  points: AutomotiveTrajectoryPoint[]
}

export interface AutomotiveSplitStructureRead {
  run_id: string
  structure: Record<string, unknown>
  validation: Record<string, unknown>
}

export interface SalesLayerRowRead {
  tick: number
  oem_id: string
  product_id: string
  units: number
  capacity_value: number
  own_sales: number | null
}

export interface SalesLayerTickTotalRead {
  tick: number
  production_volume: number
  units: number
  capacity_value: number
  own_sales: number | null
}

export interface SalesLayerSummaryRead {
  total_units: number
  total_capacity_value: number
  total_own_sales: number | null
  tick_count: number
  oem_count: number
  product_count: number
}

export interface SalesLayerRead {
  run_id: string
  domain_id: string
  snapshot_tick_count: number
  rows: SalesLayerRowRead[]
  per_tick: SalesLayerTickTotalRead[]
  summary: SalesLayerSummaryRead
  production_trajectory: Array<{ tick: number; production_volume: number }>
  assumptions: string[]
  skipped_unpriced_slots: string[]
  own_sales_basis: string
  own_sales_unavailable_reason: string | null
}

export interface SupplyShareOverride {
  oem_id: string
  product_id: string
  share: number
}

export interface SalesLayerRequest {
  oem_production_shares: Record<string, number>
  own_supplier_id?: string | null
  supply_shares?: SupplyShareOverride[]
  default_supply_share?: number | null
  strict_prices?: boolean
}

export interface CooccurrencePrompt {
  rule_id: string
  severity: 'anomaly' | 'info'
  path: string
  title: string
  observed: string
  expected_logic: string
  likely_explanations: string[]
  evidence_ref: string
  scope: string
}

export interface PromptSkipRecord {
  rule_id: string
  path: string
  reason: string
}

export interface PromptReportRead {
  prompts: CooccurrencePrompt[]
  skipped: PromptSkipRecord[]
  anomaly_count: number
  info_count: number
  rules_evaluated: string[]
  rules_skipped: string[]
}

export interface ExpectationCatalogEntry {
  id: string
  title: string
  normal_logic: string
  strength: string
  scope: string
  evidence_ref: string
  evaluated: boolean
}

// ==================== Sprint 20 — 多模型研讨 ====================
// Shapes mirror src/planagent/services/seminar/models.py,
// contracts.py, audit.py, and the composer document exactly; the
// cockpit reads them, it never re-derives them.

export interface SeminarEndpointConfig {
  target?: string | null
  base_url_env?: string | null
  api_key_env?: string | null
  model?: string | null
}

export interface SeminarModelPortConfig {
  model_id: string
  endpoint: SeminarEndpointConfig
  temperature: number
  timeout_seconds: number
}

export interface SeminarModelPortConfigInput {
  model_id: string
  endpoint?: SeminarEndpointConfig
  temperature?: number
  timeout_seconds?: number
}

export interface SeminarRosterEntry {
  model_id: string
  endpoint: SeminarEndpointConfig
  temperature: number
  timeout_seconds: number
  max_rounds: number | null
  role: 'participant' | 'chair'
}

export interface SeminarRosterEntryInput {
  model_id: string
  endpoint?: SeminarEndpointConfig
  temperature?: number
  timeout_seconds?: number
  max_rounds?: number | null
  role?: 'participant' | 'chair'
}

export type SeminarPipeline = 'strategy_team' | 'advisory_board'
export type SeminarChairMode = 'model' | 'agent'

export interface SeminarConfigRead {
  pipeline: SeminarPipeline
  mode: string
  max_rounds: number
  quiet_rounds: number
  snapshot_policy: 'latest_per_model'
  max_concurrency: number
  output_language: string
  include_premortem: boolean
  failure_date: string
  decision_question: string
  options: string[]
  context_lines: string[]
  chair_participates: boolean
  chair_mode: SeminarChairMode
  max_stage_calls: number
  max_tokens: number
  max_retries: number
  retry_backoff_seconds: number
  near_duplicate_threshold: number
}

export interface SeminarCreateRequest {
  topic: string
  decision_question?: string
  options?: string[]
  roster?: SeminarRosterEntryInput[]
  pipeline?: SeminarPipeline
  mode?: string
  max_rounds?: number
  quiet_rounds?: number
  snapshot_policy?: 'latest_per_model'
  max_concurrency?: number
  output_language?: string
  include_premortem?: boolean
  failure_date?: string
  chair_model: SeminarModelPortConfigInput
  context_lines?: string[]
  chair_mode?: SeminarChairMode
  max_stage_calls?: number
  max_tokens?: number
  max_retries?: number
  retry_backoff_seconds?: number
  near_duplicate_threshold?: number
}

export interface SeminarCreateRead {
  seminar_id: string
  run_id: string
  status: string
  case_snapshot_hash: string
  topic: string
  roster: SeminarRosterEntry[]
  config: SeminarConfigRead
  chair_model: SeminarModelPortConfig
}

export interface AdvanceModelRead {
  model_id: string
  round_no: number
  status: string
  board_snapshot_seq: number
}

export interface AdvanceRead {
  seminar_id: string
  wave_no: number
  per_model: AdvanceModelRead[]
  status: string
}

export interface FinalizeModelRead {
  model_id: string
  status: string
  error: Record<string, unknown> | null
}

export interface FinalizeRead {
  seminar_id: string
  finals: FinalizeModelRead[]
  status: string
}

export interface SynthesizeRequest {
  allow_partial?: boolean
  deterministic_fallback?: boolean
}

export interface PrepassItemRead {
  item_id: string
  model_id: string
  round_no: number
  field: string
  text: string
  normalized_text: string
}

export interface PrepassRead {
  items: PrepassItemRead[]
  exact_groups: string[][]
  exact_duplicate_groups: number
  near_duplicate_groups: string[][]
  near_duplicate_group_count: number
  near_duplicate_threshold: number
  item_count: number
  // Added by _synthesis_inputs: dissent "None" placeholders excluded
  // from clustering (auditable, not silent).
  excluded_dissent_placeholders?: number
}

export interface ClusterSourceRead {
  item_id: string
  model_id: string
  round_no: number
  field: string
  stance: string
  original_text: string
}

export interface CanonicalClaimRead {
  claim: string
  sources: ClusterSourceRead[]
  merge_map: string[]
}

export interface DisagreementPositionRead {
  stance: string
  sources: Array<{ model_id: string; round_no: number; field: string; original_text: string }>
}

export interface DisagreementRead {
  claim_index: number
  claim: string
  stances: string[]
  positions: DisagreementPositionRead[]
}

export interface ClustersRead {
  claims: CanonicalClaimRead[]
  disagreements: DisagreementRead[]
  merge_map: Record<string, number>
  prepass: PrepassRead
  production: string
  stage?: Record<string, unknown> | null
}

export interface RecommendationAgreementRead {
  n_models: number
  pairs_total: number
  pairs_agreeing: number
  rate: number | null
}

export interface BordaRead {
  method: string
  n_models: number
  totals: Record<string, number>
  ranked: string[]
}

export interface DedupStatisticsRead {
  original_items: number
  canonical_claims: number
  exact_duplicate_groups: number
  semantic_merge_groups: number
  cluster_production: string
}

export interface AbsentModelRead {
  model_id: string
  status: string
  reason: string
}

export interface RoundStatisticsRead {
  per_model: Record<
    string,
    { rounds: number; status: string; board_snapshot_seqs: number[]; round_statuses: string[] }
  >
  total_rounds: number
}

export interface ComputedMetricsRead {
  recommendation_agreement: RecommendationAgreementRead
  confidence_distribution: Record<string, number>
  borda: BordaRead
  dedup: DedupStatisticsRead
  disagreement_count: number
  rounds: RoundStatisticsRead
  finals_used: number
  roster_size: number
  absent_models: AbsentModelRead[]
}

export interface FinalVerdictRead {
  recommendation: string
  ranked_alternatives: string[]
  confidence: string
  key_evidence: string[]
  load_bearing_assumptions: string[]
  kill_criteria: string[]
  dissent_held: string[]
  rounds_summary: string
  board_snapshot_seq: number
}

export interface StageRecordRead {
  stage: string
  template_id: string
  template_version: string
  contract_version: string
  output: Record<string, unknown>
  model: string | null
  usage: Record<string, unknown> | null
  duration_ms: number | null
  attempts: number | null
}

export interface BriefVerdictEntryRead {
  model_id: string
  verdict: FinalVerdictRead
  stage: StageRecordRead
  board_snapshot_seq: number
}

export interface ChairBriefRead {
  seminar_id: string
  brief_version: number
  brief_hash: string
  topic: string
  status: string
  chair_mode: string
  chair_model_id: string
  prepass: PrepassRead
  deterministic_clusters: ClustersRead
  disagreements: DisagreementRead[]
  computed_metrics: ComputedMetricsRead
  verdicts: BriefVerdictEntryRead[]
  participation_note: string
  absent_models: AbsentModelRead[]
  finals_used: number
  roster_size: number
  partial: boolean
  submit_endpoint: string
}

export interface ChairSynthesisRequest {
  clusters: Record<string, unknown>
  synthesis: Record<string, unknown>
  brief_version?: number | null
}

export interface SynthesizeRead {
  report_id: string
  seminar_id: string
  version: number
  partial: boolean
  agreement_level: string | null
  production_path: string
  cluster_production: string
  fallback_reason: string | null
  report_hash: string
  chair_model_id: string
  status: string
}

export interface SeminarModelProgress {
  model_id: string
  status: string
  rounds: number
  has_final: boolean
  latest_board_seq: number | null
}

export interface SeminarReportSummary {
  version: number
  partial: boolean
  production_path: string
  cluster_production: string
  report_hash: string
  chair_model_id: string
}

export interface SeminarBudgetsRead {
  max_stage_calls: number
  stage_calls_used: number
  stage_calls_remaining: number
  max_tokens: number
  tokens_used: number
  tokens_remaining: number
}

export interface SeminarDiagnosisRead {
  error_counts: Record<string, number>
  total_tokens: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_duration_ms: number
  stage_calls: number
  stage_call_attempts: number
  retries: number
  fallbacks: number
  queue_waits: number
}

export interface SeminarDetailRead {
  seminar_id: string
  run_id: string
  topic: string
  status: string
  case_snapshot_hash: string
  roster: SeminarRosterEntry[]
  config: SeminarConfigRead
  chair_model: SeminarModelPortConfig
  per_model: SeminarModelProgress[]
  board_publications: number
  board_latest_seq: number
  finals_count: number
  reports: SeminarReportSummary[]
  budgets: SeminarBudgetsRead
  diagnosis: SeminarDiagnosisRead
}

export interface SeminarSummaryRead {
  seminar_id: string
  run_id: string
  topic: string
  status: string
  roster_size: number
  finals_count: number
  report_versions: number
}

export interface BoardDigestRead {
  model_id: string
  round_no: number
  recommendation: string
  confidence: 'low' | 'medium' | 'high' | null
  key_arguments: string[]
  kill_criteria: string[]
  changes: string[]
  reflection_missing: boolean
  board_snapshot_seq: number
}

export interface BoardRowRead {
  id: string
  seminar_id: string
  seq: number
  model_id: string
  round_no: number
  digest: BoardDigestRead
}

export interface ReflectionRead {
  critique: Array<{ weak_point: string; reason: string }>
  responses: Array<{ model_id: string; stance: string; reason: string }>
  changes: string[]
  confidence: string
  confidence_basis: string
  open_questions: string[]
}

export interface RoundErrorRead {
  kind: string
  stage: string | null
  message: string
}

export interface RoundRowRead {
  id: string
  seminar_id: string
  model_id: string
  round_no: number
  board_snapshot_seq: number
  stages: StageRecordRead[]
  reflection: ReflectionRead | null
  reflection_stage: StageRecordRead | null
  status: string
  error: RoundErrorRead | null
}

export interface FinalRowRead {
  id: string
  seminar_id: string
  model_id: string
  verdict: FinalVerdictRead
  stage: StageRecordRead
  board_snapshot_seq: number
  status: string
}

export type SeminarProvenance = 'computed' | 'deliberated' | 'template'

export interface SynthesisEvidenceItemRead {
  text: string
  source_models: string[]
}

export interface SeminarSynthesisRead {
  unified_recommendation: string
  recommendation_basis: string
  agreement_level: string
  alternatives_ranked: string[]
  aggregation_rule: string
  key_evidence: SynthesisEvidenceItemRead[]
  kill_criteria: SynthesisEvidenceItemRead[]
  minority_report: string
  open_questions: string[]
  chair_notes: string
}

export interface SeminarReportDocument {
  header: {
    seminar_id: string
    run_id: string
    topic: string
    version: number
    partial: boolean
    chair_model_id: string
    chair_mode: string
    chair_participates: boolean
    production_path: string
    cluster_production: string
    report_hash: string
    finals_used: number
    roster_size: number
    absent_models: AbsentModelRead[]
    brief_version?: number
    brief_hash?: string | null
    chair_provenance_note?: string
    chair_participation_flag?: string
    fallback_reason?: string
  }
  unified_recommendation: { text: string; basis: string | null; provenance: SeminarProvenance }
  agreement: {
    chair_level: string | null
    chair_provenance: SeminarProvenance
    computed: RecommendationAgreementRead | null
    computed_provenance: SeminarProvenance
    note: string
  }
  canonical_claims: {
    claims: CanonicalClaimRead[]
    merge_map: Record<string, number>
    provenance: SeminarProvenance
    production: string
  }
  disagreements: {
    items: DisagreementRead[]
    count: number
    provenance: SeminarProvenance
    note: string
  }
  alternatives: {
    borda: BordaRead | null
    borda_provenance: SeminarProvenance
    chair_ranked: string[] | null
    aggregation_rule: string
    chair_provenance: SeminarProvenance
  }
  key_evidence: { items: SynthesisEvidenceItemRead[]; provenance: SeminarProvenance }
  kill_criteria: { items: SynthesisEvidenceItemRead[]; provenance: SeminarProvenance }
  minority_report: { text: string; provenance: SeminarProvenance; verbatim: boolean }
  rounds_evolution: Array<{
    model_id: string
    rounds_summary: string
    board_snapshot_seq: number
    verbatim: boolean
  }>
  open_questions: { items: string[]; provenance: SeminarProvenance; note?: string }
  chair_notes: { text: string; provenance: SeminarProvenance }
  chair_synthesis: SeminarSynthesisRead | null
  computed_metrics: ComputedMetricsRead
  audit_appendix: {
    case_snapshot_hash: string
    cluster_stage: Record<string, unknown> | null
    synthesis_stage: Record<string, unknown> | null
    verdict_stages: Array<{
      model_id: string
      template_id: string
      template_version: string
      contract_version: string
      model: string | null
    }>
    round_stage_counts: Record<string, number>
    board_seq_range: number[]
    board_publications: number
    model_configs: Array<Record<string, unknown>>
    chair_config: Record<string, unknown>
    token_usage: Record<string, unknown> | string
  }
}

export interface ReportDetailRead {
  report_id: string
  seminar_id: string
  version: number
  partial: boolean
  chair_model_id: string
  report_hash: string
  document: SeminarReportDocument
}

export interface AuditEventRead {
  id: string
  seminar_id: string
  seq: number
  model_id: string | null
  stage: string | null
  kind: string
  detail: Record<string, unknown>
  round_no: number | null
  stage_call_id: string | null
  created_at: string
}
