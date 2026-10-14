"use client";

import { useState, type FormEvent } from "react";

import { Card, CardHeader } from "@/components/ui/Card";
import { Badge, Button, Message, TextArea, TextField, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiDelete, apiPatch, apiPost } from "@/lib/api";
import { FEATURE_LABELS } from "@/lib/features";
import { formatMoney, formatNumber } from "@/lib/format";
import type { FeatureName, ListResponse, Plan } from "@/lib/types";

const FEATURE_KEYS = Object.keys(FEATURE_LABELS) as FeatureName[];

export default function PlansPage() {
  const plans = useApi<ListResponse<Plan>>("/api/admin/plans");
  const [editing, setEditing] = useState<string | "new" | null>(null);

  return (
    <>
      <PageHeader
        title="Plans"
        description="What you sell. A client on no plan is unrestricted and isn't invoiced (use that for your own site). New prices apply to future invoices only."
        action={
          editing !== "new" && (
            <Button variant="primary" onClick={() => setEditing("new")}>
              + New plan
            </Button>
          )
        }
      />
      <Async query={plans} skeleton={<Card className="pt-4"><SkeletonRows rows={4} /></Card>}>
        {(p) => (
          <div className="space-y-4">
            {editing === "new" && (
              <PlanForm
                onCancel={() => setEditing(null)}
                onSaved={() => {
                  setEditing(null);
                  plans.reload();
                }}
              />
            )}
            {p.results.map((plan) =>
              editing === plan.id ? (
                <PlanForm
                  key={plan.id}
                  plan={plan}
                  onCancel={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    plans.reload();
                  }}
                />
              ) : (
                <PlanCard key={plan.id} plan={plan} onEdit={() => setEditing(plan.id)} />
              ),
            )}
          </div>
        )}
      </Async>
    </>
  );
}

function PlanCard({ plan, onEdit }: { plan: Plan; onEdit: () => void }) {
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-ink">{plan.name}</h2>
            {!plan.is_active && <Badge tone="gray">Not for sale</Badge>}
            <span className="text-xs text-muted">
              {plan.clients ?? 0} client{plan.clients === 1 ? "" : "s"}
            </span>
          </div>
          <p className="mt-1 text-sm text-ink">
            <strong>{formatMoney(plan.price_pkr, "PKR")}</strong> or <strong>{formatMoney(plan.price_usd, "USD")}</strong> per month
          </p>
          {plan.description && <p className="mt-1 text-sm text-ink-2">{plan.description}</p>}
        </div>
        <Button variant="secondary" onClick={onEdit}>
          Edit
        </Button>
      </div>
      <dl className="mt-4 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
        <Limit label="Events per month" value={plan.monthly_event_limit} />
        <Limit label="Websites" value={plan.max_websites} />
        <Limit label="People with access" value={plan.max_team_members} />
      </dl>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        {FEATURE_KEYS.map((f) => (
          <li key={f} className={plan.features[f] ? "text-ink" : "text-muted"}>
            <span aria-hidden="true">{plan.features[f] ? "✓" : "✕"}</span> {FEATURE_LABELS[f]}
            <span className="sr-only">{plan.features[f] ? " (included)" : " (not included)"}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Limit({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="flex justify-between gap-3 sm:block">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="font-medium text-ink">{value === null ? "Unlimited" : formatNumber(value)}</dd>
    </div>
  );
}

function PlanForm({ plan, onSaved, onCancel }: { plan?: Plan; onSaved: () => void; onCancel: () => void }) {
  const [name, setName] = useState(plan?.name ?? "");
  const [description, setDescription] = useState(plan?.description ?? "");
  const [pkr, setPkr] = useState(String(plan?.price_pkr ?? ""));
  const [usd, setUsd] = useState(String(plan?.price_usd ?? ""));
  const [events, setEvents] = useState(plan?.monthly_event_limit?.toString() ?? "");
  const [sites, setSites] = useState(plan?.max_websites?.toString() ?? "");
  const [members, setMembers] = useState(plan?.max_team_members?.toString() ?? "");
  const [active, setActive] = useState(plan?.is_active ?? true);
  const [features, setFeatures] = useState<Record<string, boolean>>(plan?.features ?? Object.fromEntries(FEATURE_KEYS.map((f) => [f, false])));

  const orNull = (value: string) => (value.trim() === "" ? null : Number(value));
  const save = useAction(async () => {
    const body = {
      name,
      description: description || null,
      price_pkr: Number(pkr || 0),
      price_usd: Number(usd || 0),
      monthly_event_limit: orNull(events),
      max_websites: orNull(sites),
      max_team_members: orNull(members),
      is_active: active,
      features,
    };
    if (plan) await apiPatch(`/api/admin/plans/${plan.id}`, body);
    else await apiPost("/api/admin/plans", body);
    onSaved();
  });
  const remove = useAction(async () => {
    if (!plan || !window.confirm(`Delete the plan "${plan.name}"?`)) return;
    await apiDelete(`/api/admin/plans/${plan.id}`);
    onSaved();
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    save.run();
  }

  return (
    <Card>
      <CardHeader title={plan ? `Edit ${plan.name}` : "New plan"} />
      <form onSubmit={onSubmit} className="grid gap-4 px-4 pb-5 sm:grid-cols-3 sm:px-5">
        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
        <TextField label="Price per month (PKR)" type="number" min="0" step="0.01" value={pkr} onChange={(e) => setPkr(e.target.value)} />
        <TextField label="Price per month (USD)" type="number" min="0" step="0.01" value={usd} onChange={(e) => setUsd(e.target.value)} />
        <div className="sm:col-span-3">
          <TextArea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <TextField label="Events per month" type="number" min="1" value={events} onChange={(e) => setEvents(e.target.value)} hint="Leave empty for unlimited. Soft limit: you get an alert, nothing is switched off." />
        <TextField label="Websites" type="number" min="1" value={sites} onChange={(e) => setSites(e.target.value)} hint="Empty = unlimited." />
        <TextField label="People with access" type="number" min="1" value={members} onChange={(e) => setMembers(e.target.value)} hint="Empty = unlimited." />
        <fieldset className="sm:col-span-3">
          <legend className="mb-2 text-sm font-medium text-ink">Included in this plan</legend>
          <div className="flex flex-wrap gap-x-6 gap-y-2">
            {FEATURE_KEYS.map((f) => (
              <label key={f} className="flex items-center gap-2 text-sm text-ink">
                <input type="checkbox" checked={Boolean(features[f])} onChange={(e) => setFeatures((s) => ({ ...s, [f]: e.target.checked }))} className="h-4 w-4 accent-[var(--accent)]" />
                {FEATURE_LABELS[f]}
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted">The basic dashboard (overview, pages, traffic sources, audience) is in every plan.</p>
        </fieldset>
        <label className="flex items-center gap-2 text-sm text-ink sm:col-span-3">
          <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} className="h-4 w-4 accent-[var(--accent)]" />
          This plan can be sold to new clients
        </label>
        <div className="flex flex-wrap items-center gap-3 sm:col-span-3">
          <Button type="submit" variant="primary" busy={save.busy}>
            {plan ? "Save plan" : "Create plan"}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
          {plan && (
            <Button variant="ghost" className="ml-auto !text-bad" busy={remove.busy} onClick={() => remove.run()}>
              Delete plan
            </Button>
          )}
        </div>
        {(save.error || remove.error) && (
          <div className="sm:col-span-3">
            <Message kind="error">{save.error ?? remove.error}</Message>
          </div>
        )}
      </form>
    </Card>
  );
}
