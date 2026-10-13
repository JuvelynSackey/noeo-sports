"use client";

import { useEffect, useMemo, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { ApiError, getSystemEvents, getSystemHealth } from "@/lib/api";
import type { SystemEvent, SystemHealth } from "@/lib/types";

const SEVERITIES = ["INFO", "WARNING", "ERROR"] as const;

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

function fmt(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : "—";
}

const inputClass =
  "rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200";

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <div className="mt-1 text-sm text-slate-200">{value}</div>
    </div>
  );
}

export default function SystemIntelligencePage() {
  return (
    <RequireAuth>
      <SystemIntelligenceInner />
    </RequireAuth>
  );
}

function SystemIntelligenceInner() {
  const { token, role } = useAuth();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [events, setEvents] = useState<SystemEvent[]>([]);
  const [eventTypeFilter, setEventTypeFilter] = useState("ALL");
  const [severityFilter, setSeverityFilter] = useState("ALL");
  const [error, setError] = useState<string | null>(null);

  const canView = role === "ADMIN" || role === "ANALYST";

  useEffect(() => {
    getSystemHealth()
      .then(setHealth)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!token || !canView) return;
    getSystemEvents(token, {
      event_type: eventTypeFilter === "ALL" ? undefined : eventTypeFilter,
      severity: severityFilter === "ALL" ? undefined : severityFilter,
    })
      .then((rows) => {
        setEvents(rows);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)));
  }, [token, canView, eventTypeFilter, severityFilter]);

  const eventTypes = useMemo(
    () => Array.from(new Set(events.map((e) => e.event_type))).sort(),
    [events]
  );

  if (!token) return null;

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">System Intelligence</h1>
      <p className="mb-6 text-sm text-slate-500">
        Infrastructure health and the system&rsquo;s own operational event
        log (sections 51/53) — sync completions, discovery failures, model
        promotions and challenger rejections, drift breaches, and team
        promotion/relegation/arrival/departure movements, recorded with no
        human actor. Distinct from the Admin Centre&rsquo;s audit log,
        which is who-did-what; this is what the system itself observed or
        decided. Drift detail and job-queue status live in the Admin
        Centre and aren&rsquo;t duplicated here.
      </p>

      <Card title="System health" className="mb-6">
        {health ? (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Status" value={<StatusBadge value={health.status} />} />
            <Stat label="Provider" value={health.data_provider} />
            <Stat
              label="Competitions"
              value={`${health.active_competitions} / ${health.competitions_total} active`}
            />
            <Stat
              label="Scheduler"
              value={health.scheduler_enabled ? "enabled" : "disabled"}
            />
            <Stat label="Database" value={health.database_url_scheme} />
            <Stat label="Next scheduled sync" value={fmt(health.next_scheduled_sync)} />
          </div>
        ) : (
          <p className="text-sm text-slate-500">Loading…</p>
        )}
        {health?.detail && <p className="mt-3 text-sm text-red-400">{health.detail}</p>}
      </Card>

      {!canView ? (
        <Card title="System events">
          <p className="text-sm text-slate-500">
            This section is ADMIN/ANALYST only (section 54) — you&rsquo;re
            signed in as {role ?? "an unknown role"}. The backend would
            reject <code>GET /system-events</code> with a 403 anyway.
          </p>
        </Card>
      ) : (
        <Card title="System events">
          <div className="mb-3 flex flex-wrap gap-2">
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className={inputClass}
            >
              <option value="ALL">All severities</option>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              value={eventTypeFilter}
              onChange={(e) => setEventTypeFilter(e.target.value)}
              className={inputClass}
            >
              <option value="ALL">All event types</option>
              {eventTypes.map((t) => (
                <option key={t} value={t}>
                  {t.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </div>

          {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

          {events.length === 0 && !error && (
            <p className="text-sm text-slate-500">No matching events recorded.</p>
          )}

          {events.length > 0 && (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-slate-500">
                  <th className="pb-2">When</th>
                  <th className="pb-2">Severity</th>
                  <th className="pb-2">Type</th>
                  <th className="pb-2">Message</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={i} className="border-t border-slate-800">
                    <td className="py-1.5 text-slate-400">{fmt(e.occurred_at)}</td>
                    <td className="py-1.5">
                      <StatusBadge value={e.severity} />
                    </td>
                    <td className="py-1.5 text-slate-200">{e.event_type.replaceAll("_", " ")}</td>
                    <td className="py-1.5 text-slate-400">{e.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  );
}
