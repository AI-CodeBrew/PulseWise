"use client";

import { useState, type FormEvent } from "react";

import { Card, CardHeader } from "@/components/ui/Card";
import { Badge, Button, Message, TextArea, TextField, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useDebounced } from "@/hooks/useDebounced";
import { apiDelete, apiPatch, apiPost } from "@/lib/api";
import { FEATURE_LABELS } from "@/lib/features";
import { formatMoney, formatNumber, formatUsd } from "@/lib/format";
import type { FeatureName, ListResponse, Plan, PlanQuote } from "@/lib/types";

const FEATURE_KEYS = Object.keys(FEATURE_LABELS) as FeatureName[];

/** The list of plans, plus what PostHog gives away free each month (a good starting point for a plan's limits). */
type PlansResponse = ListResponse<Plan> & { free_allowance: { events: number; recordings: number } };

export default function PlansPage() {
  const plans = useApi<PlansResponse>("/api/admin/plans");
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
                free={p.free_allowance}
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
                  free={p.free_allowance}
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
  const quote = plan.quote;
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
          {(plan.intro_price_pkr !== null || plan.intro_price_usd !== null) && (
            <p className="mt-0.5 text-sm text-ink-2" data-intro-price>
              {plan.intro_months === 1 ? "First month" : `First ${plan.intro_months} months`}:{" "}
              {[plan.intro_price_pkr !== null && formatMoney(plan.intro_price_pkr, "PKR"), plan.intro_price_usd !== null && formatMoney(plan.intro_price_usd, "USD")]
                .filter(Boolean)
                .join(" or ")}
            </p>
          )}
          {plan.description && <p className="mt-1 text-sm text-ink-2">{plan.description}</p>}
        </div>
        <Button variant="secondary" onClick={onEdit}>
          Edit
        </Button>
      </div>
      <dl className="mt-4 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <Limit label="Events per month" value={plan.monthly_event_limit} />
        <Limit label="Recordings (videos) per month" value={plan.monthly_recording_limit} />
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
      {quote && (
        <p className="mt-3 text-xs text-muted" data-price-guide>
          Price guide: <strong className="text-ink">{formatUsd(quote.suggested_usd)}</strong> or {formatMoney(quote.suggested_pkr, "PKR")} a month. PostHog would charge you{" "}
          {formatUsd(quote.provider_usd)} for these amounts; your {quote.commission_percent}% commission adds {formatUsd(quote.commission_usd)}.
          {plan.price_usd < quote.suggested_usd && <span className="text-ink"> ▲ The USD price is below the guide.</span>}
        </p>
      )}
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

function PlanForm({ plan, free, onSaved, onCancel }: { plan?: Plan; free: { events: number; recordings: number }; onSaved: () => void; onCancel: () => void }) {
  const [name, setName] = useState(plan?.name ?? "");
  const [description, setDescription] = useState(plan?.description ?? "");
  const [pkr, setPkr] = useState(String(plan?.price_pkr ?? ""));
  const [usd, setUsd] = useState(String(plan?.price_usd ?? ""));
  const [introPkr, setIntroPkr] = useState(plan?.intro_price_pkr?.toString() ?? "");
  const [introUsd, setIntroUsd] = useState(plan?.intro_price_usd?.toString() ?? "");
  const [introMonths, setIntroMonths] = useState(String(plan?.intro_months ?? 1));
  const [events, setEvents] = useState(plan?.monthly_event_limit?.toString() ?? "");
  const [recordings, setRecordings] = useState(plan?.monthly_recording_limit?.toString() ?? "");
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
      intro_price_pkr: orNull(introPkr),
      intro_price_usd: orNull(introUsd),
      intro_months: Number(introMonths || 1),
      monthly_event_limit: orNull(events),
      monthly_recording_limit: orNull(recordings),
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

  // The price guide: asks the backend what these amounts should cost (PostHog's price + your commission), once typing has paused.
  const ready = events.trim() !== "" && recordings.trim() !== "" && Number(events) >= 1 && Number(recordings) >= 1;
  const typed = ready ? `${Math.round(Number(events))}|${Math.round(Number(recordings))}` : "";
  const asked = useDebounced(typed, 400);
  const [askedEvents, askedRecordings] = asked.split("|");
  const guide = useApi<PlanQuote>(asked ? "/api/admin/pricing/quote" : null, asked ? { events: askedEvents, recordings: askedRecordings } : undefined);
  // (only an answer to what is typed right now is shown, never one for older numbers)
  const quote = asked === typed && guide.data && String(guide.data.events) === askedEvents && String(guide.data.recordings) === askedRecordings ? guide.data : null;

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
        <TextField label="First month price (PKR)" type="number" min="0" step="0.01" value={introPkr} onChange={(e) => setIntroPkr(e.target.value)} hint="Optional. Empty = the normal price from the start." />
        <TextField label="First month price (USD)" type="number" min="0" step="0.01" value={introUsd} onChange={(e) => setIntroUsd(e.target.value)} hint="For example 20 when the normal price is 30." />
        <TextField label="First month price lasts (months)" type="number" min="1" max="12" value={introMonths} onChange={(e) => setIntroMonths(e.target.value)} hint="Usually 1." />
        <div className="sm:col-span-3">
          <TextArea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <TextField label="Events per month" type="number" min="1" value={events} onChange={(e) => setEvents(e.target.value)} hint="Leave empty for unlimited. Soft limit: you get an alert, nothing is switched off." />
        <TextField label="Recordings (videos) per month" type="number" min="1" value={recordings} onChange={(e) => setRecordings(e.target.value)} hint="Each recorded visit is one video. Empty = unlimited. Needs “Recordings” ticked below." />
        <div className="flex items-end">
          <Button
            variant="secondary"
            onClick={() => {
              setEvents(String(free.events));
              setRecordings(String(free.recordings));
            }}
          >
            Use PostHog&apos;s free amounts
          </Button>
        </div>

        <div className="rounded-lg border border-line p-4 text-sm sm:col-span-3" data-price-guide aria-live="polite">
          <h3 className="font-semibold text-ink">Price guide</h3>
          {quote ? (
            <div className="mt-1 space-y-1 text-ink-2">
              <p>
                PostHog gives {formatNumber(free.events)} events and {formatNumber(free.recordings)} recordings free every month. For {formatNumber(quote.events)} events and{" "}
                {formatNumber(quote.recordings)} recordings it would charge you <strong className="text-ink">{formatUsd(quote.provider_usd)}</strong> (events {formatUsd(quote.provider_events_usd)}, recordings{" "}
                {formatUsd(quote.provider_recordings_usd)}).
              </p>
              <p>
                Base price {formatUsd(quote.base_usd)} + that {formatUsd(quote.provider_usd)} + your {quote.commission_percent}% commission ({formatUsd(quote.commission_usd)}) = suggested{" "}
                <strong className="text-ink">{formatUsd(quote.suggested_usd)}</strong> or <strong className="text-ink">{formatMoney(quote.suggested_pkr, "PKR")}</strong> a month.
              </p>
              {usd.trim() !== "" && (
                <p>
                  At {formatUsd(Number(usd))} you keep <strong className="text-ink">{formatUsd(Number(usd) - quote.provider_usd)}</strong> a month after PostHog&apos;s price, if this plan were your only customer.
                </p>
              )}
              <div className="pt-1">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setUsd(String(quote.suggested_usd));
                    setPkr(String(quote.suggested_pkr));
                  }}
                >
                  Use this price
                </Button>
              </div>
            </div>
          ) : (
            <p className="mt-1 text-ink-2">
              {guide.error && ready ? guide.error.message : ready ? "Working it out…" : "Fill in both the events and the recordings to see what this plan should cost (PostHog\u2019s price + your commission). An unlimited plan can\u2019t be priced."}
            </p>
          )}
          <p className="mt-2 text-xs text-muted">The commission and the base price are set in Settings → Billing. Clients never see them.</p>
        </div>

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
