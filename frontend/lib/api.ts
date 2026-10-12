// Thin client for the Noeo Sports FastAPI backend. Every call that isn't
// POST /auth/token or GET /system-health requires a bearer token (section
// 54 of the backend's own spec) — this client never fabricates one, and
// ApiError carries the backend's own `detail` message rather than a
// generic "request failed" string, so callers can surface the real reason
// (e.g. "no ENABLED dixon_coles model for this competition").

import type {
  AuditLog,
  Backtest,
  Calibration,
  Competition,
  CompetitionDetail,
  ConformalCalibrationDiagnostic,
  DataQuality,
  Fixture,
  Job,
  LeagueParameter,
  MatchForecast,
  ModelPerformance,
  ModelVersionDetail,
  ModelVersionSummary,
  Monitoring,
  Scenario,
  SimulationRun,
  SyncReport,
  SystemHealth,
  Team,
  TeamStrength,
  TokenResponse,
  User,
  UserCreateIn,
  UserUpdateIn,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // body wasn't JSON — fall back to statusText
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function login(
  email: string,
  password: string
): Promise<TokenResponse> {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);
  return request<TokenResponse>("/auth/token", {
    method: "POST",
    body: form,
  });
}

export function getSystemHealth(): Promise<SystemHealth> {
  return request<SystemHealth>("/system-health");
}

export function getCompetitions(token: string): Promise<Competition[]> {
  return request<Competition[]>("/competitions", {}, token);
}

export function getCompetition(
  id: string,
  token: string
): Promise<CompetitionDetail> {
  return request<CompetitionDetail>(
    `/competitions/${encodeURIComponent(id)}`,
    {},
    token
  );
}

export function getFixtures(
  token: string,
  params: { competition?: string; season?: string; status?: string } = {}
): Promise<Fixture[]> {
  const query = new URLSearchParams();
  if (params.competition) query.set("competition", params.competition);
  if (params.season) query.set("season", params.season);
  if (params.status) query.set("status", params.status);
  const qs = query.toString();
  return request<Fixture[]>(`/fixtures${qs ? `?${qs}` : ""}`, {}, token);
}

export function getFixture(id: string, token: string): Promise<Fixture> {
  return request<Fixture>(`/fixtures/${encodeURIComponent(id)}`, {}, token);
}

export function getDataQuality(
  token: string,
  competition?: string
): Promise<DataQuality[]> {
  const qs = competition
    ? `?competition=${encodeURIComponent(competition)}`
    : "";
  return request<DataQuality[]>(`/data-quality${qs}`, {}, token);
}

export function getTeam(teamId: string, token: string): Promise<Team> {
  return request<Team>(`/teams/${encodeURIComponent(teamId)}`, {}, token);
}

export function getTeamStrength(
  teamId: string,
  token: string,
  competition?: string
): Promise<TeamStrength[]> {
  const qs = competition
    ? `?competition=${encodeURIComponent(competition)}`
    : "";
  return request<TeamStrength[]>(
    `/teams/${encodeURIComponent(teamId)}/strength${qs}`,
    {},
    token
  );
}

export function getLeagueParameters(
  token: string,
  competition?: string
): Promise<LeagueParameter[]> {
  const qs = competition
    ? `?competition=${encodeURIComponent(competition)}`
    : "";
  return request<LeagueParameter[]>(`/league-parameters${qs}`, {}, token);
}

export function getPrediction(
  fixtureId: string,
  token: string
): Promise<MatchForecast> {
  return request<MatchForecast>(
    `/predictions/${encodeURIComponent(fixtureId)}`,
    {},
    token
  );
}

export function postForecast(
  fixtureId: string,
  token: string
): Promise<MatchForecast> {
  return request<MatchForecast>(
    `/forecast?fixture=${encodeURIComponent(fixtureId)}`,
    { method: "POST" },
    token
  );
}

// --- Model Lab (section 70) ---

