"use client";

import { useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Badge, Button, CopyButton, Message, SelectField, TextField, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useCurrentSite } from "@/hooks/useSite";
import { apiDelete, apiPatch, apiPost, apiPut } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { ClientSettings, Team, TeamMember } from "@/lib/types";

/** The client's own settings: business name, weekly report, and who has access. Owners only. */
export default function SettingsPage() {
  const site = useCurrentSite();
  const canSee = site?.role === "owner" || site?.role === "admin";
  const clientId = site?.client_id;
  const settings = useApi<ClientSettings>(canSee && clientId ? `/api/clients/${clientId}/settings` : null);
  const team = useApi<Team>(canSee && clientId ? `/api/clients/${clientId}/team` : null);

  if (!site || !clientId) return null;
  if (!canSee) {
    return (
      <>
        <PageHeader title="Settings" />
        <Card>
          <EmptyState message="Only the account owner can change settings." />
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader title="Settings" description="Your business details, and who can see this dashboard." />
      <div className="space-y-6">
        <Async query={settings} skeleton={<Skeleton className="h-56 rounded-xl" />}>
          {(s) => <BusinessCard clientId={clientId} settings={s} reload={settings.reload} />}
        </Async>
        <Async query={team} skeleton={<Skeleton className="h-64 rounded-xl" />}>
          {(t) => <TeamCard clientId={clientId} team={t} reload={team.reload} />}
        </Async>
      </div>
    </>
  );
}

// ------------------------------------------------------------------ business details

function BusinessCard({ clientId, settings, reload }: { clientId: string; settings: ClientSettings; reload: () => void }) {
  const { refresh } = useAuth();
  const [name, setName] = useState(settings.name);
  const [weekly, setWeekly] = useState(settings.weekly_report_enabled);
  const [whatsappNumber, setWhatsappNumber] = useState(settings.whatsapp_number ? `+${settings.whatsapp_number}` : "");
  const [whatsappOn, setWhatsappOn] = useState(settings.whatsapp_reports_enabled);
  const [saved, setSaved] = useState(false);

  const save = useAction(async () => {
    setSaved(false);
    await apiPatch(`/api/clients/${clientId}/settings`, {
      name,
      weekly_report_enabled: weekly,
      // Only sent when the section is shown (otherwise there is nothing to change).
      ...(settings.whatsapp_available ? { whatsapp_number: whatsappNumber, whatsapp_reports_enabled: whatsappOn && whatsappNumber.trim() !== "" } : {}),
    });
    setSaved(true);
    refresh(); // the name is shown in other places too
    reload();
  });

  return (
    <Card>
      <CardHeader title="Your business" />
      <form
        className="space-y-4 px-4 pb-5 sm:px-5"
        onSubmit={(e) => {
          e.preventDefault();
          void save.run();
        }}
      >
        <div className="max-w-md">
          <TextField label="Business name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required />
        </div>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={weekly} onChange={(e) => setWeekly(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
          Send me the weekly report by email every Monday
        </label>
        {settings.whatsapp_available && (
          <div className="space-y-3 rounded-lg border border-line p-3">
            <TextField
              label="WhatsApp number"
              type="tel"
              placeholder="+92 300 1234567"
              value={whatsappNumber}
              onChange={(e) => setWhatsappNumber(e.target.value)}
              hint="With the country code. Used only to send you your weekly report."
            />
            <label className="flex items-center gap-2 text-sm text-ink">
              <input type="checkbox" checked={whatsappOn} onChange={(e) => setWhatsappOn(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
              Also send me the weekly report on WhatsApp
            </label>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary" busy={save.busy}>
            Save changes
          </Button>
          {saved && <Message kind="success">Saved.</Message>}
        </div>
        {save.error && <Message kind="error">{save.error}</Message>}
      </form>
    </Card>
  );
}

// ------------------------------------------------------------------ team

type Created = { email: string; passwordSet: boolean; newAccount: boolean; link: string | null; password: string };

function TeamCard({ clientId, team, reload }: { clientId: string; team: Team; reload: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"owner" | "viewer">("viewer");
  const [password, setPassword] = useState("");
  const [created, setCreated] = useState<Created | null>(null);
  const [settingFor, setSettingFor] = useState<TeamMember | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [passwordDone, setPasswordDone] = useState<string | null>(null);

  const invite = useAction(async () => {
    const result = await apiPost<{ email: string; invite_link: string | null; password_set: boolean; new_account: boolean }>(`/api/clients/${clientId}/team`, {
      email,
      name,
      role,
      password: password || null,
    });
    setCreated({ email: result.email, passwordSet: result.password_set, newAccount: result.new_account, link: result.invite_link, password });
    setEmail("");
    setName("");
    setPassword("");
    reload();
  });
  const patch = useAction(async (userId: string, body: { role?: string; suspended?: boolean }) => {
    await apiPatch(`/api/clients/${clientId}/team/${userId}`, body);
    reload();
  });
  const remove = useAction(async (userId: string) => {
    await apiDelete(`/api/clients/${clientId}/team/${userId}`);
    reload();
  });
  const setPass = useAction(async () => {
    if (!settingFor) return;
    await apiPut(`/api/clients/${clientId}/team/${settingFor.user_id}/password`, { password: newPassword });
    setPasswordDone(settingFor.email);
    setSettingFor(null);
    setNewPassword("");
    reload();
  });

  return (
    <Card>
      <CardHeader
        title="People with access"
        subtitle={team.max_members ? `Your plan includes up to ${team.max_members} people.` : "Owners can change everything. Viewers can only look at the dashboard."}
      />
      <DataTable
        rows={team.members}
        rowKey={(m) => m.user_id}
        columns={[
          {
            header: "Person",
            cell: (m) => (
              <div>
                <p className="font-medium text-ink">
                  {m.name || m.email}
                  {m.is_you && <span className="ms-1.5 text-xs font-normal text-muted">(you)</span>}
                </p>
                {m.name && <p className="text-xs text-muted">{m.email}</p>}
                {m.suspended && (
                  <div className="mt-1">
                    <Badge tone="red">Suspended</Badge>
                  </div>
                )}
              </div>
            ),
          },
          {
            header: "Last login",
            className: "hidden md:table-cell",
            cell: (m) => (m.last_login_at ? formatDateTime(m.last_login_at) : <span className="text-muted">Not yet</span>),
          },
          {
            header: "Role",
            cell: (m) => (
              <select
                aria-label={`Role of ${m.email}`}
                value={m.role}
                disabled={patch.busy}
                onChange={(e) => patch.run(m.user_id, { role: e.target.value })}
                className="rounded-md border border-line bg-page px-2 py-1 text-sm text-ink"
              >
                <option value="owner">Owner</option>
                <option value="viewer">Viewer</option>
              </select>
            ),
          },
          {
            header: "Actions",
            align: "right",
            cell: (m) => (
              <div className="flex flex-wrap justify-end gap-1">
                {m.can_set_password && (
                  <Button
                    variant="ghost"
                    className="!px-2 !py-1 text-xs"
                    aria-label={`Set a new password for ${m.email}`}
                    onClick={() => {
                      setPasswordDone(null);
                      setNewPassword("");
                      setSettingFor(m);
                    }}
                  >
                    Set password
                  </Button>
                )}
                {!m.is_you && (
                  <Button
                    variant="ghost"
                    className="!px-2 !py-1 text-xs"
                    aria-label={`${m.suspended ? "Activate" : "Suspend"} ${m.email}`}
                    onClick={() => patch.run(m.user_id, { suspended: !m.suspended })}
                  >
                    {m.suspended ? "Activate" : "Suspend"}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  className="!px-2 !py-1 text-xs"
                  aria-label={`Remove ${m.email}`}
                  onClick={() => {
                    if (window.confirm(`Remove ${m.email}? They will no longer be able to open this dashboard.`)) void remove.run(m.user_id);
                  }}
                >
                  Remove
                </Button>
              </div>
            ),
          },
        ]}
      />
      {(patch.error || remove.error) && (
        <div className="px-4 pt-3 sm:px-5">
          <Message kind="error">{patch.error || remove.error}</Message>
        </div>
      )}
      {passwordDone && (
        <div className="px-4 pt-3 sm:px-5">
          <Message kind="success">New password set for {passwordDone}. They were logged out and must use the new one.</Message>
        </div>
      )}

      {settingFor && (
        <form
          className="mx-4 mt-3 space-y-3 rounded-lg border border-line p-3 sm:mx-5"
          onSubmit={(e) => {
            e.preventDefault();
            void setPass.run();
          }}
        >
          <p className="text-sm font-medium text-ink">New password for {settingFor.email}</p>
          <TextField label="New password" type="text" autoComplete="off" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} hint="At least 8 characters. Share it with them yourself." required />
          <div className="flex gap-3">
            <Button type="submit" variant="primary" busy={setPass.busy}>
              Save password
            </Button>
            <Button variant="ghost" onClick={() => setSettingFor(null)}>
              Cancel
            </Button>
          </div>
          {setPass.error && <Message kind="error">{setPass.error}</Message>}
        </form>
      )}

      <div className="border-t border-line px-4 py-5 sm:px-5 mt-4">
        <h3 className="text-sm font-semibold text-ink">Give someone access</h3>
        {!team.can_invite ? (
          <p className="mt-1 text-sm text-ink-2">Your plan doesn&apos;t include team members. Contact support to upgrade.</p>
        ) : (
          <form
            className="mt-3 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              setCreated(null);
              void invite.run();
            }}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              <TextField label="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
              <TextField
                label="Password for them (optional)"
                type="text"
                autoComplete="off"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                hint="At least 8 characters. Leave empty to give them a one-time link to choose their own."
              />
              <SelectField label="Role" value={role} onChange={(e) => setRole(e.target.value as "owner" | "viewer")}>
                <option value="viewer">Viewer (can look only)</option>
                <option value="owner">Owner (can change everything)</option>
              </SelectField>
            </div>
            <Button type="submit" variant="primary" busy={invite.busy}>
              Add person
            </Button>
          </form>
        )}
        {invite.error && (
          <div className="mt-3">
            <Message kind="error">{invite.error}</Message>
          </div>
        )}
        {created && (
          <div className="mt-3 space-y-2">
            <Message kind="success">{created.email} now has access.</Message>
            {created.passwordSet ? (
              <div className="rounded-lg border border-line bg-page p-3 text-sm">
                <p className="text-ink-2">The login is ready. Give them these details yourself (we don&apos;t email them):</p>
                <p className="mt-2 font-mono text-xs text-ink">
                  Email: {created.email}
                  <br />
                  Password: {created.password}
                </p>
                <div className="mt-2">
                  <CopyButton text={`Email: ${created.email}\nPassword: ${created.password}`} label="Copy login" />
                </div>
              </div>
            ) : created.link ? (
              <div className="rounded-lg border border-line bg-page p-3 text-sm">
                <p className="text-ink-2">
                  We emailed them a link to choose a password. If the email doesn&apos;t arrive, you can send them this link yourself (it works once):
                </p>
                <p className="mt-2 break-all font-mono text-xs text-ink">{created.link}</p>
                <div className="mt-2">
                  <CopyButton text={created.link} label="Copy link" />
                </div>
              </div>
            ) : (
              <p className="text-sm text-ink-2">They already have an account, so they log in with their own password (the one you typed was not used).</p>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
