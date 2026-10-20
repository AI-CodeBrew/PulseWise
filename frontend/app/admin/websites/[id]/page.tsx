"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Card, CardHeader } from "@/components/ui/Card";
import { Badge, Button, CodeBlock, DangerZone, Message, SelectField, TextField, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, ErrorState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiDelete, apiPatch, apiPost, apiPut } from "@/lib/api";
import { formatDateTime, formatNumber, timeAgo } from "@/lib/format";
import { installGuides, POSTHOG_SETUP_STEPS } from "@/lib/installGuides";
import { UsageChart } from "@/components/charts/UsageChart";
import { REPORT_LANGUAGES, type AdminShopify, type AdminWebsite, type ReportLanguage, type SnippetInfo, type UsagePoint, type WebsiteCheck } from "@/lib/types";

export default function WebsiteDetailPage() {
  const { id } = useParams<{ id: string }>();
  const website = useApi<AdminWebsite>(`/api/admin/websites/${id}`);

  return (
    <Async query={website} skeleton={<Skeleton className="h-64 rounded-xl" />}>
      {(w) => <WebsiteDetail website={w} reload={website.reload} />}
    </Async>
  );
}

function WebsiteDetail({ website, reload }: { website: AdminWebsite; reload: () => void }) {
  const router = useRouter();
  return (
    <>
      <Link href={`/admin/clients/${website.client_id}`} className="mb-3 inline-block text-sm text-accent hover:underline">
        ← {website.client_name ?? "Client"}
      </Link>
      <PageHeader
        title={website.name}
        description={website.domain ?? "No domain set"}
        action={website.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Hidden from the client</Badge>}
      />
      <div className="space-y-6">
        <HealthCard websiteId={website.id} />
        <UsageCard websiteId={website.id} />
        <ReportCard websiteId={website.id} />
        <ShopifyCard websiteId={website.id} />
        <InstallCard websiteId={website.id} onTokenSaved={reload} />
        <ConnectionCard website={website} reload={reload} />
        <DetailsCard website={website} reload={reload} />
        <DangerZone
          title="Delete this website"
          description="Removes it from the client's dashboard and deletes the stored connection. The data in PostHog is not touched. This can't be undone."
          confirmName={website.name}
          buttonLabel="Delete website"
          onConfirm={async () => {
            await apiDelete(`/api/admin/websites/${website.id}`, { confirm: website.name });
            router.push(`/admin/clients/${website.client_id}`);
          }}
        />
      </div>
    </>
  );
}

// ------------------------------------------------------------------ "is data arriving?"

function HealthCard({ websiteId }: { websiteId: string }) {
  const check = useApi<WebsiteCheck>(`/api/admin/websites/${websiteId}/check`);

  return (
    <Card>
      <CardHeader
        title="Is data arriving?"
        action={
          <Button variant="secondary" busy={check.loading} onClick={check.reload}>
            Check again
          </Button>
        }
      />
      <Async query={check} skeleton={<Skeleton className="mx-5 mb-5 h-20" />}>
        {(c) => {
          if (!c.connection.ok || !c.health) {
            return (
              <div className="px-4 pb-5 sm:px-5">
                <Message kind="error">The connection to PostHog is not working: {c.connection.message}</Message>
                <p className="mt-2 text-xs text-muted">Fix it in “PostHog connection” below (for example, enter a new API key).</p>
              </div>
            );
          }
          const h = c.health;
          const headline = {
            green: ["green", "Yes, data is arriving"],
            amber: ["amber", "No data in the last 24 hours"],
            red: ["red", "No data for 2 days or more"],
          } as const;
          const [tone, text] = headline[h.status];
          return (
            <div className="px-4 pb-5 sm:px-5">
              <div className="flex flex-wrap items-center gap-3">
                <Badge tone={tone}>{text}</Badge>
                <span className="text-sm text-ink-2">
                  {formatNumber(h.events_24h)} events · {formatNumber(h.pageviews_24h)} pageviews in the last 24 hours
                </span>
              </div>
              <p className="mt-2 text-sm text-muted">
                {h.last_event_at
                  ? `Last event: ${timeAgo(h.last_event_at)} (${formatDateTime(h.last_event_at)})`
                  : "No event has ever arrived in the last 90 days."}
              </p>
              {h.status !== "green" && <p className="mt-2 text-sm text-ink-2">Not working yet? Check that the tracking code below is installed on every page.</p>}
            </div>
          );
        }}
      </Async>
    </Card>
  );
}

// ------------------------------------------------------------------ events per day

function UsageCard({ websiteId }: { websiteId: string }) {
  const usage = useApi<{ series: UsagePoint[] }>(`/api/admin/usage/websites/${websiteId}`, { days: 30 });
  return (
    <Card>
      <CardHeader title="Events per day" subtitle="What this website costs you at PostHog (last 30 days)" />
      <Async query={usage} skeleton={<Skeleton className="mx-5 mb-5 h-48" />}>
        {(u) => <UsageChart data={u.series} />}
      </Async>
    </Card>
  );
}

