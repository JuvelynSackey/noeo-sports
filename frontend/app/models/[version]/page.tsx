"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  ApiError,
  getAuditLogs,
  getBacktests,
  getCalibration,
  getConformal,
  getModelPerformance,
  getModelVersion,
  getMonitoring,
  rollbackModel,
} from "@/lib/api";
import type {
  AuditLog,
  Backtest,
  Calibration,
  ConformalCalibrationDiagnostic,
  ModelPerformance,
  ModelVersionDetail,
  Monitoring,
} from "@/lib/types";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function num(v: unknown, digits = 3): string {
  return typeof v === "number" ? v.toFixed(digits) : "—";
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function ModelDetailContent({ version }: { version: string }) {
  const { token, role } = useAuth();
  const [model, setModel] = useState<ModelVersionDetail | null>(null);
  const [performance, setPerformance] = useState<ModelPerformance | null>(null);
  const [backtest, setBacktest] = useState<Backtest | null>(null);
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [conformal, setConformal] = useState<ConformalCalibrationDiagnostic[]>([]);
  const [monitoring, setMonitoring] = useState<Monitoring[]>([]);
  const [rollbackHistory, setRollbackHistory] = useState<AuditLog[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isRollingBack, setIsRollingBack] = useState(false);
  const [rollbackMessage, setRollbackMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!token) return;
    getModelVersion(version, token)
      .then((detail) => {
        setModel(detail);
        setError(null);
        const competition = detail.competition_canonical_id ?? undefined;

        getModelPerformance(token, competition)
          .then((rows) =>
            setPerformance(rows.find((r) => r.model_version === version) ?? null)
          )
          .catch(() => {});
        getBacktests(token, { competition, model_name: detail.model_name })
          .then((rows) =>
            setBacktest(rows.find((r) => r.model_version === version) ?? null)
          )
          .catch(() => {});
        getCalibration(token, competition)
          .then((rows) =>
            setCalibration(rows.find((r) => r.model_version === version) ?? null)
          )
          .catch(() => {});
        getConformal(token, { competition })
          .then((rows) => setConformal(rows.filter((r) => r.model_version === version)))
          .catch(() => {});
        getMonitoring(token, { competition, model_name: detail.model_name })
          .then((rows) => setMonitoring(rows.filter((r) => r.model_version === version)))
          .catch(() => {});
        getAuditLogs(token, { action: "ROLLBACK_MODEL_VERSION" })
          .then((rows) =>
            setRollbackHistory(
              rows.filter(
                (r) =>
                  r.resource_id === version ||
                  (r.details && r.details["previous_champion"] === version)
              )
            )
          )
          .catch(() => {});
      })
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : String(err));
      });
  }, [token, version]);

  useEffect(load, [load]);

  const handleRollback = useCallback(async () => {
    if (!token) return;
    setIsRollingBack(true);
    setRollbackMessage(null);
    try {
      const updated = await rollbackModel(version, token);
      setModel(updated);
      setRollbackMessage(`Rolled back — ${version} is now ENABLED.`);
    } catch (err) {
      setRollbackMessage(err instanceof ApiError ? err.message : String(err));
    } finally {
      setIsRollingBack(false);
    }
  }, [token, version]);

  if (error) {
    return (
      <div className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
        <Link href="/models" className="text-sm text-slate-500 hover:text-cyan-400">
          ← Model Lab
        </Link>
        <Card className="mt-4">
          <p className="text-sm text-red-400">{error}</p>
          <p className="mt-2 text-xs text-slate-500">
            Raw parameters, backtests and drift history require ADMIN or
            ANALYST access (section 54).
          </p>
        </Card>
      </div>
    );
  }

  if (!model) {
    return (
      <div className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
        <p className="text-sm text-slate-500">Loading…</p>
      </div>
    );
  }

  const metrics = model.evaluation_metrics ?? {};
  const attack = model.parameters?.attack ?? {};
  const defence = model.parameters?.defence ?? {};
  const teamRows = Object.keys(attack)
    .map((team) => ({ team, attack: attack[team], defence: defence[team] ?? null }))
    .sort((a, b) => b.attack - a.attack);

  return (
    <div className="mx-auto w-full max-w-4xl flex-1 px-4 py-6">
      <Link href="/models" className="text-sm text-slate-500 hover:text-cyan-400">
        ← Model Lab
      </Link>

      <div className="mt-2 mb-1 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-white">{model.model_name}</h1>
        <span className="font-mono text-sm text-slate-500">{model.version}</span>
        <StatusBadge value={model.status} />
      </div>
      {model.disabled_reason && (
        <p className="mb-4 text-sm text-amber-400">{model.disabled_reason}</p>
      )}
      {model.competition_canonical_id && (
        <p className="mb-4 text-sm text-slate-500">
          Competition:{" "}
          <Link
            href={`/competitions/${encodeURIComponent(model.competition_canonical_id)}`}
            className="text-cyan-400 hover:underline"
          >
            {model.competition_canonical_id}
          </Link>
        </p>
      )}

      {role === "ADMIN" && model.status !== "ENABLED" && (
        <Card className="mb-6">
          <p className="mb-3 text-sm text-slate-400">
            This version is not the live one. Rolling back promotes it back
            to ENABLED and retires whatever is currently live for this
            model/competition — the human override for the champion/
            challenger gate (section 11).
          </p>
          <button
            onClick={handleRollback}
            disabled={isRollingBack}
            className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-60"
          >
            {isRollingBack ? "Rolling back…" : "Roll back to this version"}
          </button>
          {rollbackMessage && (
            <p className="mt-2 text-sm text-slate-300">{rollbackMessage}</p>
          )}
        </Card>
      )}

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Card title="Training">
          <Row label="Trained at" value={formatDate(model.trained_at)} />
          <Row
            label="Window"
            value={`${formatDate(model.training_window_start)} → ${formatDate(model.training_window_end)}`}
          />
          <Row label="Reproducible" value={model.is_reproducible ? "yes" : "no"} />
        </Card>
        <Card title="Evaluation metrics">
          <Row label="Log-likelihood" value={num(metrics["log_likelihood"])} />
          <Row label="AIC" value={num(metrics["aic"])} />
          <Row label="Matches" value={String(metrics["n_matches"] ?? "—")} />
          <Row label="Parameters" value={String(metrics["n_params"] ?? "—")} />
          <Row
            label="Converged"
            value={metrics["converged"] === false ? "no" : "yes"}
          />
        </Card>
      </div>

      {Object.keys(attack).length > 0 && (
        <Card title="Team strength (attack / defence, log scale)" className="mb-6">
          <div className="mb-2 flex gap-4 text-xs text-slate-500">
            <span>Home advantage: {num(model.parameters?.home_advantage, 3)}</span>
            <span>Rho (low-score correction): {num(model.parameters?.rho, 3)}</span>
          </div>
          <div className="max-h-64 overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="pb-1">Team</th>
                  <th className="pb-1">Attack</th>
                  <th className="pb-1">Defence</th>
                </tr>
              </thead>
              <tbody>
                {teamRows.map((r) => (
                  <tr key={r.team} className="border-t border-slate-800">
                    <td className="py-1 text-slate-300">{r.team}</td>
                    <td className="py-1 text-slate-400">{num(r.attack)}</td>
                    <td className="py-1 text-slate-400">{num(r.defence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {model.hyperparameters && (
        <Card title="Hyperparameters" className="mb-6">
          <pre className="overflow-x-auto text-xs text-slate-400">
            {JSON.stringify(model.hyperparameters, null, 2)}
          </pre>
        </Card>
      )}

      <Card title="Walk-forward performance" className="mb-6">
        {performance ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Row label="Ensemble weight" value={pct(performance.ensemble_weight)} />
            <Row label="Brier score" value={num(performance.brier_score)} />
            <Row label="Log loss" value={num(performance.log_loss)} />
            <Row label="RPS" value={num(performance.ranked_probability_score)} />
            <Row label="Folds" value={String(performance.n_folds ?? "—")} />
            <Row label="Predictions" value={String(performance.n_predictions ?? "—")} />
          </div>
        ) : (
          <p className="text-sm text-slate-500">
            No pooled performance recorded for this exact version —
            walk-forward results are only attached to whichever version was
            ENABLED when they were computed.
          </p>
        )}
      </Card>

      {backtest && (
        <Card title="Backtest residuals" className="mb-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Row
              label="Home goal residual"
              value={`${num(backtest.home_goal_residual_mean, 2)} ± ${num(backtest.home_goal_residual_std, 2)}`}
            />
            <Row
              label="Away goal residual"
              value={`${num(backtest.away_goal_residual_mean, 2)} ± ${num(backtest.away_goal_residual_std, 2)}`}
            />
            <Row label="Total goals RMSE" value={num(backtest.total_goals_rmse, 2)} />
            <Row
              label="Exact-score log loss"
              value={num(backtest.exact_score_mean_log_loss)}
            />
          </div>
        </Card>
      )}

      {calibration && (
        <Card title="Probability calibration" className="mb-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Row label="Method" value={calibration.method} />
            <Row label="Calibration error" value={num(calibration.calibration_error)} />
            <Row label="Brier score" value={num(calibration.brier_score)} />
            <Row label="Log loss" value={num(calibration.log_loss)} />
          </div>
        </Card>
      )}

      {conformal.length > 0 && (
        <Card title="Conformal calibration" className="mb-6">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="pb-1">Target</th>
                <th className="pb-1">Quantile</th>
                <th className="pb-1">Target coverage</th>
                <th className="pb-1">Observed coverage</th>
              </tr>
            </thead>
            <tbody>
              {conformal.map((c) => (
                <tr key={c.target} className="border-t border-slate-800">
                  <td className="py-1 text-slate-300">
                    {c.target.replaceAll("_", " ")}
                  </td>
                  <td className="py-1 text-slate-400">{num(c.quantile, 2)}</td>
                  <td className="py-1 text-slate-400">{pct(1 - c.alpha)}</td>
                  <td className="py-1 text-slate-400">{pct(c.empirical_coverage)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {monitoring.length > 0 && (
        <Card title="Drift history" className="mb-6">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="pb-1">Metric</th>
                <th className="pb-1">Value</th>
                <th className="pb-1">Threshold</th>
                <th className="pb-1">Evaluated</th>
              </tr>
            </thead>
            <tbody>
              {monitoring.map((m, i) => (
                <tr key={i} className="border-t border-slate-800">
                  <td className="py-1 text-slate-300">{m.metric_name}</td>
                  <td className={`py-1 ${m.breached ? "text-red-400" : "text-slate-400"}`}>
                    {num(m.metric_value, 4)}
                  </td>
                  <td className="py-1 text-slate-500">{num(m.threshold, 4)}</td>
                  <td className="py-1 text-slate-500">{formatDate(m.evaluated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {rollbackHistory.length > 0 && (
        <Card title="Rollback history">
          <ul className="space-y-2 text-sm text-slate-400">
            {rollbackHistory.map((r, i) => (
              <li key={i}>
                {formatDate(r.occurred_at)} — {r.actor_email} rolled back to{" "}
                <span className="font-mono text-slate-300">{r.resource_id}</span>
                {r.details?.["previous_champion"]
                  ? ` (from ${r.details["previous_champion"]})`
                  : ""}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-sm text-slate-200">{value}</p>
    </div>
  );
}

export default function ModelVersionPage({
  params,
}: {
  params: Promise<{ version: string }>;
}) {
  const { version } = use(params);
  return (
    <RequireAuth>
      <ModelDetailContent version={decodeURIComponent(version)} />
    </RequireAuth>
  );
}
