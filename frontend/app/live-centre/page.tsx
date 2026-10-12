"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { ApiError, getCompetitions, getFixtures } from "@/lib/api";
import type { Competition, Fixture } from "@/lib/types";

const POLL_INTERVAL_MS = 15000;

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

function formatKickoff(iso: string | null): string {
  if (!iso) return "TBD";
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

interface LiveFixture extends Fixture {
  competitionName: string;
}

function LiveCentreContent() {
  const { token } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);
  const [liveFixtures, setLiveFixtures] = useState<LiveFixture[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch(() => {});
  }, [token]);

  useEffect(() => {
    if (!token || competitions.length === 0) return;
    let cancelled = false;

    function poll() {
      Promise.all(
        competitions.map((c) =>
          getFixtures(token!, { competition: c.canonical_competition_id, status: "IN_PLAY" }).then(
            (fixtures) => fixtures.map((f) => ({ ...f, competitionName: c.name }))
          )
        )
      )
        .then((groups) => {
          if (cancelled) return;
          const all = groups
            .flat()
            .sort((a, b) => (a.kickoff_utc ?? "").localeCompare(b.kickoff_utc ?? ""));
          setLiveFixtures(all);
          setLastUpdated(new Date());
          setError(null);
        })
        .catch((err) => {
          if (!cancelled) setError(errorMessage(err));
        });
    }

    poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [token, competitions]);

  if (!token) return null;

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <div className="mb-1 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-white">Live Centre</h1>
        {lastUpdated && (
          <span className="text-xs text-slate-500">
            Updated {lastUpdated.toLocaleTimeString()} · refreshes every{" "}
            {POLL_INTERVAL_MS / 1000}s
          </span>
        )}
      </div>
      <p className="mb-6 text-sm text-slate-500">
        Every fixture currently IN_PLAY, across every competition — polled
        on an interval rather than pushed, since there&rsquo;s no
        websocket/SSE channel on the backend. <code>GET /fixtures</code>{" "}
        doesn&rsquo;t carry a competition reference on the fixture object
        itself, so this page fetches per competition ({competitions.length}{" "}
        right now) and tags each result with the competition it came from,
        rather than parsing it out of the fixture id (a fragile pattern
        this project deliberately avoids elsewhere).
      </p>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {liveFixtures === null && !error && (
        <p className="text-sm text-slate-500">Loading…</p>
      )}

      {liveFixtures?.length === 0 && !error && (
        <p className="text-sm text-slate-500">No matches currently in play.</p>
      )}

      {liveFixtures && liveFixtures.length > 0 && (
        <div className="divide-y divide-slate-800 rounded-xl border border-slate-800">
          {liveFixtures.map((f) => (
            <Link
              key={f.canonical_fixture_id}
              href={`/fixtures/${encodeURIComponent(f.canonical_fixture_id)}`}
              className="flex items-center justify-between gap-4 px-4 py-3 transition hover:bg-slate-900/60"
            >
              <div className="flex-1">
                <p className="text-xs text-slate-500">{f.competitionName}</p>
                <p className="text-sm text-white">
                  {f.home_team.current_name}{" "}
                  <span className="text-slate-500">vs</span>{" "}
                  {f.away_team.current_name}
                </p>
                <p className="text-xs text-slate-500">{formatKickoff(f.kickoff_utc)}</p>
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
      )}
    </div>
  );
}

export default function LiveCentrePage() {
  return (
    <RequireAuth>
      <LiveCentreContent />
    </RequireAuth>
  );
}