// ------------------------------------------------------------------ tracking code + install guides

function InstallCard({ websiteId, onTokenSaved }: { websiteId: string; onTokenSaved: () => void }) {
  const info = useApi<SnippetInfo>(`/api/admin/websites/${websiteId}/snippet`);
  const [guideId, setGuideId] = useState("shopify");
  const [token, setToken] = useState("");

  const saveToken = useAction(async () => {
    await apiPatch(`/api/admin/websites/${websiteId}`, { posthog_project_token: token.trim() });
    info.reload();
    onTokenSaved();
  });

  return (
    <Card>
      <CardHeader title="Install the tracking code" subtitle="This is what makes a website send visitor data." />
      <Async query={info} skeleton={<Skeleton className="mx-5 mb-5 h-40" />}>
        {(s) => {
          if (s.needs_token || !s.snippet || !s.project_token) {
            return (
              <div className="space-y-3 px-4 pb-5 sm:px-5">
                <Message kind="info">
                  We couldn&apos;t read the project&apos;s public token automatically (the API key may lack the “Project: read” scope). Paste it here:
                  PostHog → Settings → Project → <em>Project token</em> (starts with phc_).
                </Message>
                <div className="flex flex-wrap items-end gap-3">
                  <div className="min-w-64 flex-1">
                    <TextField label="Project token" value={token} onChange={(e) => setToken(e.target.value)} placeholder="phc_…" />
                  </div>
                  <Button variant="primary" busy={saveToken.busy} disabled={!token.trim().startsWith("phc_")} onClick={() => saveToken.run()}>
                    Save token
                  </Button>
                </div>
                {saveToken.error && <Message kind="error">{saveToken.error}</Message>}
              </div>
            );
          }
          const guides = installGuides(s.project_token, s.api_host);
          const guide = guides.find((g) => g.id === guideId) ?? guides[0];
          return (
            <div className="space-y-5 px-4 pb-5 sm:px-5">
              <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-2">
                {POSTHOG_SETUP_STEPS.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>

              <CodeBlock code={s.snippet} label="Tracking code (paste before </head>)" />

              <div>
                <div role="tablist" aria-label="Platform" className="mb-3 flex flex-wrap gap-1">
                  {guides.map((g) => (
                    <button
                      key={g.id}
                      type="button"
                      role="tab"
                      aria-selected={g.id === guide.id}
                      onClick={() => setGuideId(g.id)}
                      className={`rounded-md px-3 py-1.5 text-sm ${g.id === guide.id ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-surface-2"}`}
                    >
                      {g.label}
                    </button>
                  ))}
                </div>
                <p className="mb-2 text-sm text-ink">{guide.intro}</p>
                <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-2">
                  {guide.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
                {guide.code && (
                  <div className="mt-3">
                    <CodeBlock code={guide.code.text} label={guide.code.label} />
                  </div>
                )}
                {guide.note && <p className="mt-3 text-xs text-muted">{guide.note}</p>}
              </div>
            </div>
          );
        }}
      </Async>
    </Card>
  );
}

// ------------------------------------------------------------------ PostHog connection

function ConnectionCard({ website, reload }: { website: AdminWebsite; reload: () => void }) {
  const [host, setHost] = useState(website.posthog_host);
  const [projectId, setProjectId] = useState(String(website.posthog_project_id));
  const [orgId, setOrgId] = useState(website.posthog_org_id ?? "");
  const [token, setToken] = useState(website.posthog_project_token ?? "");
  const [newKey, setNewKey] = useState("");
  const [saved, setSaved] = useState(false);

  const save = useAction(async () => {
    const body: Record<string, unknown> = {
      posthog_host: host,
      posthog_project_id: Number(projectId),
      posthog_org_id: orgId,
      posthog_project_token: token,
    };
    if (newKey.trim()) body.posthog_api_key = newKey.trim();
    await apiPatch(`/api/admin/websites/${website.id}`, body);
    setNewKey("");
    setSaved(true);
    reload();
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaved(false);
    save.run();
  }

  return (
    <Card>
      <CardHeader title="PostHog connection" subtitle="Used by the backend only. Clients never see any of this." />
      <form onSubmit={onSubmit} className="grid gap-4 px-4 pb-5 sm:grid-cols-2 sm:px-5">
        <SelectField label="Region" value={host} onChange={(e) => setHost(e.target.value)}>
          <option value="https://us.posthog.com">US cloud (us.posthog.com)</option>
          <option value="https://eu.posthog.com">EU cloud (eu.posthog.com)</option>
        </SelectField>
        <TextField label="Project ID" required inputMode="numeric" pattern="[0-9]+" value={projectId} onChange={(e) => setProjectId(e.target.value)} />
        <TextField label="Organization ID" value={orgId} onChange={(e) => setOrgId(e.target.value)} />
        <TextField label="Project token (public)" value={token} onChange={(e) => setToken(e.target.value)} placeholder="phc_…" />
        <div className="sm:col-span-2">
          <TextField
            label="Replace the API key"
            type="password"
            autoComplete="off"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            placeholder="Leave empty to keep the current key"
            hint={`A key is stored, encrypted (${website.has_api_key ? "✓" : "none"}). It can never be shown again, only replaced. Any change is tested against PostHog before it is saved.`}
          />
        </div>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <Button type="submit" variant="primary" busy={save.busy}>
            Test and save
          </Button>
          {saved && !save.error && <span className="text-sm text-good">✓ Saved</span>}
        </div>
        {save.error && (
          <div className="sm:col-span-2">
            <Message kind="error">{save.error}</Message>
          </div>
        )}
      </form>
    </Card>
  );
}

// ------------------------------------------------------------------ name, domain, visibility

function DetailsCard({ website, reload }: { website: AdminWebsite; reload: () => void }) {
  const [name, setName] = useState(website.name);
  const [domain, setDomain] = useState(website.domain ?? "");
  const [active, setActive] = useState(website.is_active);
  const [saved, setSaved] = useState(false);

  const save = useAction(async () => {
    await apiPatch(`/api/admin/websites/${website.id}`, { name, domain, is_active: active });
    setSaved(true);
    reload();
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setSaved(false);
    save.run();
  }

  return (
    <Card>
      <CardHeader title="Details" />
      <form onSubmit={onSubmit} className="grid gap-4 px-4 pb-5 sm:grid-cols-2 sm:px-5">
        <TextField label="Website name" required value={name} onChange={(e) => setName(e.target.value)} />
        <TextField label="Domain" value={domain} onChange={(e) => setDomain(e.target.value)} />
        <label className="flex items-center gap-2 text-sm text-ink sm:col-span-2">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
          Show this website in the client&apos;s dashboard
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <Button type="submit" variant="primary" busy={save.busy}>
            Save
          </Button>
          {saved && !save.error && <span className="text-sm text-good">✓ Saved</span>}
          {save.error && <ErrorState message={save.error} />}
        </div>
      </form>
    </Card>
  );
}

// ------------------------------------------------------------------ weekly report

/** Make last week's report right now (for a first report, a test, or a re-send), and optionally email it to the owners. */
function ReportCard({ websiteId }: { websiteId: string }) {
  const [language, setLanguage] = useState<"" | ReportLanguage>("");
  const [done, setDone] = useState<{ id: string; emailed: number; whatsapp: boolean; send: boolean } | null>(null);
  const make = useAction(async (send: boolean) => {
    setDone(null);
    const r = await apiPost<{ report_id: string; emailed_to: number; whatsapp_sent: boolean }>(`/api/admin/websites/${websiteId}/reports`, {
      send,
      language: language || null,
    });
    setDone({ id: r.report_id, emailed: r.emailed_to, whatsapp: r.whatsapp_sent, send });
  });

  return (
    <Card>
      <CardHeader title="Weekly report" subtitle="Reports are made automatically every Monday morning. Use this to make last week's now." />
      <div className="space-y-4 px-4 pb-5 sm:px-5">
        <div className="max-w-xs">
          <SelectField label="Language" value={language} onChange={(e) => setLanguage(e.target.value as "" | ReportLanguage)}>
            <option value="">The client&apos;s setting</option>
            {REPORT_LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </SelectField>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button busy={make.busy} onClick={() => make.run(false)}>
            Make report
          </Button>
          <Button variant="primary" busy={make.busy} onClick={() => make.run(true)}>
            Make and send to owners
          </Button>
        </div>
        {make.error && <Message kind="error">{make.error}</Message>}
        {done && (
          <Message kind="success">
            Report made.{" "}
            {done.send
              ? `${done.emailed > 0 ? `Emailed to ${done.emailed} owner${done.emailed > 1 ? "s" : ""}.` : "Nobody was emailed (email isn't set up, or the account has no owners)."} ${done.whatsapp ? "Sent on WhatsApp." : "Not sent on WhatsApp (not set up, or the client hasn't opted in)."}`
              : "It is visible on the client's Weekly reports page."}
          </Message>
        )}
      </div>
    </Card>
  );
}

// ------------------------------------------------------------------ Shopify

/** Connect this website to its Shopify store, so the client's weekly report gets a "Your store" section (orders, revenue, best sellers). */
function ShopifyCard({ websiteId }: { websiteId: string }) {
  const shop = useApi<AdminShopify>(`/api/admin/websites/${websiteId}/shopify`);
  const [editing, setEditing] = useState(false);
  const [domain, setDomain] = useState("");
  const [mode, setMode] = useState<"token" | "client_credentials">("token");
  const [token, setToken] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const connect = useAction(async () => {
    setNote(null);
    const body = mode === "token" ? { shop_domain: domain, access_token: token } : { shop_domain: domain, client_id: clientId, client_secret: clientSecret };
    await apiPut(`/api/admin/websites/${websiteId}/shopify`, body);
    setToken("");
    setClientSecret(""); // never keep secrets in the page longer than needed
    setEditing(false);
    setNote("Connected. The last 60 days of orders are being read now: refresh in a moment.");
    shop.reload();
  });
  const sync = useAction(async () => {
    setNote(null);
    const r = await apiPost<{ orders: number }>(`/api/admin/websites/${websiteId}/shopify/sync`);
    setNote(`Synced: ${r.orders} order${r.orders === 1 ? "" : "s"} read.`);
    shop.reload();
  });
  const disconnect = useAction(async () => {
    await apiDelete(`/api/admin/websites/${websiteId}/shopify`);
    setNote(null);
    shop.reload();
  });

  return (
    <Card>
      <CardHeader title="Shopify store" subtitle="Orders are copied every hour (no customer details). The client sees their store sales in the weekly report." />
      <Async query={shop} skeleton={<Skeleton className="mx-5 mb-5 h-20" />}>
        {(c) => (
          <div className="space-y-4 px-4 pb-5 sm:px-5">
            {c.connected && !editing && (
              <div className="space-y-2 text-sm">
                <div className="flex flex-wrap items-center gap-3">
                  <Badge tone={c.last_error ? "red" : "green"}>{c.last_error ? "Sync is failing" : "Connected"}</Badge>
                  <span className="font-medium text-ink">{c.shop_name}</span>
                  <span className="text-ink-2">{c.shop_domain}</span>
                </div>
                <p className="text-ink-2">
                  {formatNumber(c.orders_stored ?? 0)} orders stored · currency {c.currency ?? "?"} · API {c.api_version} ·{" "}
                  {c.last_synced_at ? `last sync ${timeAgo(c.last_synced_at)}` : "not synced yet"}
                </p>
                {c.last_error && <Message kind="error">{c.last_error}</Message>}
              </div>
            )}
            {!c.connected && !editing && <p className="text-sm text-ink-2">No store connected.</p>}

            {editing && (
              <form
                className="space-y-3"
                onSubmit={(e: FormEvent) => {
                  e.preventDefault();
                  void connect.run();
                }}
              >
                <TextField label="Store address" placeholder="my-shop.myshopify.com" value={domain} onChange={(e) => setDomain(e.target.value)} required />
                <SelectField label="Log in with" value={mode} onChange={(e) => setMode(e.target.value as "token" | "client_credentials")}>
                  <option value="token">An Admin API access token (starts with shpat_)</option>
                  <option value="client_credentials">A Dev Dashboard app (Client ID + secret)</option>
                </SelectField>
                {mode === "token" ? (
                  <TextField label="Admin API access token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} required />
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField label="Client ID" autoComplete="off" value={clientId} onChange={(e) => setClientId(e.target.value)} required />
                    <TextField label="Client secret" type="password" autoComplete="off" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} required />
                  </div>
                )}
                <p className="text-xs text-muted">
                  The app needs the <strong>read_orders</strong> access scope (plus <strong>read_all_orders</strong> to read orders older than 60 days). The login is tested before it is saved, and stored encrypted.
                </p>
                <div className="flex gap-3">
                  <Button type="submit" variant="primary" busy={connect.busy}>
                    Test and connect
                  </Button>
                  <Button variant="ghost" onClick={() => setEditing(false)}>
                    Cancel
                  </Button>
                </div>
              </form>
            )}

            {!editing && (
              <div className="flex flex-wrap gap-3">
                <Button variant={c.connected ? "secondary" : "primary"} onClick={() => setEditing(true)}>
                  {c.connected ? "Change login" : "Connect Shopify store"}
                </Button>
                {c.connected && (
                  <>
                    <Button busy={sync.busy} onClick={() => sync.run()}>
                      Sync now
                    </Button>
                    <Button
                      variant="ghost"
                      busy={disconnect.busy}
                      onClick={() => {
                        if (window.confirm("Disconnect this store? The copied orders are deleted and the \"Your store\" part of the client's weekly report will be empty.")) void disconnect.run();
                      }}
                    >
                      Disconnect
                    </Button>
                  </>
                )}
              </div>
            )}
            {note && <Message kind="success">{note}</Message>}
            {(connect.error || sync.error || disconnect.error) && <Message kind="error">{connect.error || sync.error || disconnect.error}</Message>}
          </div>
        )}
      </Async>
    </Card>
  );
}
