"use client";

import { useEffect, useState, type FormEvent } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import {
  ApiError,
  createUser,
  getAuditLogs,
  getCompetitions,
  getJob,
  getMonitoring,
  getUsers,
  listDeadLetterJobs,
  triggerSync,
  triggerSyncAsync,
  updateUser,
} from "@/lib/api";
import type {
  AuditLog,
  Competition,
  Job,
  Monitoring,
  SyncReport,
  User,
} from "@/lib/types";

const ROLES = ["ADMIN", "ANALYST", "VIEWER", "SYSTEM"];

function fmt(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : "—";
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

function SyncPanel({ token }: { token: string }) {
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<SyncReport | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const jobDone = job && (job.status === "SUCCEEDED" || job.status === "FAILED");

  useEffect(() => {
    if (!job || jobDone) return;
    const timer = setInterval(() => {
      getJob(job.job_id, token)
        .then(setJob)
        .catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [job, jobDone, token]);

  function runSync() {
    setRunning(true);
    setError(null);
    setReport(null);
    triggerSync(token)
      .then((r) => setReport(r))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setRunning(false));
  }

  function runSyncAsync() {
    setError(null);
    setJob(null);
    triggerSyncAsync(token).then(setJob).catch((err) => setError(errorMessage(err)));
  }

  return (
    <Card title="Data synchronization">
      <p className="mb-3 text-xs text-slate-500">
        Runs discovery, team mapping, fixture/result sync, promotion/
        relegation detection, data-quality scoring, league baselines, model
        training, backtesting and calibration (section 51). &ldquo;Run
        now&rdquo; blocks until finished; &ldquo;Run in background&rdquo;
        enqueues it on the job queue (section 74, Phase 15) and polls for
        status instead — that needs <code>REDIS_URL</code> configured on the
        backend and 503s otherwise.
      </p>
      <div className="mb-4 flex flex-wrap gap-2">
        <button
          onClick={runSync}
          disabled={running}
          className="rounded-md border border-cyan-700 bg-cyan-900/30 px-3 py-1.5 text-sm text-cyan-300 transition hover:border-cyan-500 disabled:opacity-50"
        >
          {running ? "Running…" : "Run sync now"}
        </button>
        <button
          onClick={runSyncAsync}
          disabled={!!job && !jobDone}
          className="rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-300 transition hover:border-cyan-500 hover:text-cyan-400 disabled:opacity-50"
        >
          Run in background
        </button>
      </div>

      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      {job && (
        <div className="mb-4 rounded-md border border-slate-800 p-3 text-sm">
          <div className="mb-1 flex items-center gap-2">
            <span className="text-slate-400">Job {job.job_id}</span>
            <StatusBadge value={job.status} />
            <span className="text-slate-500">
              attempt {job.attempts}/{job.max_retries}
            </span>
          </div>
          {job.error && <p className="text-red-400">{job.error}</p>}
        </div>
      )}

      {report && (
        <div className="space-y-3 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-slate-400">Status</span>
            <StatusBadge value={report.system_status} />
            <span className="text-slate-500">via {report.provider}</span>
          </div>
          <table className="w-full text-sm">
            <tbody>
              <tr className="border-t border-slate-800">
                <td className="py-1 text-slate-500">Teams</td>
                <td className="py-1 text-slate-200">
                  {report.new_teams} new, {report.updated_teams} updated,{" "}
                  {report.renamed_teams} renamed
                </td>
              </tr>
              <tr className="border-t border-slate-800">
                <td className="py-1 text-slate-500">Fixtures</td>
                <td className="py-1 text-slate-200">
                  {report.new_fixtures} new, {report.updated_fixtures} updated
                </td>
              </tr>
              <tr className="border-t border-slate-800">
                <td className="py-1 text-slate-500">Results</td>
                <td className="py-1 text-slate-200">{report.new_results} new</td>
              </tr>
              <tr className="border-t border-slate-800">
                <td className="py-1 text-slate-500">Models</td>
                <td className="py-1 text-slate-200">
                  {report.models_activated.length} activated,{" "}
                  {report.models_disabled.length} disabled,{" "}
                  {report.models_requiring_review.length} need review
                </td>
              </tr>
            </tbody>
          </table>
          {report.errors.length > 0 && (
            <ul className="list-disc pl-5 text-red-400">
              {report.errors.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function DeadLetterPanel({ token }: { token: string }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    listDeadLetterJobs(token)
      .then((rows) => {
        setJobs(rows);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoaded(true));
  }, [token]);

  return (
    <Card title="Dead-letter jobs">
      <p className="mb-3 text-xs text-slate-500">
        Background jobs that exhausted their retries (section 74) — the same
        job queue as the sync panel above. Empty if no job has ever failed
        that many times, or if <code>REDIS_URL</code> isn&rsquo;t configured.
      </p>
      {error && <p className="text-sm text-red-400">{error}</p>}
      {loaded && !error && jobs.length === 0 && (
        <p className="text-sm text-slate-500">None.</p>
      )}
      {jobs.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="pb-2">Job</th>
              <th className="pb-2">Type</th>
              <th className="pb-2">Attempts</th>
              <th className="pb-2">Error</th>
              <th className="pb-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.job_id} className="border-t border-slate-800">
                <td className="py-1.5 text-slate-200">{j.job_id}</td>
                <td className="py-1.5 text-slate-400">{j.job_type}</td>
                <td className="py-1.5 text-slate-400">
                  {j.attempts}/{j.max_retries}
                </td>
                <td className="py-1.5 text-red-400">{j.error ?? "—"}</td>
                <td className="py-1.5 text-slate-400">{fmt(j.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function DriftPanel({
  token,
  competitions,
}: {
  token: string;
  competitions: Competition[];
}) {
  const [competition, setCompetition] = useState("");
  const [breachedOnly, setBreachedOnly] = useState(true);
  const [rows, setRows] = useState<Monitoring[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getMonitoring(token, {
      competition: competition || undefined,
      breached_only: breachedOnly,
    })
      .then((r) => {
        setRows(r);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)));
  }, [token, competition, breachedOnly]);

  return (
    <Card title="Drift monitoring">
      <p className="mb-3 text-xs text-slate-500">
        Model/data drift checks across every competition (section 42) —
        ADMIN/ANALYST only. A model&rsquo;s own page in Model Lab shows this
        same data scoped to one version; this is the cross-competition,
        breaches-first view.
      </p>
      <div className="mb-3 flex items-center gap-3">
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
        <label className="flex items-center gap-1.5 text-sm text-slate-400">
          <input
            type="checkbox"
            checked={breachedOnly}
            onChange={(e) => setBreachedOnly(e.target.checked)}
          />
          Breached only
        </label>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      {!error && rows.length === 0 && (
        <p className="text-sm text-slate-500">
          {breachedOnly
            ? "No threshold breaches recorded."
            : "No monitoring checks recorded yet."}
        </p>
      )}
      {rows.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="pb-2">Competition</th>
              <th className="pb-2">Model</th>
              <th className="pb-2">Metric</th>
              <th className="pb-2">Value</th>
              <th className="pb-2">Threshold</th>
              <th className="pb-2">Breached</th>
              <th className="pb-2">Evaluated</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-800">
                <td className="py-1.5 text-slate-200">{r.competition_canonical_id}</td>
                <td className="py-1.5 text-slate-400">
                  {r.model_name} {r.model_version}
                </td>
                <td className="py-1.5 text-slate-400">{r.metric_name}</td>
                <td className="py-1.5 text-slate-400">{r.metric_value.toFixed(3)}</td>
                <td className="py-1.5 text-slate-400">
                  {r.threshold != null ? r.threshold.toFixed(3) : "—"}
                </td>
                <td className="py-1.5">
                  <StatusBadge value={r.breached ? "BREACHED" : "OK"} />
                </td>
                <td className="py-1.5 text-slate-400">{fmt(r.evaluated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function UsersPanel({ token }: { token: string }) {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState("VIEWER");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  function reload() {
    getUsers(token)
      .then((rows) => {
        setUsers(rows);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)));
  }

  useEffect(reload, [token]);

  function handleCreate(event: FormEvent) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    createUser({ email: newEmail, password: newPassword, role: newRole }, token)
      .then(() => {
        setNewEmail("");
        setNewPassword("");
        setNewRole("VIEWER");
        reload();
      })
      .catch((err) => setCreateError(errorMessage(err)))
      .finally(() => setCreating(false));
  }

  function handleRoleChange(user: User, role: string) {
    updateUser(user.id, { role }, token).then(reload).catch((err) => setError(errorMessage(err)));
  }

  function handleToggleActive(user: User) {
    updateUser(user.id, { is_active: !user.is_active }, token)
      .then(reload)
      .catch((err) => setError(errorMessage(err)));
  }

  return (
    <Card title="Users">
      <p className="mb-3 text-xs text-slate-500">
        Administrator-surface accounts and roles (section 54). The very
        first ADMIN account can&rsquo;t be created here — bootstrap it with
        the backend&rsquo;s <code>scripts/create_admin.py</code> instead.
      </p>

      <form onSubmit={handleCreate} className="mb-4 flex flex-wrap items-end gap-2">
        <input
          type="email"
          required
          placeholder="email"
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        />
        <input
          type="password"
          required
          placeholder="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        />
        <select
          value={newRole}
          onChange={(e) => setNewRole(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={creating}
          className="rounded-md border border-cyan-700 bg-cyan-900/30 px-3 py-1.5 text-sm text-cyan-300 transition hover:border-cyan-500 disabled:opacity-50"
        >
          {creating ? "Creating…" : "Create user"}
        </button>
      </form>
      {createError && <p className="mb-3 text-sm text-red-400">{createError}</p>}
      {error && <p className="mb-3 text-sm text-red-400">{error}</p>}

      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-slate-500">
            <th className="pb-2">Email</th>
            <th className="pb-2">Role</th>
            <th className="pb-2">Active</th>
            <th className="pb-2">Created</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className="border-t border-slate-800">
              <td className="py-1.5 text-slate-200">{u.email}</td>
              <td className="py-1.5">
                <select
                  value={u.role}
                  onChange={(e) => handleRoleChange(u, e.target.value)}
                  className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </td>
              <td className="py-1.5">
                <button
                  onClick={() => handleToggleActive(u)}
                  className="rounded-md border border-slate-700 px-2 py-0.5 text-xs text-slate-300 transition hover:border-cyan-500 hover:text-cyan-400"
                >
                  {u.is_active ? "Active — deactivate" : "Inactive — activate"}
                </button>
              </td>
              <td className="py-1.5 text-slate-400">{fmt(u.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function AuditLogPanel({ token }: { token: string }) {
  const [action, setAction] = useState("");
  const [actorEmail, setActorEmail] = useState("");
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      getAuditLogs(token, {
        action: action || undefined,
        actor_email: actorEmail || undefined,
      })
        .then((rows) => {
          setLogs(rows);
          setError(null);
        })
        .catch((err) => setError(errorMessage(err)));
    }, 300);
    return () => clearTimeout(timer);
  }, [token, action, actorEmail]);

  return (
    <Card title="Audit log">
      <p className="mb-3 text-xs text-slate-500">
        Every recorded administrative action (section 54) — most recent 500.
      </p>
      <div className="mb-3 flex flex-wrap gap-2">
        <input
          placeholder="filter by action (e.g. ROLLBACK_MODEL_VERSION)"
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        />
        <input
          placeholder="filter by actor email"
          value={actorEmail}
          onChange={(e) => setActorEmail(e.target.value)}
          className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200"
        />
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      {!error && logs.length === 0 && (
        <p className="text-sm text-slate-500">No matching audit events.</p>
      )}
      {logs.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="pb-2">When</th>
              <th className="pb-2">Actor</th>
              <th className="pb-2">Action</th>
              <th className="pb-2">Resource</th>
              <th className="pb-2">Details</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l, i) => (
              <tr key={i} className="border-t border-slate-800">
                <td className="py-1.5 text-slate-400">{fmt(l.occurred_at)}</td>
                <td className="py-1.5 text-slate-200">
                  {l.actor_email ?? "—"}{" "}
                  <span className="text-slate-600">({l.actor_role ?? "—"})</span>
                </td>
                <td className="py-1.5 text-slate-200">{l.action}</td>
                <td className="py-1.5 text-slate-400">
                  {l.resource_type ? `${l.resource_type}:${l.resource_id}` : "—"}
                </td>
                <td className="py-1.5 text-slate-500">
                  {l.details ? JSON.stringify(l.details) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function AdminCentreContent() {
  const { token, role } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[]>([]);

  useEffect(() => {
    if (!token) return;
    getCompetitions(token)
      .then(setCompetitions)
      .catch(() => {});
  }, [token]);

  if (role !== "ADMIN") {
    return (
      <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        <h1 className="mb-2 text-lg font-semibold text-white">Admin Centre</h1>
        <p className="text-sm text-slate-500">
          This page is ADMIN only (section 54). You&rsquo;re signed in as{" "}
          {role ?? "an unknown role"} — every call this page would make
          (users, audit logs, sync, drift) would be rejected by the backend
          with a 403, so there&rsquo;s nothing to show.
        </p>
      </div>
    );
  }

  if (!token) return null;

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">Admin Centre</h1>
      <p className="mb-6 text-sm text-slate-500">
        Operational control for the platform (sections 19/72): trigger a
        sync, inspect background-job and drift status, manage user accounts,
        and browse the audit log. Model/backtest/calibration diagnostics live
        in Model Lab and the Backtesting Centre rather than being duplicated
        here.
      </p>

      <div className="mb-6">
        <SyncPanel token={token} />
      </div>
      <div className="mb-6">
        <DeadLetterPanel token={token} />
      </div>
      <div className="mb-6">
        <DriftPanel token={token} competitions={competitions} />
      </div>
      <div className="mb-6">
        <UsersPanel token={token} />
      </div>
      <AuditLogPanel token={token} />
    </div>
  );
}

export default function AdminPage() {
  return (
    <RequireAuth>
      <AdminCentreContent />
    </RequireAuth>
  );
}
