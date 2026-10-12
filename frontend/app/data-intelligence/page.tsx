"use client";

import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  ApiError,
  getCompetition,
  getCompetitions,
  getDataQuality,
  getLeagueParameters,
} from "@/lib/api";
import type { Competition, DataQuality, LeagueParameter } from "@/lib/types";

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function num(v: number | null | undefined, digits = 3): string {
  return v == null ? "—" : v.toFixed(digits);
}

function fmt(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : "—";
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

const inputClass =
  "rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200";

function DataIntelligenceContent() {
  const { token } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [competition, setCompetition] = useState("");
  const [seasonNames, setSeasonNames] = useState<Record<string, string>>({});
  const [dataQuality, setDataQuality] = useState<DataQuality[]>([]);
  const [leagueParameters, setLeagueParameters] = useState<LeagueParameter[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    if (!token || !competition) return;
    getCompetition(competition, token)
      .then((detail) => {
        const names: Record<string, string> = {};
        for (const s of detail.seasons) names[s.canonical_season_id] = s.name;
        setSeasonNames(names);
      })
      .catch(() => setSeasonNames({}));
    Promise.all([getDataQuality(token, competition), getLeagueParameters(token, competition)])
      .then(([dq, lp]) => {
        setDataQuality(dq);
        setLeagueParameters(lp);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)));
  }, [token, competition]);

  if (!token) return null;

  const issues = dataQuality.filter((dq) => dq.issues.length > 0);

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">Data Intelligence</h1>
      <p className="mb-4 text-sm text-slate-500">
        Data quality scoring and league baseline parameters by season
        (sections 15/11) — the inputs the forecasting models are actually
        conditioned on, not a forecast diagnostic itself. Recomputed on
        every sync (see the Admin Centre).
      </p>

      <select
        value={competition}
        onChange={(e) => setCompetition(e.target.value)}
        className={`mb-6 ${inputClass}`}
      >
        <option value="">Select a competition…</option>
        {competitions.map((c) => (
          <option key={c.canonical_competition_id} value={c.canonical_competition_id}>
            {c.name}
          </option>
        ))}
      </select>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {!competition && !error && (
        <p className="text-sm text-slate-500">
          Pick a competition above to see its data quality and league
          baselines.
        </p>
      )}

      {competition && (
        <>
          <Card title="Data quality" className="mb-6">
            {dataQuality.length === 0 ? (
              <p className="text-sm text-slate-500">
                No data-quality evaluation recorded yet — needs a full sync.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="pb-2">Season</th>
                    <th className="pb-2">Status</th>
                    <th className="pb-2">Overall</th>
                    <th className="pb-2">Completeness</th>
                    <th className="pb-2">Freshness</th>
                    <th className="pb-2">Source reliability</th>
                    <th className="pb-2">Team mapping</th>
                    <th className="pb-2">Fixture completeness</th>
                    <th className="pb-2">Evaluated</th>
                  </tr>
                </thead>
                <tbody>
                  {dataQuality.map((dq, i) => (
                    <tr key={i} className="border-t border-slate-800">
                      <td className="py-1.5 text-slate-200">
                        {seasonNames[dq.season_canonical_id] ?? dq.season_canonical_id}
                      </td>
                      <td className="py-1.5">
                        <StatusBadge value={dq.status} />
                      </td>
                      <td className="py-1.5 text-slate-400">{pct(dq.overall_score)}</td>
                      <td className="py-1.5 text-slate-400">{pct(dq.completeness)}</td>
                      <td className="py-1.5 text-slate-400">{pct(dq.freshness)}</td>
                      <td className="py-1.5 text-slate-400">{pct(dq.source_reliability)}</td>
                      <td className="py-1.5 text-slate-400">{pct(dq.team_mapping_quality)}</td>
                      <td className="py-1.5 text-slate-400">{pct(dq.fixture_completeness)}</td>
                      <td className="py-1.5 text-slate-400">{fmt(dq.evaluated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {issues.length > 0 && (
              <div className="mt-3 space-y-1">
                {issues.map((dq, i) => (
                  <p key={i} className="text-xs text-amber-400">
                    {seasonNames[dq.season_canonical_id] ?? dq.season_canonical_id}:{" "}
                    {dq.issues.join(", ")}
                  </p>
                ))}
              </div>
            )}
          </Card>

          <Card title="League baseline parameters">
            {leagueParameters.length === 0 ? (
              <p className="text-sm text-slate-500">
                No league baselines computed yet — needs a full sync.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="pb-2">Season</th>
                    <th className="pb-2">Avg home goals</th>
                    <th className="pb-2">Avg away goals</th>
                    <th className="pb-2">Avg total goals</th>
                    <th className="pb-2">Home advantage</th>
                    <th className="pb-2">Draw frequency</th>
                    <th className="pb-2">Scoring variance</th>
                    <th className="pb-2">Sample size</th>
                    <th className="pb-2">Shrinkage</th>
                    <th className="pb-2">Computed</th>
                  </tr>
                </thead>
                <tbody>
                  {leagueParameters.map((lp, i) => (
                    <tr key={i} className="border-t border-slate-800">
                      <td className="py-1.5 text-slate-200">
                        {seasonNames[lp.season_canonical_id] ?? lp.season_canonical_id}
                      </td>
                      <td className="py-1.5 text-slate-400">{num(lp.avg_home_goals, 2)}</td>
                      <td className="py-1.5 text-slate-400">{num(lp.avg_away_goals, 2)}</td>
                      <td className="py-1.5 text-slate-400">{num(lp.avg_total_goals, 2)}</td>
                      <td className="py-1.5 text-slate-400">{num(lp.home_advantage, 3)}</td>
                      <td className="py-1.5 text-slate-400">{pct(lp.draw_frequency)}</td>
                      <td className="py-1.5 text-slate-400">{num(lp.scoring_variance, 3)}</td>
                      <td className="py-1.5 text-slate-400">{lp.sample_size}</td>
                      <td className="py-1.5 text-slate-400">
                        {lp.shrinkage_applied ? "Yes" : "No"}
                      </td>
                      <td className="py-1.5 text-slate-400">{fmt(lp.computed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

export default function DataIntelligencePage() {
  return (
    <RequireAuth>
      <DataIntelligenceContent />
    </RequireAuth>
  );
}
