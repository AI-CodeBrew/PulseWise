"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { ApiError, apiGet, apiPost, setUnauthorizedHandler } from "@/lib/api";
import type { Me } from "@/lib/types";

type Status = "loading" | "authenticated" | "anonymous" | "error";

interface AuthState {
  status: Status;
  me: Me | null; // the user + the websites they may see
  error: string | null; // when status is "error" (e.g. backend unreachable)
  loggedOut: boolean; // true right after clicking "Log out"
}

interface AuthContextValue extends AuthState {
  setMe: (me: Me) => void; // after logging in
  refresh: () => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Knows who is logged in, for the whole app.
 * On start it asks the backend "who am I?" (GET /api/auth/me). The answer comes
 * from the httpOnly login cookie, which JavaScript itself can't read.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading", me: null, error: null, loggedOut: false });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    apiGet<Me>("/api/auth/me", undefined, controller.signal)
      .then((me) => setState({ status: "authenticated", me, error: null, loggedOut: false }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          setState({ status: "anonymous", me: null, error: null, loggedOut: false });
        } else {
          const message = err instanceof ApiError ? err.message : "Something went wrong.";
          setState({ status: "error", me: null, error: message, loggedOut: false });
        }
      });
    return () => controller.abort();
  }, [tick]);

  // Any request that gets "401 not logged in" (e.g. the session expired) lands here.
  useEffect(() => {
    setUnauthorizedHandler(() => setState({ status: "anonymous", me: null, error: null, loggedOut: false }));
    return () => setUnauthorizedHandler(null);
  }, []);

  const setMe = useCallback((me: Me) => setState({ status: "authenticated", me, error: null, loggedOut: false }), []);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const logout = useCallback(async () => {
    try {
      await apiPost("/api/auth/logout", {}, { quiet401: true });
    } finally {
      setState({ status: "anonymous", me: null, error: null, loggedOut: true });
    }
  }, []);

  return <AuthContext.Provider value={{ ...state, setMe, refresh, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
