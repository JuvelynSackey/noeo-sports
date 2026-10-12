"use client";

import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { StrengthChart } from "@/components/teams/StrengthChart";
import { useAuth } from "@/lib/auth";
import { ApiError, getCompetitions, getFixtures, getTeam, getTeamStrength } from "@/lib/api";
import type { Competition, Team, TeamStrength } from "@/lib/types";

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

interface TeamOption {
  canonical_team_id: string;
  current_name: string;
}

function TeamsContent() {
  const { token } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [competition, setCompetition] = useState("");
  const [teamOptions, setTeamOptions] = useState<TeamOption[]>([]);
  const [teamId, setTeamId] = useState("");
  const [team, setTeam] = useState<Team | null>(null);
  const [strength, setStrength] = useState<TeamStrength[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    if (!token || !competition) return;
    getFixtures(token, { competition })
      .then((fixtures) => {
        const seen = new Map<string, string>();
        for (const f of fixtures) {
          seen.set(f.home_team.canonical_team_id, f.home_team.current_name);
          seen.set(f.away_team.canonical_team_id, f.away_team.current_name);
        }
        setTeamOptions(
          Array.from(seen, ([canonical_team_id, current_name]) => ({
            canonical_team_id,
            current_name,
          })).sort((a, b) => a.current_name.localeCompare(b.current_name))
        );
      })
      .catch(() => setTeamOptions([]));
  }, [token, competition]);

  useEffect(() => {
    if (!token || !teamId) return;
    Promise.all([
      getTeam(teamId, token),
      getTeamStrength(teamId, token, competition || undefined),
    ])
      .then(([t, s]) => {
        setTeam(t);
        setStrength(s);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)));
  }, [token, teamId, competition]);

  if (!token) return null;

  const latest = strength[0] ?? null;

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">Teams</h1>
      <p className="mb-4 text-sm text-slate-500">
        Team identity and dynamic strength ratings (section 9) — attack/
        defence strength, home/away splits, opponent-adjusted and
        recency-weighted variants, and their estimation uncertainty.
        There&rsquo;s no team-level form table or forecast here — that&rsquo;s
        what the competition&rsquo;s fixtures list and Match Intelligence are
        for.
      </p>

      <div className="mb-6 flex flex-wrap gap-2">
        <select
          value={competition}
          onChange={(e) => {
            setCompetition(e.target.value);
            setTeamId("");
            setTeam(null);
            setStrength([]);
            setTeamOptions([]);
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
        <select
          value={teamId}
          onChange={(e) => {
            setTeamId(e.target.value);
            setTeam(null);
            setStrength([]);
          }}
          disabled={!competition}
          className={inputClass}
        >
          <option value="">Select a team…</option>
          {teamOptions.map((t) => (
            <option key={t.canonical_team_id} value={t.canonical_team_id}>
              {t.current_name}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {!competition && !error && (
        <p className="text-sm text-slate-500">
          Pick a competition, then a team, to see its strength ratings.
        </p>
      )}

      {team && (
        <>
          <Card title={team.current_name} className="mb-6">
            <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
              <span className="text-slate-400">{team.country ?? "Unknown country"}</span>
              {team.is_reserve_team && <StatusBadge value="RESERVE_TEAM" />}
              {team.is_dissolved && <StatusBadge value="DISSOLVED" />}
            </div>
            {latest ? (
              <table className="w-full text-sm">
                <tbody>
                  <tr className="border-t border-slate-800">
                    <td className="py-1 text-slate-500">Attack / defence strength</td>
                    <td className="py-1 text-slate-200">
                      {num(latest.attack_strength)} / {num(latest.defence_strength)}
                    </td>
                  </tr>
                  <tr className="border-t border-slate-800">
                    <td className="py-1 text-slate-500">Home / away strength</td>
                    <td className="py-1 text-slate-200">
                      {num(latest.home_strength)} / {num(latest.away_strength)}
                    </td>
                  </tr>
                  <tr className="border-t border-slate-800">
                    <td className="py-1 text-slate-500">
                      Opponent-adjusted / recent-form strength
                    </td>
                    <td className="py-1 text-slate-200">
                      {num(latest.opponent_adjusted_strength)} / {num(latest.recent_strength)}
                    </td>
                  </tr>
                  <tr className="border-t border-slate-800">
                    <td className="py-1 text-slate-500">Uncertainty</td>
                    <td className="py-1 text-slate-200">{num(latest.uncertainty)}</td>
                  </tr>
                  <tr className="border-t border-slate-800">
                    <td className="py-1 text-slate-500">Method / as of</td>
                    <td className="py-1 text-slate-200">
                      {latest.method ?? "—"} · {fmt(latest.as_of)}
                    </td>
                  </tr>
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-slate-500">
                No strength ratings recorded yet for this team.
              </p>
            )}
          </Card>

          <Card title="Strength over time">
            <StrengthChart points={strength} />
          </Card>
        </>
      )}
    </div>
  );
}

export default function TeamsPage() {
  return (
    <RequireAuth>
      <TeamsContent />
    </RequireAuth>
  );
}
