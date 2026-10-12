// Mirrors app/api/schemas.py on the backend. Kept hand-written rather than
// generated, since the backend's OpenAPI schema isn't wired into this
// frontend's build yet (a natural follow-up — see the README).

export interface TokenResponse {
  access_token: string;
  token_type: string;
  role: string;
  expires_at: string;
}

export interface SystemHealth {
  status: string;
  detail: string | null;
  data_provider: string;
  competitions_total: number;
  active_competitions: number;
  database_url_scheme: string;
  scheduler_enabled: boolean;
  next_scheduled_sync: string | null;
}

export interface Season {
  canonical_season_id: string;
  name: string;
  start_date: string | null;
  end_date: string | null;
  status: string;
}

export interface Competition {
  canonical_competition_id: string;
  name: string;
  country: string | null;
  competition_type: string;
  division_level: number | null;
  competition_format: string;
  status: string;
  data_quality_status: string;
  number_of_teams: number | null;
}

export interface CompetitionDetail extends Competition {
  seasons: Season[];
}

export interface Team {
  canonical_team_id: string;
  current_name: string;
  country: string | null;
  is_reserve_team: boolean;
  is_dissolved: boolean;
}

export interface Result {
  home_goals: number;
  away_goals: number;
  home_goals_first_half: number | null;
  away_goals_first_half: number | null;
}

export interface Fixture {
  canonical_fixture_id: string;
  round: string | null;
  kickoff_utc: string | null;
  status: string;
  home_team: Team;
  away_team: Team;
  result: Result | null;
}

export interface DataQuality {
  competition_canonical_id: string;
  season_canonical_id: string;
  overall_score: number;
  status: string;
  completeness: number | null;
  freshness: number | null;
  source_reliability: number | null;
  team_mapping_quality: number | null;
  fixture_completeness: number | null;
  issues: string[];
  evaluated_at: string;
}

export interface ExpectedGoals {
  home: number | null;
  away: number | null;
  total: number | null;
}

export interface Scoreline {
  home_goals: number;
  away_goals: number;
  probability: number;
}

export interface OutcomeDistribution {
  home_win: number;
  draw: number;
  away_win: number;
}

export interface GoalDistribution {
  buckets: Record<string, number>;
  expected_total_goals: number;
  median_total_goals: number;
  mode_total_goals: number;
  variance_total_goals: number;
  over_under: Record<string, number>;
  btts_probability: number;
  home_clean_sheet_probability: number;
  away_clean_sheet_probability: number;
  no_goals_probability: number;
}

export interface FirstHalfForecast {
  expected_goals_home: number;
  expected_goals_away: number;
  expected_goals_total: number;
  most_probable_score: Scoreline;
}

export interface RateMarketForecast {
  expected_home: number;
  expected_away: number;
  expected_total: number;
}

export interface ConformalInterval {
  point_estimate: number;
  lower: number;
  upper: number;
  target_coverage: number;
  empirical_coverage: number | null;
}

export interface ConformalForecast {
  home_goals: ConformalInterval | null;
  away_goals: ConformalInterval | null;
  total_goals: ConformalInterval | null;
  outcome_prediction_set: string[];
  outcome_target_coverage: number | null;
}

export interface ModelDiagnostics {
  model_disagreement: string | null;
  aleatoric_uncertainty: number | null;
  epistemic_uncertainty: number | null;
  data_quality_score: number | null;
  ood_status: boolean;
  ood_flags: string[];
  shock_status: boolean;
  shock_flags: string[];
}

export interface ModelInformation {
  champion_model: string | null;
  supporting_models: string[];
  ensemble_weights: Record<string, number>;
  model_version: string | null;
  dataset_version: string | null;
  feature_version: string;
  software_version: string;
  predicted_at: string;
}

export interface CalibrationDiagnostic {
  method: string;
  raw_home_win_probability: number;
  calibrated_home_win_probability: number;
  calibration_error: number | null;
  brier_score: number | null;
  log_loss: number | null;
}

export interface AdministratorNotes {
  warnings: string[];
  errors: string[];
  calibration: CalibrationDiagnostic | null;
}

export interface MatchForecast {
  prediction_id: string;
  competition_canonical_id: string;
  season_canonical_id: string;
  fixture_canonical_id: string;
  kickoff_utc: string | null;
  home_team: string;
  away_team: string;
  forecast_status: string;
  expected_goals: ExpectedGoals;
  most_probable_scorelines: Scoreline[];
  outcome_distribution: OutcomeDistribution | null;
  goal_distribution: GoalDistribution | null;
  first_half: FirstHalfForecast | null;
  corners: RateMarketForecast | null;
  cards: RateMarketForecast | null;
  conformal: ConformalForecast | null;
  model_diagnostics: ModelDiagnostics;
  model_information: ModelInformation;
  administrator_notes: AdministratorNotes;
}

// --- Model Lab (section 70) ---

export interface ModelVersionSummary {
  model_name: string;
  version: string;
  status: string;
  disabled_reason: string | null;
  competition_canonical_id: string | null;
  trained_at: string | null;
  training_window_start: string | null;
  training_window_end: string | null;
  evaluation_metrics: Record<string, unknown> | null;
  is_reproducible: boolean;
}

export interface ModelVersionDetail extends ModelVersionSummary {
  hyperparameters: Record<string, unknown> | null;
  parameters: {
    attack?: Record<string, number>;
    defence?: Record<string, number>;
    home_advantage?: number;
    rho?: number;
    team_ids?: string[];
  } | null;
}

export interface ModelPerformance {
  competition_canonical_id: string;
  model_name: string;
  model_version: string;
  ensemble_weight: number | null;
  brier_score: number | null;
  log_loss: number | null;
  ranked_probability_score: number | null;
  n_folds: number | null;
  n_predictions: number | null;
  exact_score_mean_probability: number | null;
  total_goals_rmse: number | null;
  evaluated_at: string;
}

export interface ReliabilityPoint {
  [key: string]: number;
}

export interface Backtest {
  competition_canonical_id: string;
  model_name: string;
  model_version: string;
  n_folds: number | null;
  n_predictions: number | null;
  brier_score: number | null;
  log_loss: number | null;
  ranked_probability_score: number | null;
  calibration_error: number | null;
  exact_score_mean_log_loss: number | null;
  exact_score_mean_probability: number | null;
  home_goal_residual_mean: number | null;
  home_goal_residual_std: number | null;
  away_goal_residual_mean: number | null;
  away_goal_residual_std: number | null;
  total_goals_rmse: number | null;
  reliability_curve: ReliabilityPoint[] | null;
  evaluated_at: string;
}

export interface Calibration {
  competition_canonical_id: string;
  model_name: string;
  model_version: string;
  method: string;
  brier_score: number | null;
  log_loss: number | null;
  ranked_probability_score: number | null;
  calibration_error: number | null;
  reliability_curve: ReliabilityPoint[] | null;
  evaluated_at: string;
}

export interface ConformalCalibrationDiagnostic {
  competition_canonical_id: string;
  model_name: string;
  model_version: string;
  target: string;
  method: string;
  alpha: number;
  quantile: number;
  n_calibration: number;
  n_test: number;
  empirical_coverage: number | null;
  evaluated_at: string;
}

export interface Monitoring {
  competition_canonical_id: string;
  model_name: string;
  model_version: string;
  metric_name: string;
  metric_value: number;
  threshold: number | null;
  breached: boolean;
  detail: Record<string, unknown> | null;
  evaluated_at: string;
}

export interface AuditLog {
  actor_email: string | null;
  actor_role: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  occurred_at: string;
}
