"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Badge, Button, CodeBlock, DangerZone, Message, SelectField, TextArea, TextField, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlanBillingCard } from "@/components/admin/PlanBillingCard";
import { EditLoginPanel } from "@/components/admin/EditLoginPanel";
import { Async, EmptyState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { randomPassword } from "@/lib/password";
import type { AdminClientDetail, AdminMember, AdminWebsite, InviteResult, Me } from "@/lib/types";

export default function ClientDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useApi<AdminClientDetail>(`/api/admin/clients/${id}`);

  return (
    <>
      <Link href="/admin/clients" className="mb-3 inline-block text-sm text-accent hover:underline">
        ← All clients
      </Link>
      <Async query={client} skeleton={<Skeleton className="h-64 rounded-xl" />}>
        {(c) => <ClientDetail client={c} reload={client.reload} />}
      </Async>
    </>
  );
}

function ClientDetail({ client, reload }: { client: AdminClientDetail; reload: () => void }) {
  const router = useRouter();
  const { setMe } = useAuth();

  const toggleStatus = useAction(async () => {
    await apiPatch(`/api/admin/clients/${client.id}`, { status: client.status === "active" ? "suspended" : "active" });
    reload();
  });

  // "View as client": the backend sets a read-only cookie, then we reload who-am-I and open their dashboard.
  const viewAs = useAction(async () => {
    const result = await apiPost<{ website_id: string | null }>("/api/admin/view-as", { client_id: client.id });
    setMe(await apiGet<Me>("/api/auth/me"));
    router.push(result.website_id ? `/sites/${result.website_id}` : "/");
  });

  return (
    <>
      <PageHeader
        title={client.name}
        description={client.contact_email ?? "No contact email yet"}
        action={
          <div className="flex flex-wrap items-center gap-2">
            {client.status === "active" ? <Badge tone="green">Active</Badge> : <Badge tone="red">Suspended</Badge>}
            <Button variant="primary" busy={viewAs.busy} onClick={() => viewAs.run()} disabled={client.websites.length === 0} title={client.websites.length === 0 ? "Add a website first" : undefined}>
              View as client
            </Button>
            <Button busy={toggleStatus.busy} onClick={() => toggleStatus.run()}>
              {client.status === "active" ? "Suspend" : "Re-activate"}
            </Button>
          </div>
        }
      />
      {(viewAs.error || toggleStatus.error) && (
        <div className="mb-4">
          <Message kind="error">{viewAs.error ?? toggleStatus.error}</Message>
        </div>
      )}
      {client.status === "suspended" && (
        <div className="mb-4">
          <Message kind="info">
            {client.suspended_reason === "overdue"
              ? "Suspended automatically: an invoice is overdue. It lifts by itself once the invoice is paid."
              : "This client is suspended: their people can't open their dashboards. You still can."}
          </Message>
        </div>
      )}

      <div className="space-y-6">
        <WebsitesCard client={client} reload={reload} />
        <PlanBillingCard client={client} reload={reload} />
        <MembersCard client={client} reload={reload} />
        <EditCard client={client} reload={reload} />
        <DangerZone
          title="Delete this client"
          description="Removes the client, its websites and everyone's access to them. The PostHog data itself is not touched. This can't be undone."
          confirmName={client.name}
          buttonLabel="Delete client"
          onConfirm={async () => {
            await apiDelete(`/api/admin/clients/${client.id}`, { confirm: client.name });
            router.push("/admin/clients");
          }}
        />
      </div>
    </>
  );
}

// ------------------------------------------------------------------ edit details

