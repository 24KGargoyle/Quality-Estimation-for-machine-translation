"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { useRouter } from "next/navigation";
import { api, setToken } from "./api";
import { TokenResponse } from "./types";

interface AuthUser {
  userId: string;
  displayName: string;
  tenantId: string;
  role: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  devLogin: (email: string, displayName: string, tenantName: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);
const STORAGE_KEY = "mi_user";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    // localStorage only exists client-side, so this must run in an effect rather
    // than a lazy useState initializer (which would mismatch the server render).
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const token = window.localStorage.getItem("mi_token");
    if (raw && token) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setUser(JSON.parse(raw));
    }
    setLoading(false);
  }, []);

  async function devLogin(email: string, displayName: string, tenantName: string) {
    const resp = await api.post<TokenResponse>("/api/auth/dev-login", {
      email,
      display_name: displayName,
      tenant_name: tenantName,
    });
    setToken(resp.access_token);
    const authUser: AuthUser = {
      userId: resp.user_id,
      displayName: resp.display_name,
      tenantId: resp.tenant_id,
      role: resp.role,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(authUser));
    setUser(authUser);
    router.push("/dashboard");
  }

  function logout() {
    setToken(null);
    window.localStorage.removeItem(STORAGE_KEY);
    setUser(null);
    router.push("/login");
  }

  return (
    <AuthContext.Provider value={{ user, loading, devLogin, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