export function getModels(
  token: string,
  params: { competition?: string; model_name?: string; status?: string } = {}
): Promise<ModelVersionSummary[]> {
  const query = new URLSearchParams();
  if (params.competition) query.set("competition", params.competition);
  if (params.model_name) query.set("model_name", params.model_name);
  if (params.status) query.set("status", params.status);
  const qs = query.toString();
  return request<ModelVersionSummary[]>(`/models${qs ? `?${qs}` : ""}`, {}, token);
}

/** ADMIN/ANALYST only on the backend — callers should expect this to
 * reject with a 403 ApiError for a VIEWER and surface that, not hide the
 * page entirely (the list above is open to any authenticated role). */
export function getModelVersion(
  version: string,
  token: string
): Promise<ModelVersionDetail> {
  return request<ModelVersionDetail>(
    `/models/${encodeURIComponent(version)}`,
    {},
    token
  );
}

/** ADMIN only on the backend. */
export function rollbackModel(
  version: string,
  token: string
): Promise<ModelVersionDetail> {
  return request<ModelVersionDetail>(
    `/models/${encodeURIComponent(version)}/rollback`,
    { method: "POST" },
    token
  );
}

export function getModelPerformance(
  token: string,
  competition?: string
): Promise<ModelPerformance[]> {
  const qs = competition
    ? `?competition=${encodeURIComponent(competition)}`
    : "";
  return request<ModelPerformance[]>(`/model-performance${qs}`, {}, token);
}

export function getBacktests(
  token: string,
  params: { competition?: string; model_name?: string } = {}
): Promise<Backtest[]> {
  const query = new URLSearchParams();
  if (params.competition) query.set("competition", params.competition);
  if (params.model_name) query.set("model_name", params.model_name);
  const qs = query.toString();
  return request<Backtest[]>(`/backtests${qs ? `?${qs}` : ""}`, {}, token);
}

export function getCalibration(
  token: string,
  competition?: string
): Promise<Calibration[]> {
  const qs = competition
    ? `?competition=${encodeURIComponent(competition)}`
    : "";
  return request<Calibration[]>(`/calibration${qs}`, {}, token);
}

export function getConformal(
  token: string,
  params: { competition?: string; target?: string } = {}
): Promise<ConformalCalibrationDiagnostic[]> {
  const query = new URLSearchParams();
  if (params.competition) query.set("competition", params.competition);
  if (params.target) query.set("target", params.target);
  const qs = query.toString();
  return request<ConformalCalibrationDiagnostic[]>(
    `/conformal${qs ? `?${qs}` : ""}`,
    {},
    token
  );
}

/** ADMIN/ANALYST only on the backend. */
export function getMonitoring(
  token: string,
  params: {
    competition?: string;
    model_name?: string;
    metric_name?: string;
    breached_only?: boolean;
  } = {}
): Promise<Monitoring[]> {
  const query = new URLSearchParams();
  if (params.competition) query.set("competition", params.competition);
  if (params.model_name) query.set("model_name", params.model_name);
  if (params.metric_name) query.set("metric_name", params.metric_name);
  if (params.breached_only) query.set("breached_only", "true");
  const qs = query.toString();
  return request<Monitoring[]>(`/monitoring${qs ? `?${qs}` : ""}`, {}, token);
}

/** ADMIN only on the backend. */
export function getAuditLogs(
  token: string,
  params: { action?: string; actor_email?: string } = {}
): Promise<AuditLog[]> {
  const query = new URLSearchParams();
  if (params.action) query.set("action", params.action);
  if (params.actor_email) query.set("actor_email", params.actor_email);
  const qs = query.toString();
  return request<AuditLog[]>(`/audit-logs${qs ? `?${qs}` : ""}`, {}, token);
}

// --- Admin Centre (sections 19/72) ---

/** ADMIN only on the backend. */
export function getUsers(token: string): Promise<User[]> {
  return request<User[]>("/users", {}, token);
}

/** ADMIN only on the backend. Can't create the first ADMIN account this
 * way — see `scripts/create_admin.py` on the backend for bootstrapping. */
