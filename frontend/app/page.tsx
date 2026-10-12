"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { getCompetitions, getSystemHealth } from "@/lib/api";
import type { Competition, SystemHealth } from "@/lib/types";

function DashboardContent() {
  const { token } = useAuth();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [competitions, setCompetitions] = useState<Competition[] | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    Promise.all([getSystemHealth(), getCompetitions(token)])
      .then(([h, c]) => {
        if (cancelled) return;
        setHealth(h);
        setCompetitions(c);
      })
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [token]);

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-4 text-lg font-semibold text-white">
        System Intelligence
      </h1>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {health && (
        <Card title="System health" className="mb-6">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Status">
              <StatusBadge value={health.status} />
            </Stat>
            <Stat label="Provider" value={health.data_provider} />
            <Stat
              label="Competitions"
              value={`${health.active_competitions} / ${health.competitions_total} active`}
            />
            <Stat
              label="Scheduler"
              value={health.scheduler_enabled ? "enabled" : "disabled"}
            />
          </div>
          {health.detail && (
            <p className="mt-3 text-sm text-red-400">{health.detail}</p>
          )}
        </Card>
      )}

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">
        Competitions
      </h2>
      {competitions === null && !error && (
        <p className="text-sm text-slate-500">Loading competitions…</p>
      )}
      {competitions?.length === 0 && (
        <p className="text-sm text-slate-500">
          No competitions discovered yet — trigger a sync from the API
          (<code className="text-slate-400">POST /sync</code>) to populate
          this.
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {competitions?.map((c) => (
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
                {c.country ?? "—"} · {c.competition_format.replaceAll("_", " ")}
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

function Stat({
  label,
  value,
  children,
}: {
  label: string;
  value?: string;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </p>
      {children ?? <p className="mt-1 text-sm text-slate-200">{value}</p>}
    </div>
  );
}

export default function Dashboard() {
  return (
    <RequireAuth>
      <DashboardContent />
    </RequireAuth>
  );
}
