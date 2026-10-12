"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { ApiError, getCompetitions } from "@/lib/api";
import type { Competition } from "@/lib/types";

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

const inputClass =
  "rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200";

type SortKey = "name" | "number_of_teams";

function CompetitionsContent() {
  const { token } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [typeFilter, setTypeFilter] = useState("ALL");
  const [countryFilter, setCountryFilter] = useState("ALL");
  const [sortKey, setSortKey] = useState<SortKey>("name");

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch((err) => setError(errorMessage(err)));
  }, [token]);

  const statuses = useMemo(
    () => Array.from(new Set(competitions.map((c) => c.status))).sort(),
    [competitions]
  );
  const types = useMemo(
    () => Array.from(new Set(competitions.map((c) => c.competition_type))).sort(),
    [competitions]
  );
  const countries = useMemo(
    () =>
      Array.from(new Set(competitions.map((c) => c.country).filter((c): c is string => !!c))).sort(),
    [competitions]
  );

  const filtered = useMemo(() => {
    return competitions
      .filter((c) => statusFilter === "ALL" || c.status === statusFilter)
      .filter((c) => typeFilter === "ALL" || c.competition_type === typeFilter)
      .filter((c) => countryFilter === "ALL" || c.country === countryFilter)
      .sort((a, b) =>
        sortKey === "number_of_teams"
          ? (b.number_of_teams ?? 0) - (a.number_of_teams ?? 0)
          : a.name.localeCompare(b.name)
      );
  }, [competitions, statusFilter, typeFilter, countryFilter, sortKey]);

  if (!token) return null;

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">Competitions</h1>
      <p className="mb-4 text-sm text-slate-500">
        Every competition the platform tracks, filterable by status,
        type and country, and sortable — the Dashboard&rsquo;s own
        competitions grid is deliberately unfiltered (a quick jump-off
        point, not a browser). Pick one to see its fixtures.
      </p>

      <div className="mb-6 flex flex-wrap gap-2">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className={inputClass}
        >
          <option value="ALL">All statuses</option>
          {statuses.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className={inputClass}
        >
          <option value="ALL">All types</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <select
          value={countryFilter}
          onChange={(e) => setCountryFilter(e.target.value)}
          className={inputClass}
        >
          <option value="ALL">All countries</option>
          {countries.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          className={inputClass}
        >
          <option value="name">Sort: name</option>
          <option value="number_of_teams">Sort: teams (most first)</option>
        </select>
      </div>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {filtered.length === 0 && !error && (
        <p className="text-sm text-slate-500">No competitions match these filters.</p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((c) => (
          <Link
            key={c.canonical_competition_id}
            href={`/competitions/${encodeURIComponent(c.canonical_competition_id)}`}
          >
            <Card className="h-full transition hover:border-cyan-600">
              <div className="mb-2 flex items-start justify-between gap-2">
                <h3 className="font-medium text-white">{c.name}</h3>
                <StatusBadge value={c.status} />
              </div>
              <p className="mb-3 text-sm text-slate-400">
                {c.country ?? "—"} · {c.competition_type.replaceAll("_", " ")} ·{" "}
                {c.competition_format.replaceAll("_", " ")}
              </p>
              <div className="flex items-center justify-between text-xs text-slate-500">
                <span>{c.number_of_teams ?? "?"} teams</span>
                <StatusBadge value={c.data_quality_status} />
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function CompetitionsPage() {
  return (
    <RequireAuth>
      <CompetitionsContent />
    </RequireAuth>
  );
}
