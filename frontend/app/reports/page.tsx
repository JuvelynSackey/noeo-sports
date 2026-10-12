"use client";

import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { SyncReportCard } from "@/components/reports/SyncReportCard";
import { useAuth } from "@/lib/auth";
import { ApiError, getSyncReports } from "@/lib/api";
import type { SyncReport } from "@/lib/types";

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

function ReportsContent() {
  const { token, role } = useAuth();
  const [reports, setReports] = useState<SyncReport[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || role !== "ADMIN") return;
    getSyncReports(token)
      .then(setReports)
      .catch((err) => setError(errorMessage(err)));
  }, [token, role]);

  if (!token) return null;

  if (role !== "ADMIN") {
    return (
      <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <h1 className="mb-2 text-lg font-semibold text-white">Reports</h1>
        <p className="text-sm text-slate-500">
          This page is ADMIN only (section 54) — sync reports are read via{" "}
          <code>GET /audit-logs</code>, which the backend restricts to
          ADMIN. You&rsquo;re signed in as {role ?? "an unknown role"}.
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">Reports</h1>
      <p className="mb-6 text-sm text-slate-500">
        Every past full sync (section 63), most recent first. There&rsquo;s
        no dedicated report store on the backend — each{" "}
        <code>POST /sync</code> now records its complete result as that
        action&rsquo;s own audit-log entry, so this page is just that
        history read back and rendered properly instead of as raw JSON.
        Only synchronous syncs are recorded this way; a background sync
        (<code>POST /sync/async</code>) only logs its enqueue, not its
        eventual result, at audit-log granularity — see the Admin
        Centre&rsquo;s job panel for that case instead. Sync runs recorded
        before this report format existed are skipped rather than shown
        as broken rows.
      </p>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      {reports.length === 0 && !error && (
        <p className="text-sm text-slate-500">No sync has been run yet.</p>
      )}

      {reports.map((r, i) => (
        <SyncReportCard key={i} report={r} />
      ))}
    </div>
  );
}

export default function ReportsPage() {
  return (
    <RequireAuth>
      <ReportsContent />
    </RequireAuth>
  );
}
