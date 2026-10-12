// Thin client for the Noeo Sports FastAPI backend. Every call that isn't
// POST /auth/token or GET /system-health requires a bearer token (section
// 54 of the backend's own spec) — this client never fabricates one, and
// ApiError carries the backend's own `detail` message rather than a
// generic "request failed" string, so callers can surface the real reason
// (e.g. "no ENABLED dixon_coles model for this competition").

import type {
  Competition,
  CompetitionDetail,
  DataQuality,
  Fixture,
  MatchForecast,
  SystemHealth,
  TokenResponse,
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
