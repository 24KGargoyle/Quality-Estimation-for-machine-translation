"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";

export default function LoginPage() {
  const { devLogin } = useAuth();
  const [provider, setProvider] = useState<string>("dev");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [tenantName, setTenantName] = useState("");
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
    <div className="login-layout">
      <section className="login-card" aria-labelledby="sign-in-heading">
        <header className="login-brand">
          <Image src="/brand/everforth-quinnox-logo.png" alt="Everforth Quinnox" width={935} height={267} priority />
          <p>Meeting Assistant</p>
        </header>
        <h1 id="sign-in-heading">Sign in</h1>
        <button
          onClick={handleEntraLogin}
          className="microsoft-sign-in w-full rounded-md border border-neutral-300 px-4 py-2.5 text-sm font-medium hover:bg-neutral-50"
        >
          Sign in with Microsoft
        </button>
        {entraError && <p role="alert" className="mb-4 text-xs text-amber-600">{entraError}</p>}

        <div className="my-5 flex items-center gap-3 text-xs text-neutral-400">
          <div className="h-px flex-1 bg-neutral-200" />
          or
          <div className="h-px flex-1 bg-neutral-200" />
        </div>

        <form onSubmit={handleDevLogin} className="space-y-4">
          <div>
            <label htmlFor="login-field-1" className="mb-1 block text-xs font-medium text-neutral-500">Work email</label>
            <input id="login-field-1"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              required
            />
          </div>
          <div>
            <label htmlFor="login-field-2" className="mb-1 block text-xs font-medium text-neutral-500">Display name</label>
            <input id="login-field-2"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
          </div>
          <div>
            <label htmlFor="login-field-3" className="mb-1 block text-xs font-medium text-neutral-500">Organization / tenant</label>
            <input id="login-field-3"
              className="w-full rounded-md border border-neutral-300 px-3 py-2 text-sm"
              value={tenantName}
              onChange={(e) => setTenantName(e.target.value)}
              required
            />
          </div>
          {error && <p role="alert" className="text-xs text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md bg-neutral-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-50"
          >
            {busy ? "Signing in…" : "Continue"}
          </button>
        </form>
        {provider === "dev" && <p className="login-environment">Development environment</p>}
      </section>
    </div>
  );
}
