"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AuthCard, Field, FormMessage, SubmitButton } from "@/components/auth/AuthCard";
import { ApiError, apiPost } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sentMessage, setSentMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await apiPost<{ message: string }>("/api/auth/forgot-password", { email }, { quiet401: true });
      setSentMessage(result.message);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard title="Reset your password" subtitle="We'll email you a link to choose a new password.">
      {sentMessage ? (
        <FormMessage kind="success">{sentMessage}</FormMessage>
      ) : (
        <>
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
            <SubmitButton busy={busy}>Send reset link</SubmitButton>
          </form>
        </>
      )}
      <p className="mt-4 text-center text-sm">
        <Link href="/login" className="text-accent hover:underline">
          ← Back to log in
        </Link>
      </p>
    </AuthCard>
  );
}
