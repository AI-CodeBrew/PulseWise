"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Button, CodeBlock, Message, SelectField, TextField, useAction } from "@/components/ui/Form";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiPost } from "@/lib/api";
import type { OnboardResult } from "@/lib/types";

function randomPassword(): string {
  const chars = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(14));
  return Array.from(bytes, (b) => chars[b % chars.length]).join("");
}

export default function NewUserPage() {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [businessName, setBusinessName] = useState("");
  const [phone, setPhone] = useState("");
  const [siteName, setSiteName] = useState("");
  const [domain, setDomain] = useState("");
  const [host, setHost] = useState("https://us.posthog.com");
  const [projectId, setProjectId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [token, setToken] = useState("");
  const [orgId, setOrgId] = useState("");
  const [sendEmail, setSendEmail] = useState(true);
  const [done, setDone] = useState<{ result: OnboardResult; password: string } | null>(null);

  const create = useAction(async () => {
    const result = await apiPost<OnboardResult>("/api/admin/users", {
      email,
      name,
      password,
      business_name: businessName || null,
      phone: phone || null,
      website_name: siteName,
      domain: domain || null,
      posthog_host: host,
      posthog_project_id: Number(projectId),
      posthog_api_key: apiKey,
      posthog_project_token: token || null,
      posthog_org_id: orgId || null,
      send_email: sendEmail,
    });
    setDone({ result, password });
    setApiKey("");
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.run();
  }

  if (done) {
    const { result } = done;
    const message = `Your analytics dashboard is ready.\nLogin: ${result.login_url}\nEmail: ${result.email}\nPassword: ${done.password}`;
    return (
      <>
        <PageHeader title="User created" description={`${result.email} can log in now and will see their website's data.`} />
        <Card className="max-w-xl space-y-4 p-5">
          <Message kind="success">
            {result.emailed
              ? "The login details were emailed to them."
              : "Email isn't set up on the server, so nothing was emailed. Send the details below yourself."}
          </Message>
          {!result.token_found && (
            <Message kind="info">The tracking token wasn&apos;t found automatically. Open the website page to paste it and get the install code.</Message>
          )}
          <CodeBlock code={message} label="Login details (e.g. for WhatsApp)" />
          <div className="flex flex-wrap gap-4">
            <Link href={`/admin/websites/${result.website_id}`} className="text-sm text-accent hover:underline">
              Open website / install code →
            </Link>
            <Link href={`/admin/clients/${result.client_id}`} className="text-sm text-accent hover:underline">
              Open client →
            </Link>
            <Link href="/admin/users" className="text-sm text-accent hover:underline">
              All users
            </Link>
          </div>
        </Card>
      </>
    );
  }

  return (
    <>
      <Link href="/admin/users" className="mb-3 inline-block text-sm text-accent hover:underline">
        ← All users
      </Link>
      <PageHeader title="Add user" description="Set their login and the PostHog keys of their website. They'll see only that website's data." />
      <form onSubmit={onSubmit} className="max-w-2xl space-y-5">
        {create.error && <Message kind="error">{create.error}</Message>}

        <Card className="p-5">
          <h2 className="mb-4 text-sm font-semibold text-ink">Login</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="Email (Gmail)" type="email" required autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} />
            <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
            <div className="sm:col-span-2">
              <TextField
                label="Password"
                required
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                hint="At least 8 characters. They can change it later from their Account page."
              />
              <div className="mt-2 flex gap-3">
                <Button
                  variant="ghost"
                  className="!px-2 !py-1 text-xs"
                  onClick={() => {
                    setPassword(randomPassword());
                    setShowPassword(true);
                  }}
                >
                  Generate
                </Button>
                <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => setShowPassword((s) => !s)}>
                  {showPassword ? "Hide" : "Show"}
                </Button>
              </div>
            </div>
            <TextField label="Business name (optional)" value={businessName} onChange={(e) => setBusinessName(e.target.value)} hint="Defaults to their name." />
            <TextField label="Phone / WhatsApp (optional)" value={phone} onChange={(e) => setPhone(e.target.value)} />
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="mb-1 text-sm font-semibold text-ink">Their website &amp; PostHog keys</h2>
          <p className="mb-4 text-xs text-muted">We test the key before saving anything, and store it encrypted. It is never shown again.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="Website name" required value={siteName} onChange={(e) => setSiteName(e.target.value)} placeholder="Ali's Shop" />
            <TextField label="Domain" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="alishop.pk" />
            <SelectField label="PostHog region" value={host} onChange={(e) => setHost(e.target.value)}>
              <option value="https://us.posthog.com">US cloud (us.posthog.com)</option>
              <option value="https://eu.posthog.com">EU cloud (eu.posthog.com)</option>
            </SelectField>
            <TextField
              label="PostHog project ID"
              required
              inputMode="numeric"
              pattern="[0-9]+"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              hint="Settings → Project → Project ID."
            />
            <div className="sm:col-span-2">
              <TextField
                label="Personal API key"
                required
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="phx_…"
                hint="Scopes: Query, Session recording and Person (read), plus Project (read) to find the tracking token automatically."
              />
            </div>
            <TextField label="Project token (optional)" value={token} onChange={(e) => setToken(e.target.value)} placeholder="phc_…" hint="Found automatically if the key may read the project." />
            <TextField label="Organization ID (optional)" value={orgId} onChange={(e) => setOrgId(e.target.value)} />
          </div>
        </Card>

        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={sendEmail} onChange={(e) => setSendEmail(e.target.checked)} />
          Email the login details (email + password) to the user
        </label>

        <Button type="submit" variant="primary" busy={create.busy}>
          Test keys and create user
        </Button>
      </form>
    </>
  );
}
