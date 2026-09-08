"use client";

import { useEffect, useState } from "react";
import RequireAuth from "@/components/RequireAuth";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

function SettingsContent() {
  const { user, logout } = useAuth();
  const [health, setHealth] = useState<{ graph_configured: boolean; llm_configured: boolean; auth_provider: string } | null>(null);

  useEffect(() => {
    api
      .get<{ status: string; graph_configured: boolean; llm_configured: boolean; auth_provider: string }>("/health")
      .then(setHealth)
      .catch(() => {});
  }, []);

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="text-xl font-semibold">Settings</h1>

      <div className="mt-6 rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="text-sm font-semibold text-neutral-500">Account</h2>
        <dl className="mt-2 space-y-1 text-sm">
          <div className="flex justify-between"><dt className="text-neutral-400">Name</dt><dd>{user?.displayName}</dd></div>
          <div className="flex justify-between"><dt className="text-neutral-400">Tenant</dt><dd>{user?.tenantId}</dd></div>
          <div className="flex justify-between"><dt className="text-neutral-400">Role</dt><dd>{user?.role}</dd></div>
        </dl>
        <button
          onClick={logout}
          className="mt-4 rounded-md border border-neutral-300 px-3 py-1.5 text-xs hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          Sign out
        </button>
      </div>

      <div className="mt-4 rounded-xl border border-neutral-200 bg-white p-5 dark:border-neutral-800 dark:bg-neutral-900">
        <h2 className="text-sm font-semibold text-neutral-500">Platform status</h2>
        <dl className="mt-2 space-y-1 text-sm">
          <div className="flex justify-between">
            <dt className="text-neutral-400">Auth provider</dt>
            <dd>{health?.auth_provider ?? "…"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-neutral-400">Microsoft Graph</dt>
            <dd>{health?.graph_configured ? "Configured" : "Not configured"}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-neutral-400">AI model</dt>
            <dd>{health?.llm_configured ? "Configured" : "Not configured"}</dd>
          </div>
        </dl>
        {!health?.graph_configured && (
          <p className="mt-3 text-xs text-neutral-400">
            Microsoft Graph requires an Azure AD app registration (tenant ID, client ID/secret).
            See docs/MICROSOFT_GRAPH_PERMISSIONS.md and docs/DEPLOYMENT.md.
          </p>
        )}
      </div>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <RequireAuth>
      <SettingsContent />
    </RequireAuth>
  );
}
