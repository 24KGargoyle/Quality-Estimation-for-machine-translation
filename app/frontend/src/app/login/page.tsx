"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";

export default function LoginPage() {
  const { devLogin } = useAuth();
  const [provider, setProvider] = useState<string>("dev");
  const [email, setEmail] = useState("santhosh@acme.com");
  const [displayName, setDisplayName] = useState("Santhosh");
  const [tenantName, setTenantName] = useState("Acme Corp");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [entraError, setEntraError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ provider: string }>("/api/auth/provider")
      .then((r) => setProvider(r.provider))
      .catch(() => setProvider("dev"));
  }, []);

  async function handleDevLogin(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await devLogin(email, displayName, tenantName);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleEntraLogin() {
    setEntraError(null);
    try {
      const { login_url } = await api.get<{ login_url: string }>("/api/auth/entra/login-url");
      window.location.href = login_url;
    } catch (err) {
      setEntraError(
        err instanceof ApiError
          ? err.message
          : "Microsoft Entra ID sign-in is not available in this environment."
      );
    }
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-md flex-col justify-center px-4">
      <div className="mb-8 text-center">
        <h1 className="text-2xl font-semibold">Meeting Copilot</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Agentic Microsoft Teams Meeting Intelligence &amp; Collaboration
        </p>
      </div>

      <div className="rounded-xl border border-neutral-200 bg-white p-6 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <button
          onClick={handleEntraLogin}
          className="mb-4 w-full rounded-md bg-[#2564cf] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1e4fa3]"
        >
          Sign in with Microsoft
        </button>
        {entraError && <p className="mb-4 text-xs text-amber-600 dark:text-amber-400">{entraError}</p>}

        <div className="mb-4 flex items-center gap-2 text-xs text-neutral-400">
          <div className="h-px flex-1 bg-neutral-200 dark:bg-neutral-800" />
          {provider === "dev" ? "development sign-in" : "or"}
          <div className="h-px flex-1 bg-neutral-200 dark:bg-neutral-800" />
        </div>

        <form onSubmit={handleDevLogin} className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">Work email</label>
            <input
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">Display name</label>
            <input
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-500">Organization / tenant</label>
            <input
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              required
            />
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-neutral-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50 dark:bg-white dark:text-neutral-900"
          >
            {busy ? "Signing in…" : "Continue"}
          </button>
        </form>
        <p className="mt-4 text-center text-[11px] leading-relaxed text-neutral-400">
          Development sign-in is used because this environment has no live Microsoft Entra ID
          tenant configured. See docs/DEPLOYMENT.md.
        </p>
      </div>
    </div>
  );
}
