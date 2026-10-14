"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { AuthCard, Field, FormMessage, SubmitButton } from "@/components/auth/AuthCard";
import { useAuth } from "@/components/auth/AuthProvider";
import { ApiError, apiPost } from "@/lib/api";
import type { Me } from "@/lib/types";

/** Only allow going back to pages of THIS site after login (never to another website). */
function safeNext(next: string | null): string {
  if (next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\")) return next;
  return "/";
}

export default function LoginPage() {
  const auth = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeNext(searchParams.get("next"));
  const justReset = searchParams.get("reset") === "1";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already logged in (or just logged in): go on.
  useEffect(() => {
    if (auth.status === "authenticated") router.replace(next);
  }, [auth.status, next, router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // quiet401: here a 401 just means "wrong email or password".
      const me = await apiPost<Me>("/api/auth/login", { email, password }, { quiet401: true });
      auth.setMe(me); // the effect above then redirects
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Log in" subtitle="See how your website is doing.">
      {justReset && <FormMessage kind="success">Your password was changed. Please log in.</FormMessage>}
      {error && <FormMessage kind="error">{error}</FormMessage>}
      <form onSubmit={onSubmit}>
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <SubmitButton busy={busy}>Log in</SubmitButton>
      </form>
      <p className="mt-4 text-center text-sm">
        <Link href="/forgot-password" className="text-accent hover:underline">
          Forgot your password?
        </Link>
      </p>
    </AuthCard>
  );
}
