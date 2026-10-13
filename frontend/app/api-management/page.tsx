"use client";

import { useEffect, useState, type FormEvent } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { Card } from "@/components/Card";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/lib/auth";
import { ApiError, createApiKey, listApiKeys, updateApiKey } from "@/lib/api";
import type { ApiKey, ApiKeyCreated } from "@/lib/types";

function fmt(v: string | null | undefined): string {
  return v ? new Date(v).toLocaleString() : "—";
}

function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : String(err);
}

const inputClass =
  "rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200";
const buttonPrimaryClass =
  "rounded-md border border-cyan-700 bg-cyan-900/30 px-3 py-1.5 text-sm text-cyan-300 transition hover:border-cyan-500 disabled:opacity-50";
const buttonSecondaryClass =
  "rounded-md border border-slate-700 px-2 py-0.5 text-xs text-slate-300 transition hover:border-cyan-500 hover:text-cyan-400";

function ApiManagementContent() {
  const { token, role } = useAuth();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [justCreated, setJustCreated] = useState<ApiKeyCreated | null>(null);

  function reload() {
    if (!token) return;
    listApiKeys(token)
      .then((rows) => {
        setKeys(rows);
        setError(null);
      })
      .catch((err) => setError(errorMessage(err)));
  }

  useEffect(reload, [token]);

  function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setCreating(true);
    createApiKey(newName, token)
      .then((created) => {
        setJustCreated(created);
        setNewName("");
        reload();
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setCreating(false));
  }

  function handleToggleActive(key: ApiKey) {
    if (!token) return;
    updateApiKey(key.key_id, { is_active: !key.is_active }, token)
      .then(reload)
      .catch((err) => setError(errorMessage(err)));
  }

  if (!token) return null;

  const isAdmin = role === "ADMIN";

  return (
    <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
      <h1 className="mb-1 text-lg font-semibold text-white">API Management</h1>
      <p className="mb-6 text-sm text-slate-500">
        API keys for programmatic access (section 24) — a long-lived
        alternative to the short-lived token this app itself uses, for
        scripts or external integrations. Send one as an{" "}
        <code>X-API-Key</code> header instead of{" "}
        <code>Authorization: Bearer</code>; it acts with your own current
        role and is rate limited per key, independently of your normal
        browser usage. Anyone can create a key for themselves; ADMIN can
        additionally see and revoke every key, not just their own.
      </p>

      <Card title="Create a key" className="mb-6">
        <form onSubmit={handleCreate} className="flex flex-wrap items-end gap-2">
          <input
            placeholder='Name (e.g. "reporting script")'
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            required
            className={`${inputClass} w-64`}
          />
          <button type="submit" disabled={creating} className={buttonPrimaryClass}>
            {creating ? "Creating…" : "Create key"}
          </button>
        </form>

        {justCreated && (
          <div className="mt-4 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
            <p className="mb-2 text-amber-400">
              Save this now — it&rsquo;s shown once and can&rsquo;t be
              retrieved again. Losing it means revoking this key below and
              creating a new one.
            </p>
            <code className="block overflow-x-auto rounded bg-slate-950 px-2 py-1.5 text-xs text-cyan-300">
              {justCreated.api_key}
            </code>
            <button
              onClick={() => setJustCreated(null)}
              className="mt-2 text-xs text-slate-500 hover:text-slate-300"
            >
              Dismiss
            </button>
          </div>
        )}
      </Card>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <Card title={isAdmin ? "All API keys" : "Your API keys"}>
        {keys.length === 0 && !error && (
          <p className="text-sm text-slate-500">No API keys yet.</p>
        )}
        {keys.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="pb-2">Name</th>
                <th className="pb-2">Key ID</th>
                {isAdmin && <th className="pb-2">Owner</th>}
                <th className="pb-2">Role</th>
                <th className="pb-2">Status</th>
                <th className="pb-2">Requests</th>
                <th className="pb-2">Last used</th>
                <th className="pb-2">Created</th>
                <th className="pb-2"></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} className="border-t border-slate-800">
                  <td className="py-1.5 text-slate-200">{k.name}</td>
                  <td className="py-1.5 text-slate-400">
                    <code className="text-xs">{k.key_id}</code>
                  </td>
                  {isAdmin && <td className="py-1.5 text-slate-400">{k.owner_email}</td>}
                  <td className="py-1.5 text-slate-400">{k.role}</td>
                  <td className="py-1.5">
                    {k.is_active ? (
                      <StatusBadge value="ACTIVE" />
                    ) : (
                      <span className="text-xs text-slate-500">Inactive</span>
                    )}
                  </td>
                  <td className="py-1.5 text-slate-400">{k.request_count}</td>
                  <td className="py-1.5 text-slate-400">{fmt(k.last_used_at)}</td>
                  <td className="py-1.5 text-slate-400">{fmt(k.created_at)}</td>
                  <td className="py-1.5">
                    <button onClick={() => handleToggleActive(k)} className={buttonSecondaryClass}>
                      {k.is_active ? "Revoke" : "Reactivate"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

export default function ApiManagementPage() {
  return (
    <RequireAuth>
      <ApiManagementContent />
    </RequireAuth>
  );
}
