"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthCard, Field, FormMessage, SubmitButton } from "@/components/auth/AuthCard";
import { useAuth } from "@/components/auth/AuthProvider";
import { RequireAuth } from "@/components/auth/RequireAuth";
import { ApiError, apiPost } from "@/lib/api";

const MIN_LENGTH = 8;

export default function AccountPage() {
  return (
    <RequireAuth>
      <ChangePassword />
    </RequireAuth>
  );
}

function ChangePassword() {
  const { me } = useAuth();
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_LENGTH) return setError(`New password must be at least ${MIN_LENGTH} characters.`);
    if (password !== confirm) return setError("The two new passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/auth/change-password", { current_password: current, new_password: password });
      setDone(true);
      setCurrent("");
      setPassword("");
      setConfirm("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Your account" subtitle={me ? `${me.user.name || me.user.email} · ${me.user.email}` : undefined}>
      <h2 className="mb-3 text-sm font-semibold text-ink">Change password</h2>
      {done && (
        <FormMessage kind="success">Password changed. You were logged out on all your other devices.</FormMessage>
      )}
      {error && <FormMessage kind="error">{error}</FormMessage>}
      <form onSubmit={onSubmit}>
        <Field
          label="Current password"
          type="password"
          autoComplete="current-password"
          required
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Field
          label="New password again"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <SubmitButton busy={busy}>Change password</SubmitButton>
      </form>
      <p className="mt-4 text-center text-sm">
        <Link href="/" className="text-accent hover:underline">
          ← Back to dashboard
        </Link>
      </p>
    </AuthCard>
  );
}
