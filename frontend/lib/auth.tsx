"use client";

// Client-side JWT auth state (section 54). The token lives only in
// localStorage, read by this provider on mount — there's no server-side
// session here, consistent with this being a thin client over an
// already-authenticated API rather than a server that itself holds
// credentials.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { ApiError, login as apiLogin } from "./api";

const STORAGE_KEY = "noeo.auth";

interface StoredAuth {
  token: string;
  role: string;
  email: string;
  expiresAt: string;
}

interface AuthContextValue {
  token: string | null;
  role: string | null;
  email: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function readStoredAuth(): StoredAuth | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredAuth;
    if (new Date(parsed.expiresAt).getTime() <= Date.now()) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<StoredAuth | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // One-time hydration from a browser-only API (localStorage) that
    // can't be read during the server render — rendering "loading" first
    // on both server and client, then syncing once after mount, avoids a
    // hydration mismatch rather than guessing the auth state up front.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAuth(readStoredAuth());
    setIsLoading(false);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await apiLogin(email, password);
    const next: StoredAuth = {
      token: response.access_token,
      role: response.role,
      email,
      expiresAt: response.expires_at,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    setAuth(next);
  }, []);

  const logout = useCallback(() => {
    window.localStorage.removeItem(STORAGE_KEY);
    setAuth(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        token: auth?.token ?? null,
        role: auth?.role ?? null,
        email: auth?.email ?? null,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

export { ApiError };
