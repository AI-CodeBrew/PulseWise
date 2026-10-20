"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Button, Message, TextField, useAction } from "@/components/ui/Form";
import { apiPost } from "@/lib/api";
import type { Me } from "@/lib/types";

/**
 * What /admin shows until the admin has typed their password once more. Logging in is not enough for the admin panel:
 * somebody who borrows a logged-in browser must not be able to open it. The backend refuses every admin call
 * until this is done (423), so this screen is not the protection itself: it is how the admin takes the step.
 */
export function AdminUnlock() {
  const { me, setMe } = useAuth();
  const [password, setPassword] = useState("");
  const unlock = useAction(async () => {
    // (quiet401: a mistake here must never count as "your session ended")
    const next = await apiPost<Me>("/api/auth/admin-unlock", { password }, { quiet401: true });
    setPassword("");
    setMe(next);
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    unlock.run();
  }

  return (
    <main data-admin-unlock className="grid min-h-screen place-items-center bg-page px-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-xl border border-line bg-surface p-6">
        <div>
          <h1 className="text-lg font-semibold text-ink">Open the admin panel</h1>
          <p className="mt-1 text-sm text-ink-2">
            For safety, please type your password again. The panel then stays open while you use it, and closes itself after a while without use.
          </p>
          <p className="mt-2 text-xs text-muted">Signed in as {me?.user.email}</p>
        </div>
        <TextField
          label="Password"
          type="password"
          autoComplete="current-password"
          autoFocus
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {unlock.error && <Message kind="error">{unlock.error}</Message>}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" busy={unlock.busy} disabled={password === ""}>
            Open admin panel
          </Button>
          <Link href="/" className="text-sm text-accent hover:underline">
            Back to my dashboard
          </Link>
        </div>
      </form>
    </main>
  );
}
