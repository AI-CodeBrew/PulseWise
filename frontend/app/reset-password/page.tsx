"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthCard, Field, FormMessage, SubmitButton } from "@/components/auth/AuthCard";
import { ApiError, apiPost } from "@/lib/api";

const MIN_LENGTH = 8;

/** Opened from the link in the reset email: /reset-password?token=... */
export default function ResetPasswordPage() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");
  const invited = params.get("invite") === "1"; // came from an invitation, not "forgot password"
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!token) {
    return (
      <AuthCard title="Link incomplete">
        <FormMessage kind="error">This reset link is incomplete. Please open the full link from the email.</FormMessage>
        <p className="text-center text-sm">
          <Link href="/forgot-password" className="text-accent hover:underline">
            Request a new link
          </Link>
        </p>
      </AuthCard>
    );
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (password.length < MIN_LENGTH) return setError(`Password must be at least ${MIN_LENGTH} characters.`);
    if (password !== confirm) return setError("The two passwords don't match.");
    setBusy(true);
    setError(null);
    try {
      await apiPost("/api/auth/reset-password", { token, new_password: password }, { quiet401: true });
      router.replace("/login?reset=1");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title={invited ? "Welcome! Choose your password" : "Choose a new password"}
      subtitle={invited ? `You've been given access. Pick a password to log in (at least ${MIN_LENGTH} characters).` : `At least ${MIN_LENGTH} characters.`}
    >
      {error && <FormMessage kind="error">{error}</FormMessage>}
      <form onSubmit={onSubmit}>
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
        <SubmitButton busy={busy}>{invited ? "Save password" : "Save new password"}</SubmitButton>
      </form>
    </AuthCard>
  );
}
