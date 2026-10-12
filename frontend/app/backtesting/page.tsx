"use client";

import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { ReliabilityChart } from "@/components/backtesting/ReliabilityChart";
import { useAuth } from "@/lib/auth";
import {
  ApiError,
  getBacktests,
  getCalibration,
  getCompetitions,
  getConformal,
  getModelPerformance,
  getModels,
} from "@/lib/api";
import type {
  Backtest,
  Calibration,
  Competition,
  ConformalCalibrationDiagnostic,
  ModelPerformance,
} from "@/lib/types";

function num(v: number | null | undefined, digits = 3): string {
  return v == null ? "—" : v.toFixed(digits);
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function BacktestingCentreContent() {
  const { token } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [competition, setCompetition] = useState<string>("");
  const [performance, setPerformance] = useState<ModelPerformance[]>([]);
  const [backtests, setBacktests] = useState<Backtest[]>([]);
  const [calibration, setCalibration] = useState<Calibration[]>([]);
  const [conformal, setConformal] = useState<ConformalCalibrationDiagnostic[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch((err) => setError(String(err)));
  }, [token]);

  useEffect(() => {
    if (!token || !competition) return;
    let cancelled = false;
    Promise.all([
      getModels(token, { competition, status: "ENABLED" }),
      getModelPerformance(token, competition),
      getBacktests(token, { competition }),
      getCalibration(token, competition),
      getConformal(token, { competition }),
    ])
      .then(([enabled, perf, bt, cal, conf]) => {
        if (cancelled) return;
        // /model-performance, /backtests, /calibration and /conformal all
        // retain history across retrains (never deleted, same as
        // ModelVersion itself) rather than scoping to "whatever's live
        // right now" — correct for Model Lab's per-version detail page,
        // but a cross-model comparison needs exactly one row per model
        // type, so this keeps only the row(s) for each model_name's
        // currently-ENABLED version.
        const enabledVersions = new Set(enabled.map((m) => m.version));
        setPerformance(perf.filter((p) => enabledVersions.has(p.model_version)));
        setBacktests(bt.filter((b) => enabledVersions.has(b.model_version)));
        setCalibration(cal.filter((c) => enabledVersions.has(c.model_version)));
        setConformal(conf.filter((c) => enabledVersions.has(c.model_version)));
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [token, competition]);

  const reliabilitySeries = [
    ...backtests
      .filter((b) => (b.reliability_curve ?? []).length > 0)
      .map((b) => ({ name: `${b.model_name} (raw)`, points: b.reliability_curve! })),
    ...calibration
      .filter((c) => (c.reliability_curve ?? []).length > 0)
      .map((c) => ({
        name: `${c.model_name} (calibrated, ${c.method})`,
        points: c.reliability_curve!,
      })),
  ];

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">
        Backtesting Centre
      </h1>
      <p className="mb-4 text-sm text-slate-500">
        Compare candidate models by competition (section 71) — walk-forward
        performance, reliability/calibration curves, residual diagnostics,
        and conformal coverage. Season/date-range filtering and
        cross-competition comparison aren&rsquo;t supported by the backend
        yet, so this is scoped to one competition at a time.
      </p>

      <select
        value={competition}
        onChange={(e) => setCompetition(e.target.value)}
        className="mb-6 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
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
          Pick a competition above to compare its candidate models.
        </p>
      )}

      {competition && (
        <>
          <Card title="Walk-forward performance" className="mb-6">
            {performance.length === 0 ? (
              <p className="text-sm text-slate-500">
                No pooled performance recorded yet — needs a full sync with
                enough completed matches to backtest.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="pb-2">Model</th>
                    <th className="pb-2">Ensemble weight</th>
                    <th className="pb-2">Brier</th>
                    <th className="pb-2">Log loss</th>
                    <th className="pb-2">RPS</th>
                    <th className="pb-2">Folds</th>
                    <th className="pb-2">Predictions</th>
                  </tr>
                </thead>
                <tbody>
                  {performance.map((p) => (
                    <tr key={p.model_version} className="border-t border-slate-800">
                      <td className="py-1.5 text-slate-200">{p.model_name}</td>
                      <td className="py-1.5 text-slate-400">{pct(p.ensemble_weight)}</td>
                      <td className="py-1.5 text-slate-400">{num(p.brier_score)}</td>
                      <td className="py-1.5 text-slate-400">{num(p.log_loss)}</td>
                      <td className="py-1.5 text-slate-400">
                        {num(p.ranked_probability_score)}
                      </td>
                      <td className="py-1.5 text-slate-400">{p.n_folds ?? "—"}</td>
                      <td className="py-1.5 text-slate-400">{p.n_predictions ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="Reliability / calibration curves" className="mb-6">
            <p className="mb-3 text-xs text-slate-500">
              Predicted home-win probability (binned) vs. observed
              frequency. The dashed diagonal is perfect calibration — a
              curve above it under-predicts, below it over-predicts.
              &ldquo;Calibrated&rdquo; series only exist for the champion
              anchor model (dixon_coles), not every candidate — see Phase
              6/13&rsquo;s own scope notes.
            </p>
            <ReliabilityChart series={reliabilitySeries} />
          </Card>

          <Card title="Residual & distribution diagnostics" className="mb-6">
            {backtests.length === 0 ? (
              <p className="text-sm text-slate-500">No backtest detail recorded yet.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="pb-2">Model</th>
                    <th className="pb-2">Home goal residual</th>
                    <th className="pb-2">Away goal residual</th>
                    <th className="pb-2">Total goals RMSE</th>
                    <th className="pb-2">Exact-score log loss</th>
                  </tr>
                </thead>
                <tbody>
                  {backtests.map((b) => (
                    <tr key={b.model_version} className="border-t border-slate-800">
                      <td className="py-1.5 text-slate-200">{b.model_name}</td>
                      <td className="py-1.5 text-slate-400">
                        {num(b.home_goal_residual_mean, 2)} ± {num(b.home_goal_residual_std, 2)}
                      </td>
                      <td className="py-1.5 text-slate-400">
                        {num(b.away_goal_residual_mean, 2)} ± {num(b.away_goal_residual_std, 2)}
                      </td>
                      <td className="py-1.5 text-slate-400">{num(b.total_goals_rmse, 2)}</td>
                      <td className="py-1.5 text-slate-400">
                        {num(b.exact_score_mean_log_loss)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="Conformal coverage (champion model only)">
            {conformal.length === 0 ? (
              <p className="text-sm text-slate-500">
                No conformal calibration recorded yet — needs enough
                out-of-sample predictions (section 44).
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-slate-500">
                    <th className="pb-2">Target</th>
                    <th className="pb-2">Quantile</th>
                    <th className="pb-2">Target coverage</th>
                    <th className="pb-2">Observed coverage</th>
                  </tr>
                </thead>
                <tbody>
                  {conformal.map((c) => (
                    <tr key={c.target} className="border-t border-slate-800">
                      <td className="py-1.5 text-slate-200">
                        {c.target.replaceAll("_", " ")}
                      </td>
                      <td className="py-1.5 text-slate-400">{num(c.quantile, 2)}</td>
                      <td className="py-1.5 text-slate-400">{pct(1 - c.alpha)}</td>
                      <td className="py-1.5 text-slate-400">{pct(c.empirical_coverage)}</td>
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

export default function BacktestingPage() {
  return (
    <RequireAuth>
      <BacktestingCentreContent />
    </RequireAuth>
  );
}
