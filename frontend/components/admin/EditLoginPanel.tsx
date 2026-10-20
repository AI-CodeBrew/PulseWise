"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button, CodeBlock, Message, TextField, useAction } from "@/components/ui/Form";
import { apiPatch } from "@/lib/api";
import { randomPassword } from "@/lib/password";

type LoginResult = {
  email: string;
  email_changed: boolean;
  password_set: boolean;
  login_url: string;
  billing_contact_of: { id: string; name: string }[]; // clients whose INVOICE address is still the old email
};

/**
 * Admin: change a person's login (their email and/or a new password) without asking for the old password:
 * they forgot it, lost their mailbox, or are locked out. After saving, it shows a ready-to-send message with the
 * login details: the admin hands it over themselves (nothing is emailed). Give it a `key` of the user, so that the
 * button of somebody else starts with an empty form. `onSaved` lets the page behind it reload its list.
 */
export function EditLoginPanel({ userId, email, onClose, onSaved }: { userId: string; email: string; onClose: () => void; onSaved: () => void }) {
  const [newEmail, setNewEmail] = useState(email);
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(true); // visible at first: the admin has to read it out to the person
  const [done, setDone] = useState<{ result: LoginResult; password: string } | null>(null);
  const panel = useRef<HTMLDivElement>(null);

  // The button can be far down a long list: bring the form into view.
  useEffect(() => {
    panel.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, []);

  const emailChanged = newEmail.trim().toLowerCase() !== email.toLowerCase();
  const save = useAction(async () => {
    const result = await apiPatch<LoginResult>(`/api/admin/users/${userId}/login`, {
      email: emailChanged ? newEmail.trim() : null,
      password: password || null,
    });
    setDone({ result, password });
    onSaved();
  });

  if (done) {
    const { result } = done;
    const details = ["Your login details.", `Login: ${result.login_url}`, `Email: ${result.email}`, `Password: ${result.password_set ? done.password : "(unchanged)"}`];
    return (
      <div ref={panel} className="space-y-3 rounded-lg border border-line bg-surface p-4">
        <Message kind="success">
          Saved for {email}.{result.email_changed && ` The email is now ${result.email}.`}
          {result.password_set && " A new password is set."} They were logged out on all devices.
        </Message>
        <CodeBlock label="Login details to send them" code={details.join("\n")} />
        {result.billing_contact_of.length > 0 && (
          <Message kind="info">
            Heads-up: the billing email (where invoices go) of{" "}
            {result.billing_contact_of.map((c, i) => (
              <span key={c.id}>
                {i > 0 && ", "}
                <Link href={`/admin/clients/${c.id}`} className="font-medium text-accent hover:underline">
                  {c.name}
                </Link>
              </span>
            ))}{" "}
            is still {email}. Change it on the client&apos;s page if it should follow.
          </Message>
        )}
        <Button onClick={onClose}>Done</Button>
      </div>
    );
  }

  return (
    <div ref={panel} className="rounded-lg border border-line bg-surface p-4">
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          void save.run();
        }}
      >
        <p className="text-sm font-medium text-ink">Edit login of {email}</p>
        <TextField
          label="Email"
          type="email"
          autoComplete="off"
          required
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          hint="Change it if they lost access to this mailbox. They log in with the new address."
        />
        <TextField
          label="New password (optional)"
          type="password"
          shown={shown}
          onShownChange={setShown}
          autoComplete="new-password"
          autoFocus
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Leave empty to keep the current password"
          hint="At least 8 characters. The old password is not needed. Saving logs them out everywhere. Nothing is emailed: you hand over the details."
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" busy={save.busy} disabled={!emailChanged && password === ""}>
            Save
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setPassword(randomPassword());
              setShown(true);
            }}
          >
            Generate password
          </Button>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
        </div>
        {save.error && <Message kind="error">{save.error}</Message>}
      </form>
    </div>
  );
}