function EditCard({ client, reload }: { client: AdminClientDetail; reload: () => void }) {
  const [name, setName] = useState(client.name);
  const [email, setEmail] = useState(client.contact_email ?? "");
  const [phone, setPhone] = useState(client.phone ?? "");
  const [notes, setNotes] = useState(client.notes ?? "");
  const [saved, setSaved] = useState(false);

  const save = useAction(async () => {
    await apiPatch(`/api/admin/clients/${client.id}`, { name, contact_email: email, phone, notes });
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
        <TextField label="Business name" required value={name} onChange={(e) => setName(e.target.value)} />
        <TextField label="Contact email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Phone / WhatsApp" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <div className="sm:col-span-2">
          <TextArea label="Private notes" value={notes} onChange={(e) => setNotes(e.target.value)} hint="Only you can see these." />
        </div>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
          <Button type="submit" variant="primary" busy={save.busy}>
            Save changes
          </Button>
          {saved && !save.error && <span className="text-sm text-good">✓ Saved</span>}
          {save.error && <Message kind="error">{save.error}</Message>}
        </div>
      </form>
    </Card>
  );
}

// ------------------------------------------------------------------ websites

function WebsitesCard({ client, reload }: { client: AdminClientDetail; reload: () => void }) {
  const [adding, setAdding] = useState(client.websites.length === 0);

  return (
    <Card>
      <CardHeader
        title="Websites"
        subtitle="Each website is tracked in its own PostHog project."
        action={
          !adding && (
            <Button variant="secondary" onClick={() => setAdding(true)}>
              + Add website
            </Button>
          )
        }
      />
      {client.websites.length === 0 && !adding ? (
        <EmptyState message="No websites yet." />
      ) : (
        client.websites.length > 0 && (
          <DataTable
            rows={client.websites}
            rowKey={(w) => w.id}
            rowHref={(w) => `/admin/websites/${w.id}`}
            columns={[
              { header: "Website", cell: (w: AdminWebsite) => <span className="font-medium">{w.name}</span> },
              { header: "Domain", className: "hidden sm:table-cell", cell: (w) => w.domain ?? "–" },
              { header: "PostHog project", className: "hidden md:table-cell", cell: (w) => `#${w.posthog_project_id}` },
              { header: "Status", cell: (w) => (w.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="gray">Hidden</Badge>) },
            ]}
          />
        )
      )}
      {adding && (
        <AddWebsiteForm
          clientId={client.id}
          onDone={() => {
            setAdding(false);
            reload();
          }}
          onCancel={client.websites.length > 0 ? () => setAdding(false) : undefined}
        />
      )}
    </Card>
  );
}

function AddWebsiteForm({ clientId, onDone, onCancel }: { clientId: string; onDone: () => void; onCancel?: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [domain, setDomain] = useState("");
  const [host, setHost] = useState("https://us.posthog.com");
  const [projectId, setProjectId] = useState("");
  const [orgId, setOrgId] = useState("");
  const [token, setToken] = useState("");
  const [apiKey, setApiKey] = useState("");

  const create = useAction(async () => {
    const website = await apiPost<AdminWebsite>(`/api/admin/clients/${clientId}/websites`, {
      name,
      domain: domain || null,
      posthog_host: host,
      posthog_project_id: Number(projectId),
      posthog_org_id: orgId || null,
      posthog_project_token: token || null,
      posthog_api_key: apiKey,
    });
    onDone();
    router.push(`/admin/websites/${website.id}`); // next step: install the tracking code
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.run();
  }

  return (
    <form onSubmit={onSubmit} className="border-t border-line px-4 py-5 sm:px-5">
      <h3 className="mb-1 text-sm font-semibold text-ink">Add a website</h3>
      <p className="mb-4 text-xs text-muted">
        In PostHog, create a project for this website first (Settings → Projects). We test the key before saving it, and store it encrypted.
      </p>
      {create.error && (
        <div className="mb-4">
          <Message kind="error">{create.error}</Message>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField label="Website name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Ali's Shop" />
        <TextField label="Domain" value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="alishop.pk" />
        <SelectField label="PostHog region" value={host} onChange={(e) => setHost(e.target.value)} hint="The region of YOUR PostHog account.">
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
          hint="Settings → Project → Project ID (a number)."
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
            hint="Settings → User → Personal API keys. Scopes: Query, Session recording and Person (read), plus Project (read) to find the tracking token automatically."
          />
        </div>
        <TextField label="Organization ID (optional)" value={orgId} onChange={(e) => setOrgId(e.target.value)} />
        <TextField label="Project token (optional)" value={token} onChange={(e) => setToken(e.target.value)} placeholder="phc_…" hint="Found automatically if the key may read the project." />
      </div>
      <div className="mt-5 flex gap-3">
        <Button type="submit" variant="primary" busy={create.busy}>
          Test and add website
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}

// ------------------------------------------------------------------ members

function MembersCard({ client, reload }: { client: AdminClientDetail; reload: () => void }) {
  const [inviting, setInviting] = useState(client.members.length === 0);
  const [added, setAdded] = useState<{ result: InviteResult; password: string } | null>(null); // what to hand over after "Add a person"
  const [loginFor, setLoginFor] = useState<AdminMember | null>(null);

  return (
    <Card>
      <CardHeader
        title="People"
        subtitle="Who can log in and see this client's websites."
        action={
          !inviting && (
            <Button variant="secondary" onClick={() => setInviting(true)}>
              + Add person
            </Button>
          )
        }
      />
      {added && <AddedBanner result={added.result} password={added.password} />}
      {loginFor && (
        <div className="px-4 pb-4 sm:px-5">
          <EditLoginPanel key={loginFor.user_id} userId={loginFor.user_id} email={loginFor.email} onClose={() => setLoginFor(null)} onSaved={reload} />
        </div>
      )}
      {client.members.length === 0 && !inviting ? (
        <EmptyState message="Nobody has access yet." />
      ) : (
        client.members.length > 0 && (
          <MembersTable
            client={client}
            reload={reload}
            onEditLogin={(member) => {
              setAdded(null);
              setLoginFor(member);
            }}
          />
        )
      )}
      {inviting && (
        <InviteForm
          clientId={client.id}
          onAdded={(result, password) => {
            setAdded({ result, password });
            setInviting(false);
            reload();
          }}
          onCancel={client.members.length > 0 ? () => setInviting(false) : undefined}
        />
      )}
    </Card>
  );
}

/** After "Add a person": the login details to hand over, or (for somebody who already had an account) a note that the typed password was not used. */
function AddedBanner({ result, password }: { result: InviteResult; password: string }) {
  if (!result.new_user) {
    return (
      <div className="px-4 pb-4 sm:px-5">
        <Message kind="info">
          {result.email} already had an account, so they now have access with their own password (the one you typed was not used). To change it, use &quot;Edit login&quot;.
        </Message>
      </div>
    );
  }
  return (
    <div className="space-y-3 px-4 pb-4 sm:px-5">
      <Message kind="success">{result.email} was added. Send them these login details:</Message>
      <CodeBlock
        label={`Login details for ${result.email}`}
        code={`Your login details.\nLogin: ${result.login_url}\nEmail: ${result.email}\nPassword: ${password}`}
      />
    </div>
  );
}

function MembersTable({ client, reload, onEditLogin }: { client: AdminClientDetail; reload: () => void; onEditLogin: (member: AdminMember) => void }) {
  const action = useAction(async (run: () => Promise<unknown>) => {
    await run();
    reload();
  });

  return (
    <>
      {action.error && (
        <div className="px-4 pb-3 sm:px-5">
          <Message kind="error">{action.error}</Message>
        </div>
      )}
      <DataTable
        rows={client.members}
        rowKey={(m) => m.user_id}
        columns={[
          {
            header: "Person",
            cell: (m: AdminMember) => (
              <div>
                <span className="font-medium">{m.name || m.email}</span>
                {m.name && <span className="block text-xs text-muted">{m.email}</span>}
                {!m.is_active && <Badge tone="gray">Deactivated</Badge>}
              </div>
            ),
          },
          {
            header: "Role",
            cell: (m) => (
              <select
                aria-label={`Role of ${m.email}`}
                value={m.role}
                onChange={(e) => action.run(() => apiPatch(`/api/admin/clients/${client.id}/members/${m.user_id}`, { role: e.target.value }))}
                className="rounded-md border border-line bg-page px-2 py-1 text-sm"
              >
                <option value="owner">Owner</option>
                <option value="viewer">Viewer</option>
              </select>
            ),
          },
          { header: "Last login", className: "hidden sm:table-cell", cell: (m) => (m.last_login_at ? formatDateTime(m.last_login_at) : "never") },
          {
            header: "",
            align: "right",
            cell: (m) => (
              <div className="flex flex-wrap justify-end gap-2">
                {!m.is_admin && (
                  <Button variant="ghost" className="!px-2 !py-1 text-xs" onClick={() => onEditLogin(m)}>
                    Edit login
                  </Button>
                )}
                <Button
                  variant="ghost"
                  className="!px-2 !py-1 text-xs !text-bad"
                  onClick={() => {
                    if (window.confirm(`Remove ${m.email}'s access to ${client.name}?`)) {
                      action.run(() => apiDelete(`/api/admin/clients/${client.id}/members/${m.user_id}`));
                    }
                  }}
                >
                  Remove
                </Button>
              </div>
            ),
          },
        ]}
      />
    </>
  );
}

function InviteForm({ clientId, onAdded, onCancel }: { clientId: string; onAdded: (r: InviteResult, password: string) => void; onCancel?: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"owner" | "viewer">("owner");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);

  const add = useAction(async () => {
    const result = await apiPost<InviteResult>(`/api/admin/clients/${clientId}/members`, { email, name, role, password: password || null });
    setEmail("");
    setName("");
    setPassword("");
    onAdded(result, password);
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    add.run();
  }

  return (
    <form onSubmit={onSubmit} className="border-t border-line px-4 py-5 sm:px-5">
      <h3 className="mb-3 text-sm font-semibold text-ink">Add a person</h3>
      {add.error && (
        <div className="mb-4">
          <Message kind="error">{add.error}</Message>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-3">
        <TextField label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />
        <SelectField label="Role" value={role} onChange={(e) => setRole(e.target.value as "owner" | "viewer")} hint="Owners will manage the team and billing; viewers only look.">
          <option value="owner">Owner</option>
          <option value="viewer">Viewer</option>
        </SelectField>
        <div className="sm:col-span-2">
          <TextField
            label="Password"
            type="password"
            shown={shown}
            onShownChange={setShown}
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            hint="Required: this is how they log in. At least 8 characters. You send them the login details afterwards. If this person already has an account, their own password stays (this one is not used)."
          />
          <div className="mt-2">
            <Button
              variant="ghost"
              className="!px-2 !py-1 text-xs"
              onClick={() => {
                setPassword(randomPassword());
                setShown(true);
              }}
            >
              Generate
            </Button>
          </div>
        </div>
      </div>
      <div className="mt-4 flex gap-3">
        <Button type="submit" variant="primary" busy={add.busy}>
          Add person
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
