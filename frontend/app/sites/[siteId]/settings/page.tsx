"use client";

import { useRef, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { ClientLogo } from "@/components/layout/ClientLogo";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Button, CopyButton, Message, SelectField, TextField, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { bumpLogoVersion, useLogoVersion } from "@/hooks/useLogoVersion";
import { useCurrentSite } from "@/hooks/useSite";
import { apiDelete, apiPatch, apiPost, apiPut } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { REPORT_LANGUAGES, type ClientSettings, type ReportLanguage, type Team } from "@/lib/types";

const MAX_LOGO_BYTES = 300_000;

/** The client's own settings: business name, logo, time zone, report language, and who has access. Owners only. */
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
      <PageHeader title="Settings" description="Your business details, your logo, and who can see this dashboard." />
      <div className="space-y-6">
        <Async query={settings} skeleton={<Skeleton className="h-72 rounded-xl" />}>
          {(s) => (
            <>
              <BusinessCard clientId={clientId} settings={s} reload={settings.reload} />
              <LogoCard clientId={clientId} hasLogo={s.has_logo} reload={settings.reload} />
            </>
          )}
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
  const [timezone, setTimezone] = useState(settings.timezone);
  const [language, setLanguage] = useState<ReportLanguage>(settings.report_language);
  const [weekly, setWeekly] = useState(settings.weekly_report_enabled);
  const [whatsappNumber, setWhatsappNumber] = useState(settings.whatsapp_number ? `+${settings.whatsapp_number}` : "");
  const [whatsappOn, setWhatsappOn] = useState(settings.whatsapp_reports_enabled);
  const [saved, setSaved] = useState(false);

  const save = useAction(async () => {
    setSaved(false);
    await apiPatch(`/api/clients/${clientId}/settings`, {
      name,
      timezone,
      report_language: language,
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
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Business name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required />
          <SelectField label="Time zone" value={timezone} onChange={(e) => setTimezone(e.target.value)} hint="Your weekly report arrives Monday 8:00 in this time zone.">
            {settings.timezones.map((z) => (
              <option key={z} value={z}>
                {z.replace(/_/g, " ")}
              </option>
            ))}
          </SelectField>
          <SelectField label="Report language" value={language} onChange={(e) => setLanguage(e.target.value as ReportLanguage)} hint="The language of the written summary in your weekly report.">
            {REPORT_LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </SelectField>
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

// ------------------------------------------------------------------ logo

function LogoCard({ clientId, hasLogo, reload }: { clientId: string; hasLogo: boolean; reload: () => void }) {
  const { refresh } = useAuth();
  const version = useLogoVersion();
  const input = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);

  function done() {
    bumpLogoVersion();
    refresh();
    reload();
  }

  const upload = useAction(async (file: File) => {
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error("read"));
      reader.readAsDataURL(file);
    });
    await apiPut(`/api/clients/${clientId}/logo`, { data: dataUrl });
    done();
  });
  const remove = useAction(async () => {
    await apiDelete(`/api/clients/${clientId}/logo`);
    done();
  });

  function onPick(file: File | undefined) {
    setProblem(null);
    if (input.current) input.current.value = ""; // so choosing the same file again still fires
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) return setProblem("Please choose a PNG, JPEG or WebP picture.");
    if (file.size > MAX_LOGO_BYTES) return setProblem(`That picture is too big. Please use one under ${MAX_LOGO_BYTES / 1000} KB.`);
    void upload.run(file);
  }

  return (
    <Card>
      <CardHeader title="Your logo" subtitle="Shown at the top of your dashboard. PNG, JPEG or WebP, up to 300 KB." />
      <div className="flex flex-wrap items-center gap-4 px-4 pb-5 sm:px-5">
        {hasLogo ? (
          <ClientLogo clientId={clientId} version={version} className="h-16 w-16" />
        ) : (
          <div className="grid h-16 w-16 place-items-center rounded-md bg-surface-2 text-xs text-muted">No logo</div>
        )}
        <input
          ref={input}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          className="sr-only"
          aria-label="Choose a logo file"
          onChange={(e) => onPick(e.target.files?.[0])}
        />
        <Button busy={upload.busy} onClick={() => input.current?.click()}>
          {hasLogo ? "Replace logo" : "Upload logo"}
        </Button>
        {hasLogo && (
          <Button variant="ghost" busy={remove.busy} onClick={() => remove.run()}>
            Remove
          </Button>
        )}
      </div>
      {(problem || upload.error || remove.error) && (
        <div className="px-4 pb-5 sm:px-5">
          <Message kind="error">{problem || upload.error || remove.error}</Message>
        </div>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ team

function TeamCard({ clientId, team, reload }: { clientId: string; team: Team; reload: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"owner" | "viewer">("viewer");
  const [link, setLink] = useState<{ email: string; url: string | null } | null>(null);

  const invite = useAction(async () => {
    const result = await apiPost<{ email: string; invite_link: string | null }>(`/api/clients/${clientId}/team`, { email, name, role });
    setLink({ email: result.email, url: result.invite_link });
    setEmail("");
    setName("");
    reload();
  });
  const changeRole = useAction(async (userId: string, newRole: string) => {
    await apiPatch(`/api/clients/${clientId}/team/${userId}`, { role: newRole });
    reload();
  });
  const remove = useAction(async (userId: string) => {
    await apiDelete(`/api/clients/${clientId}/team/${userId}`);
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
                disabled={changeRole.busy}
                onChange={(e) => changeRole.run(m.user_id, e.target.value)}
                className="rounded-md border border-line bg-page px-2 py-1 text-sm text-ink"
              >
                <option value="owner">Owner</option>
                <option value="viewer">Viewer</option>
              </select>
            ),
          },
          {
            header: "Remove",
            align: "right",
            cell: (m) => (
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
            ),
          },
        ]}
      />
      {(changeRole.error || remove.error) && (
        <div className="px-4 pt-3 sm:px-5">
          <Message kind="error">{changeRole.error || remove.error}</Message>
        </div>
      )}

      <div className="border-t border-line px-4 py-5 sm:px-5">
        <h3 className="text-sm font-semibold text-ink">Give someone access</h3>
        {!team.can_invite ? (
          <p className="mt-1 text-sm text-ink-2">Your plan doesn&apos;t include team members. Contact support to upgrade.</p>
        ) : (
          <form
            className="mt-3 space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              setLink(null);
              void invite.run();
            }}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
              <TextField label="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
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
        {link && (
          <div className="mt-3 space-y-2">
            <Message kind="success">{link.email} now has access.</Message>
            {link.url ? (
              <div className="rounded-lg border border-line bg-page p-3 text-sm">
                <p className="text-ink-2">
                  We emailed them a link to choose a password. If the email doesn&apos;t arrive, you can send them this link yourself (it works once):
                </p>
                <p className="mt-2 break-all font-mono text-xs text-ink">{link.url}</p>
                <div className="mt-2">
                  <CopyButton text={link.url} label="Copy link" />
                </div>
              </div>
            ) : (
              <p className="text-sm text-ink-2">They already have an account, so they can log in as usual.</p>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
