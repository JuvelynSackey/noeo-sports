"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  ApiError,
  getCompetitions,
  getFixtures,
  getPrediction,
  postForecast,
} from "@/lib/api";
import type { Competition, Fixture, MatchForecast } from "@/lib/types";

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(0)}%`;
}

function num(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

function formatKickoff(iso: string | null): string {
  if (!iso) return "TBD";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

const inputClass =
  "rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200";
const buttonSecondaryClass =
  "rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300 transition hover:border-cyan-500 hover:text-cyan-400 disabled:opacity-50";

function ForecastCentreContent() {
  const { token } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [competition, setCompetition] = useState("");
  const [fixtures, setFixtures] = useState<Fixture[]>([]);
  const [forecasts, setForecasts] = useState<Record<string, MatchForecast | null>>({});
  const [generating, setGenerating] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    if (!token || !competition) return;
    getFixtures(token, { competition, status: "SCHEDULED" })
      .then((fx) => {
        setFixtures(fx);
        return Promise.all(
          fx.map((f) =>
            getPrediction(f.canonical_fixture_id, token)
              .then((p) => [f.canonical_fixture_id, p] as const)
              .catch(() => [f.canonical_fixture_id, null] as const)
          )
        );
      })
      .then((pairs) => {
        const map: Record<string, MatchForecast | null> = {};
        for (const [id, p] of pairs) map[id] = p;
        setForecasts(map);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
  }, [token, competition]);

  function generate(fixtureId: string) {
    if (!token) return;
    setGenerating((g) => ({ ...g, [fixtureId]: true }));
    postForecast(fixtureId, token)
      .then((p) => setForecasts((f) => ({ ...f, [fixtureId]: p })))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setGenerating((g) => ({ ...g, [fixtureId]: false })));
  }

  function generateAll() {
    const missing = fixtures.filter((f) => forecasts[f.canonical_fixture_id] === null);
    for (const f of missing) generate(f.canonical_fixture_id);
  }

  const missingCount = fixtures.filter((f) => forecasts[f.canonical_fixture_id] === null).length;

  if (!token) return null;

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">Forecast Centre</h1>
      <p className="mb-4 text-sm text-slate-500">
        Every upcoming (SCHEDULED) fixture in a competition, one row per
        match, so a forecast doesn&rsquo;t require visiting Match
        Intelligence one fixture at a time. A row with no forecast yet
        means no one has called <code>POST /forecast</code> for it —
        generate it here, or click through for the full breakdown
        (expected-goals distribution, conformal intervals, model
        diagnostics).
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select
          value={competition}
          onChange={(e) => {
            setCompetition(e.target.value);
            setFixtures([]);
            setForecasts({});
            setLoading(!!e.target.value);
          }}
          className={inputClass}
        >
          <option value="">Select a competition…</option>
          {competitions.map((c) => (
            <option key={c.canonical_competition_id} value={c.canonical_competition_id}>
              {c.name}
            </option>
          ))}
        </select>
        {missingCount > 0 && (
          <button onClick={generateAll} className={buttonSecondaryClass}>
            Generate all missing ({missingCount})
          </button>
        )}
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {!competition && !error && (
        <p className="text-sm text-slate-500">
          Pick a competition above to see its upcoming fixtures and
          forecasts.
        </p>
      )}

      {competition && loading && fixtures.length === 0 && (
        <p className="text-sm text-slate-500">Loading fixtures…</p>
      )}

      {competition && !loading && fixtures.length === 0 && !error && (
        <p className="text-sm text-slate-500">No upcoming fixtures scheduled.</p>
      )}

      {fixtures.length > 0 && (
        <div className="divide-y divide-slate-800 rounded-xl border border-slate-800">
          {fixtures.map((f) => {
            const forecast = forecasts[f.canonical_fixture_id];
            const isGenerating = !!generating[f.canonical_fixture_id];
            return (
              <div
                key={f.canonical_fixture_id}
                className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
              >
                <div className="min-w-48">
                  <p className="text-sm text-white">
                    {f.home_team.current_name}{" "}
                    <span className="text-slate-500">vs</span>{" "}
                    {f.away_team.current_name}
                  </p>
                  <p className="text-xs text-slate-500">{formatKickoff(f.kickoff_utc)}</p>
                </div>

                {forecast === undefined ? (
                  <p className="text-xs text-slate-500">Loading…</p>
                ) : forecast === null ? (
                  <button
                    onClick={() => generate(f.canonical_fixture_id)}
                    disabled={isGenerating}
                    className={buttonSecondaryClass}
                  >
                    {isGenerating ? "Generating…" : "Generate forecast"}
                  </button>
                ) : (
                  <>
                    <div className="text-sm text-slate-300">
                      {num(forecast.expected_goals.home)} – {num(forecast.expected_goals.away)}
                    </div>
                    {forecast.outcome_distribution && (
                      <div className="text-sm text-slate-400">
                        H {pct(forecast.outcome_distribution.home_win)} · D{" "}
                        {pct(forecast.outcome_distribution.draw)} · A{" "}
                        {pct(forecast.outcome_distribution.away_win)}
                      </div>
                    )}
                    <div className="flex items-center gap-1.5">
                      <StatusBadge value={forecast.model_diagnostics.model_disagreement} />
                      {forecast.model_diagnostics.ood_status && (
                        <span className="rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-xs text-amber-400">
                          OOD
                        </span>
                      )}
                      {forecast.model_diagnostics.shock_status && (
                        <span className="rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-xs text-amber-400">
                          Shock
                        </span>
                      )}
                    </div>
                  </>
                )}

                <Link
                  href={`/fixtures/${encodeURIComponent(f.canonical_fixture_id)}`}
                  className="text-xs text-cyan-400 hover:text-cyan-300"
                >
                  View →
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ForecastCentrePage() {
  return (
    <RequireAuth>
      <ForecastCentreContent />
    </RequireAuth>
  );
}