export function createUser(
  payload: UserCreateIn,
  token: string
): Promise<User> {
  return request<User>(
    "/users",
    { method: "POST", body: JSON.stringify(payload) },
    token
  );
}

/** ADMIN only on the backend. */
export function updateUser(
  userId: number,
  payload: UserUpdateIn,
  token: string
): Promise<User> {
  return request<User>(
    `/users/${userId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
    token
  );
}

/** ADMIN only on the backend. Runs the full sync pipeline in-request —
 * this call blocks until it finishes. */
export function triggerSync(token: string): Promise<SyncReport> {
  return request<SyncReport>("/sync", { method: "POST" }, token);
}

/** ADMIN only on the backend. Enqueues the same sync instead of blocking;
 * 503s if REDIS_URL isn't configured (no job queue backing it). Poll the
 * returned job via `getJob`. */
export function triggerSyncAsync(token: string): Promise<Job> {
  return request<Job>("/sync/async", { method: "POST" }, token);
}

/** Any authenticated role. 503s if REDIS_URL isn't configured. */
export function getJob(jobId: string, token: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(jobId)}`, {}, token);
}

/** ADMIN only on the backend. 503s if REDIS_URL isn't configured. */
export function listDeadLetterJobs(token: string): Promise<Job[]> {
  return request<Job[]>("/jobs/dead-letter", {}, token);
}

// --- Scenarios & season simulations (sections 42/59) ---

/** Requires a baseline forecast (`POST /forecast`) to already exist for
 * this fixture — 422s otherwise. Deltas may only name the fixture's own
 * two teams and must stay within the backend's configured bound
 * (`scenario_max_abs_delta`); both constraints are enforced server-side
 * and surfaced via the 422's own `detail` message rather than duplicated
 * here. */
export function runScenario(
  fixtureId: string,
  payload: {
    scenario_name: string;
    home_advantage_delta?: number;
    attack_delta?: Record<string, number>;
    defence_delta?: Record<string, number>;
  },
  token: string
): Promise<Scenario> {
  return request<Scenario>(
    `/scenarios?fixture=${encodeURIComponent(fixtureId)}`,
    { method: "POST", body: JSON.stringify(payload) },
    token
  );
}

export function getScenarios(fixtureId: string, token: string): Promise<Scenario[]> {
  return request<Scenario[]>(`/scenarios/${encodeURIComponent(fixtureId)}`, {}, token);
}

interface SimulationParams {
  competition: string;
  season?: string;
  n_simulations?: number;
  random_seed?: number;
}

function simulationQuery(params: SimulationParams): string {
  const query = new URLSearchParams();
  query.set("competition", params.competition);
  if (params.season) query.set("season", params.season);
  if (params.n_simulations != null) query.set("n_simulations", String(params.n_simulations));
  if (params.random_seed != null) query.set("random_seed", String(params.random_seed));
  return query.toString();
}

/** Blocks until the simulation finishes — can take a while at the
 * backend's default `n_simulations` (10,000). */
export function runSimulation(params: SimulationParams, token: string): Promise<SimulationRun> {
  return request<SimulationRun>(
    `/simulations?${simulationQuery(params)}`,
    { method: "POST" },
    token
  );
}

/** Enqueues the same simulation instead of blocking; 503s if REDIS_URL
 * isn't configured. Poll the returned job via `getJob`; once SUCCEEDED,
 * `job.result.scenario_id` is what to pass to `getSimulation`. */
export function runSimulationAsync(params: SimulationParams, token: string): Promise<Job> {
  return request<Job>(
    `/simulations/async?${simulationQuery(params)}`,
    { method: "POST" },
    token
  );
}

export function getSimulation(scenarioId: string, token: string): Promise<SimulationRun> {
  return request<SimulationRun>(`/simulations/${encodeURIComponent(scenarioId)}`, {}, token);
}

export function getSimulations(token: string, competition?: string): Promise<SimulationRun[]> {
  const qs = competition ? `?competition=${encodeURIComponent(competition)}` : "";
  return request<SimulationRun[]>(`/simulations${qs}`, {}, token);
}
