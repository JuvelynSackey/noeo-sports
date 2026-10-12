"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { getCompetition, getFixtures } from "@/lib/api";
import type { CompetitionDetail, Fixture } from "@/lib/types";

const STATUS_FILTERS = ["ALL", "SCHEDULED", "COMPLETED", "IN_PLAY"] as const;

function formatKickoff(iso: string | null): string {
  if (!iso) return "TBD";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function CompetitionContent({ id }: { id: string }) {
  const { token } = useAuth();
  const [competition, setCompetition] = useState<CompetitionDetail | null>(
    null
  );
  const [fixtures, setFixtures] = useState<Fixture[] | null>(null);
  const [statusFilter, setStatusFilter] =
    useState<(typeof STATUS_FILTERS)[number]>("ALL");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    Promise.all([
      getCompetition(id, token),
      getFixtures(token, { competition: id }),
    ])
      .then(([c, f]) => {
        if (cancelled) return;
        setCompetition(c);
        setFixtures(f);
      })
      .catch((err) => !cancelled && setError(String(err)));
    return () => {
      cancelled = true;
    };
  }, [id, token]);

  const visibleFixtures =
    statusFilter === "ALL"
      ? fixtures
      : fixtures?.filter((f) => f.status === statusFilter);

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <Link href="/" className="text-sm text-slate-500 hover:text-cyan-400">
        ← Competitions
      </Link>

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

      {competition && (
        <>
          <div className="mt-2 mb-6 flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold text-white">
              {competition.name}
            </h1>
            <StatusBadge value={competition.status} />
            <StatusBadge value={competition.data_quality_status} />
          </div>

          <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Card title="Country">
              <p className="text-sm text-slate-200">
                {competition.country ?? "—"}
              </p>
            </Card>
            <Card title="Format">
              <p className="text-sm text-slate-200">
                {competition.competition_format.replaceAll("_", " ")}
              </p>
            </Card>
            <Card title="Teams">
              <p className="text-sm text-slate-200">
                {competition.number_of_teams ?? "—"}
              </p>
            </Card>
            <Card title="Seasons">
              <p className="text-sm text-slate-200">
                {competition.seasons.map((s) => s.name).join(", ") || "—"}
              </p>
            </Card>
          </div>
        </>
      )}

      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Fixtures
        </h2>
        <div className="flex gap-1">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded-md px-2 py-1 text-xs ${
                statusFilter === s
                  ? "bg-cyan-500 text-slate-950"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {visibleFixtures === null && !error && (
        <p className="text-sm text-slate-500">Loading fixtures…</p>
      )}
      {visibleFixtures?.length === 0 && (
        <p className="text-sm text-slate-500">No fixtures match this filter.</p>
      )}

      <div className="divide-y divide-slate-800 rounded-xl border border-slate-800">
        {visibleFixtures?.map((f) => (
          <Link
            key={f.canonical_fixture_id}
            href={`/fixtures/${encodeURIComponent(f.canonical_fixture_id)}`}
            className="flex items-center justify-between gap-4 px-4 py-3 transition hover:bg-slate-900/60"
          >
            <div className="flex-1">
              <p className="text-sm text-white">
                {f.home_team.current_name}{" "}
                <span className="text-slate-500">vs</span>{" "}
                {f.away_team.current_name}
              </p>
              <p className="text-xs text-slate-500">
                {formatKickoff(f.kickoff_utc)}
                {f.round ? ` · Round ${f.round}` : ""}
              </p>
            </div>
            {f.result && (
              <p className="text-sm font-medium text-slate-200">
                {f.result.home_goals} – {f.result.away_goals}
              </p>
            )}
            <StatusBadge value={f.status} />
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function CompetitionPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  return (
    <RequireAuth>
      <CompetitionContent id={decodeURIComponent(id)} />
    </RequireAuth>
  );
}
