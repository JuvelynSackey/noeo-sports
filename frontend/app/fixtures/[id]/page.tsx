"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { Disclaimer } from "@/components/Disclaimer";
import { OutcomeChart } from "@/components/forecast/OutcomeChart";
import { GoalBucketsChart } from "@/components/forecast/GoalBucketsChart";
import { useAuth } from "@/lib/auth";
import { ApiError, getFixture, getPrediction, postForecast } from "@/lib/api";
import type { Fixture, MatchForecast } from "@/lib/types";

function formatKickoff(iso: string | null): string {
  if (!iso) return "TBD";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "full",
    timeStyle: "short",
  });
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function num(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

function MatchIntelligenceContent({ fixtureId }: { fixtureId: string }) {
  const { token } = useAuth();
  const [fixture, setFixture] = useState<Fixture | null>(null);
  const [forecast, setForecast] = useState<MatchForecast | null>(null);
  const [noForecastYet, setNoForecastYet] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getFixture(fixtureId, token)
      .then((f) => !cancelled && setFixture(f))
      .catch((err) => !cancelled && setError(String(err)));
    getPrediction(fixtureId, token)
      .then((p) => !cancelled && setForecast(p))
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setNoForecastYet(true);
        } else {
          setError(String(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fixtureId, token]);

  const generateForecast = useCallback(async () => {
    if (!token) return;
    setIsGenerating(true);
    setError(null);
    try {
      const result = await postForecast(fixtureId, token);
      setForecast(result);
      setNoForecastYet(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setIsGenerating(false);
    }
  }, [fixtureId, token]);

  return (
    <div className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
      <Link
        href={
          forecast
            ? `/competitions/${encodeURIComponent(forecast.competition_canonical_id)}`
            : "/"
        }
        className="text-sm text-slate-500 hover:text-cyan-400"
      >
        ← Back
      </Link>

      {fixture && (
        <div className="mt-2 mb-2 flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold text-white">
            {fixture.home_team.current_name} vs {fixture.away_team.current_name}
          </h1>
          <StatusBadge value={fixture.status} />
        </div>
      )}
      {fixture && (
        <p className="mb-4 text-sm text-slate-500">
          {formatKickoff(fixture.kickoff_utc)}
          {fixture.result &&
            ` · Final score: ${fixture.result.home_goals}–${fixture.result.away_goals}`}
        </p>
      )}

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {noForecastYet && !forecast && (
        <Card className="mb-6">
          <p className="mb-3 text-sm text-slate-400">
            No forecast has been generated for this fixture yet.
          </p>
          <button
            onClick={generateForecast}
            disabled={isGenerating}
            className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-60"
          >
            {isGenerating ? "Generating…" : "Generate forecast"}
          </button>
        </Card>
      )}

      {forecast && (
        <>
          <div className="mb-2 flex items-center gap-2">
            <StatusBadge value={forecast.forecast_status} />
          </div>
          <button
            onClick={generateForecast}
            disabled={isGenerating}
            className="mb-6 rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-400 transition hover:border-cyan-500 hover:text-cyan-400 disabled:opacity-60"
          >
            {isGenerating ? "Regenerating…" : "Regenerate forecast"}
          </button>

          <div className="mb-3">
            <Disclaimer compact />
          </div>

          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Card title="Expected goals (home)">
              <p className="text-2xl font-semibold text-white">
                {num(forecast.expected_goals.home)}
              </p>
            </Card>
            <Card title="Expected goals (away)">
              <p className="text-2xl font-semibold text-white">
                {num(forecast.expected_goals.away)}
              </p>
            </Card>
            <Card title="Expected total goals">
              <p className="text-2xl font-semibold text-white">
                {num(forecast.expected_goals.total)}
              </p>
            </Card>
          </div>

          {forecast.outcome_distribution && (
            <Card title="1X2 outcome probabilities" className="mb-6">
              <OutcomeChart outcome={forecast.outcome_distribution} />
            </Card>
          )}

          {forecast.most_probable_scorelines.length > 0 && (
            <Card title="Most probable scorelines" className="mb-6">
              <p className="mb-2 text-xs text-slate-500">
                A summary of the score matrix — never a guaranteed result.
              </p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="pb-2">Scoreline</th>
                    <th className="pb-2">Probability</th>
                  </tr>
                </thead>
                <tbody>
                  {forecast.most_probable_scorelines.map((s, i) => (
                    <tr
                      key={`${s.home_goals}-${s.away_goals}`}
                      className="border-t border-slate-800"
                    >
                      <td className="py-1.5 text-slate-200">
                        {s.home_goals} – {s.away_goals}
                        {i === 0 && (
                          <span className="ml-2 text-xs text-cyan-400">
                            most probable
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 text-slate-400">
                        {pct(s.probability)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          {forecast.goal_distribution && (
            <Card title="Goal distribution" className="mb-6">
              <GoalBucketsChart buckets={forecast.goal_distribution.buckets} />
              <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <MiniStat
                  label="BTTS"
                  value={pct(forecast.goal_distribution.btts_probability)}
                />
                <MiniStat
                  label="Over 2.5"
                  value={pct(forecast.goal_distribution.over_under["over_2.5"])}
                />
                <MiniStat
                  label="Home clean sheet"
                  value={pct(
                    forecast.goal_distribution.home_clean_sheet_probability
                  )}
                />
                <MiniStat
                  label="Away clean sheet"
                  value={pct(
                    forecast.goal_distribution.away_clean_sheet_probability
                  )}
                />
              </div>
            </Card>
          )}

          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
            {forecast.first_half && (
              <Card title="First half">
                <p className="text-sm text-slate-300">
                  xG {num(forecast.first_half.expected_goals_home)} –{" "}
                  {num(forecast.first_half.expected_goals_away)}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Most probable:{" "}
                  {forecast.first_half.most_probable_score.home_goals}–
                  {forecast.first_half.most_probable_score.away_goals}
                </p>
              </Card>
            )}
            {forecast.corners && (
              <Card title="Corners">
                <p className="text-sm text-slate-300">
                  {num(forecast.corners.expected_home, 1)} –{" "}
                  {num(forecast.corners.expected_away, 1)}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Total {num(forecast.corners.expected_total, 1)}
                </p>
              </Card>
            )}
            {forecast.cards && (
              <Card title="Cards">
                <p className="text-sm text-slate-300">
                  {num(forecast.cards.expected_home, 1)} –{" "}
                  {num(forecast.cards.expected_away, 1)}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  Total {num(forecast.cards.expected_total, 1)}
                </p>
              </Card>
            )}
          </div>

          {forecast.conformal && (
            <Card title="Conformal (distribution-free) intervals" className="mb-6">
              <p className="mb-3 text-xs text-slate-500">
                Calibrated from the model&rsquo;s own out-of-sample residuals,
                not assumed from the goal-model shape. Empirical coverage is
                what was actually measured on held-out matches.
              </p>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                {(["home_goals", "away_goals", "total_goals"] as const).map(
                  (key) => {
                    const interval = forecast.conformal?.[key];
                    if (!interval) return null;
                    return (
                      <div key={key}>
                        <p className="text-xs uppercase tracking-wide text-slate-500">
                          {key.replaceAll("_", " ")}
                        </p>
                        <p className="text-sm text-slate-200">
                          {num(interval.lower, 1)} – {num(interval.upper, 1)}
                        </p>
                        <p className="text-xs text-slate-500">
                          target {pct(interval.target_coverage)}, observed{" "}
                          {pct(interval.empirical_coverage)}
                        </p>
                      </div>
                    );
                  }
                )}
              </div>
              {forecast.conformal.outcome_prediction_set.length > 0 && (
                <p className="mt-3 text-sm text-slate-300">
                  Plausible outcome set:{" "}
                  {forecast.conformal.outcome_prediction_set
                    .map((o) => o.replaceAll("_", " "))
                    .join(", ")}
                </p>
              )}
            </Card>
          )}

          <Card title="Model diagnostics" className="mb-6">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <StatusBadge value={forecast.model_diagnostics.model_disagreement} />
              {forecast.model_diagnostics.ood_status && (
                <span className="rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-xs text-amber-400">
                  Out of distribution
                </span>
              )}
              {forecast.model_diagnostics.shock_status && (
                <span className="rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-xs text-amber-400">
                  Shock detected
                </span>
              )}
            </div>
            <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MiniStat
                label="Aleatoric uncertainty"
                value={num(forecast.model_diagnostics.aleatoric_uncertainty)}
              />
              <MiniStat
                label="Epistemic uncertainty"
                value={num(forecast.model_diagnostics.epistemic_uncertainty)}
              />
              <MiniStat
                label="Data quality score"
                value={pct(forecast.model_diagnostics.data_quality_score)}
              />
            </div>
            {forecast.model_diagnostics.ood_flags.length > 0 && (
              <FlagList
                title="OOD flags"
                flags={forecast.model_diagnostics.ood_flags}
              />
            )}
            {forecast.model_diagnostics.shock_flags.length > 0 && (
              <FlagList
                title="Shock flags"
                flags={forecast.model_diagnostics.shock_flags}
              />
            )}
          </Card>

          <Card title="Model information" className="mb-6">
            <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MiniStat
                label="Champion model"
                value={forecast.model_information.champion_model ?? "—"}
              />
              <MiniStat
                label="Model version"
                value={forecast.model_information.model_version ?? "—"}
              />
              <MiniStat
                label="Dataset version"
                value={forecast.model_information.dataset_version ?? "—"}
              />
              <MiniStat
                label="Predicted at"
                value={new Date(
                  forecast.model_information.predicted_at
                ).toLocaleString()}
              />
            </div>
            {Object.keys(forecast.model_information.ensemble_weights).length >
              0 && (
              <div>
                <p className="mb-2 text-xs uppercase tracking-wide text-slate-500">
                  Ensemble weights
                </p>
                <div className="space-y-1">
                  {Object.entries(forecast.model_information.ensemble_weights).map(
                    ([model, weight]) => (
                      <div key={model} className="flex items-center gap-2">
                        <span className="w-32 shrink-0 text-xs text-slate-400">
                          {model}
                        </span>
                        <div className="h-2 flex-1 rounded-full bg-slate-800">
                          <div
                            className="h-2 rounded-full bg-cyan-500"
                            style={{ width: `${weight * 100}%` }}
                          />
                        </div>
                        <span className="w-12 text-right text-xs text-slate-400">
                          {pct(weight)}
                        </span>
                      </div>
                    )
                  )}
                </div>
              </div>
            )}
          </Card>

          <Card title="Administrator notes" className="mb-6">
            {forecast.administrator_notes.warnings.length === 0 &&
              forecast.administrator_notes.errors.length === 0 && (
                <p className="text-sm text-slate-500">No warnings.</p>
              )}
            {forecast.administrator_notes.errors.length > 0 && (
              <FlagList
                title="Errors"
                flags={forecast.administrator_notes.errors}
                tone="red"
              />
            )}
            {forecast.administrator_notes.warnings.length > 0 && (
              <FlagList
                title="Warnings"
                flags={forecast.administrator_notes.warnings}
              />
            )}
            {forecast.administrator_notes.calibration && (
              <div className="mt-3 text-sm text-slate-400">
                Calibration ({forecast.administrator_notes.calibration.method}
                ): raw{" "}
                {pct(
                  forecast.administrator_notes.calibration
                    .raw_home_win_probability
                )}{" "}
                → calibrated{" "}
                {pct(
                  forecast.administrator_notes.calibration
                    .calibrated_home_win_probability
                )}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </p>
      <p className="text-sm text-slate-200">{value}</p>
    </div>
  );
}

function FlagList({
  title,
  flags,
  tone = "amber",
}: {
  title: string;
  flags: string[];
  tone?: "amber" | "red";
}) {
  const color = tone === "red" ? "text-red-400" : "text-amber-400";
  return (
    <div className="mb-2">
      <p className="mb-1 text-xs uppercase tracking-wide text-slate-500">
        {title}
      </p>
      <ul className={`list-inside list-disc text-sm ${color}`}>
        {flags.map((flag, i) => (
          <li key={i}>{flag}</li>
        ))}
      </ul>
    </div>
  );
}

export default function FixturePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <MatchIntelligenceContent fixtureId={decodeURIComponent(id)} />
    </RequireAuth>
  );
}
