"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { ApiError, getCompetitions, getModels } from "@/lib/api";
import type { Competition, ModelVersionSummary } from "@/lib/types";

const MODEL_NAMES = [
  "dixon_coles",
  "poisson_baseline",
  "hierarchical_model",
  "first_half_model",
  "corners_model",
  "cards_model",
  "xg_model",
] as const;

const STATUSES = ["ENABLED", "CHALLENGER", "RETIRED", "DISABLED"] as const;

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function ModelLabContent() {
  const { token } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [models, setModels] = useState<ModelVersionSummary[] | null>(null);
  const [competition, setCompetition] = useState<string>("");
  const [modelName, setModelName] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch((err) => setError(String(err)));
  }, [token]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    getModels(token, {
      competition: competition || undefined,
      model_name: modelName || undefined,
      status: status || undefined,
    })
      .then((rows) => {
        if (cancelled) return;
        setModels(rows);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [token, competition, modelName, status]);

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">Model Lab</h1>
      <p className="mb-4 text-sm text-slate-500">
        The model registry (section 70) — every trained version, never
        deleted. Raw parameters and drift history require ADMIN or ANALYST
        access.
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        <select
          value={competition}
          onChange={(e) => setCompetition(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        >
          <option value="">All competitions</option>
          {competitions.map((c) => (
            <option key={c.canonical_competition_id} value={c.canonical_competition_id}>
              {c.name}
            </option>
          ))}
        </select>
        <select
          value={modelName}
          onChange={(e) => setModelName(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        >
          <option value="">All model types</option>
          {MODEL_NAMES.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        >
          <option value="">All statuses</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {models === null && !error && (
        <p className="text-sm text-slate-500">Loading model versions…</p>
      )}
      {models?.length === 0 && (
        <p className="text-sm text-slate-500">
          No model versions match this filter.
        </p>
      )}

      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="pb-2">Model</th>
              <th className="pb-2">Version</th>
              <th className="pb-2">Status</th>
              <th className="pb-2">Competition</th>
              <th className="pb-2">Trained at</th>
              <th className="pb-2">Reproducible</th>
            </tr>
          </thead>
          <tbody>
            {models?.map((m) => (
              <tr key={m.version} className="border-t border-slate-800">
                <td className="py-2 text-slate-200">{m.model_name}</td>
                <td className="py-2">
                  <Link
                    href={`/models/${encodeURIComponent(m.version)}`}
                    className="font-mono text-cyan-400 hover:underline"
                  >
                    {m.version}
                  </Link>
                </td>
                <td className="py-2">
                  <StatusBadge value={m.status} />
                  {m.disabled_reason && (
                    <p className="mt-0.5 text-xs text-slate-500">
                      {m.disabled_reason}
                    </p>
                  )}
                </td>
                <td className="py-2 text-slate-400">
                  {m.competition_canonical_id ?? "—"}
                </td>
                <td className="py-2 text-slate-400">
                  {formatDate(m.trained_at)}
                </td>
                <td className="py-2 text-slate-400">
                  {m.is_reproducible ? "yes" : "no"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

export default function ModelsPage() {
  return (
    <RequireAuth>
      <ModelLabContent />
    </RequireAuth>
  );
}
