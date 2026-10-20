"use client";

import { useState, type FormEvent } from "react";

import { InvoiceTable, QuotaMeter, UsageMeter } from "@/components/billing/parts";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button, Message, SelectField, TextField, useAction } from "@/components/ui/Form";
import { Async, EmptyState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiDelete, apiPatch, apiPost, apiPut } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import type { AdminClientDetail, BillingSummary, Currency, InvoiceRow, ListResponse, Plan } from "@/lib/types";
import { ExtraUsagePanel } from "./ExtraUsagePanel";
import { InvoiceActions } from "./InvoiceActions";
import { PayInvoicePanel } from "./PayInvoicePanel";

/** Everything about one client's money: plan, special price, usage, invoices, payments. */
export function PlanBillingCard({ client, reload }: { client: AdminClientDetail; reload: () => void }) {
  const billing = useApi<BillingSummary>(`/api/admin/clients/${client.id}/billing`);
  const plans = useApi<ListResponse<Plan>>("/api/admin/plans");
  const [paying, setPaying] = useState<InvoiceRow | null>(null);

  const refresh = () => {
    billing.reload();
    reload();
  };

  return (
    <Card>
      <CardHeader title="Plan & billing" subtitle="What they pay, and what they've used." />
      <Async query={billing} skeleton={<Skeleton className="mx-5 mb-5 h-40" />}>
        {(b) => (
          <div className="space-y-6 px-4 pb-5 sm:px-5">
            <div className="grid gap-6 lg:grid-cols-2">
              <PlanForm client={client} billing={b} plans={plans.data?.results ?? []} onChanged={refresh} />
              <div className="space-y-4">
                <QuotaMeter label="Events this month" used={b.usage.events} limit={b.usage.event_limit} remaining={b.usage.event_remaining} over={b.usage.event_over} />
                <QuotaMeter label="Recordings (videos) this month" used={b.usage.recordings} limit={b.usage.recording_limit} remaining={b.usage.recording_remaining} over={b.usage.recording_over} />
                <UsageMeter label="Websites" used={b.usage.websites} limit={b.usage.max_websites} />
                <UsageMeter label="People" used={b.usage.members} limit={b.usage.max_members} />
                {b.plan && <ExtraUsagePanel clientId={client.id} currency={b.client.currency} onChanged={refresh} />}
                {b.outstanding.count > 0 && (
                  <Message kind={b.outstanding.overdue_count > 0 ? "error" : "info"}>
                    {b.outstanding.count} unpaid invoice{b.outstanding.count > 1 ? "s" : ""}, {formatMoney(b.outstanding.amount, b.client.currency)} in total
                    {b.outstanding.overdue_count > 0 ? ` (${b.outstanding.overdue_count} overdue)` : ""}.
                  </Message>
                )}
              </div>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-ink">Invoices</h3>
              {paying && (
                <div className="mb-3">
                  <PayInvoicePanel
                    invoice={paying}
                    onCancel={() => setPaying(null)}
                    onDone={() => {
                      setPaying(null);
                      refresh();
                    }}
                  />
                </div>
              )}
              {b.invoices.length === 0 ? (
                <EmptyState message="No invoices yet." />
              ) : (
                <div className="-mx-4 sm:-mx-5">
                  <InvoiceTable invoices={b.invoices} clientId={client.id} adminLinks actions={(i) => <InvoiceActions invoice={i} onPay={setPaying} onChanged={refresh} />} />
                </div>
              )}
            </div>

            <OneOffInvoiceForm clientId={client.id} currency={b.client.currency} onCreated={refresh} />
          </div>
        )}
      </Async>
    </Card>
  );
}

function PlanForm({ client, billing, plans, onChanged }: { client: AdminClientDetail; billing: BillingSummary; plans: Plan[]; onChanged: () => void }) {
  const sub = billing.subscription;
  const [planId, setPlanId] = useState(sub?.plan_id ?? "");
  const [billingDay, setBillingDay] = useState(String(sub?.billing_day ?? ""));
  const [override, setOverride] = useState(sub?.price_override?.toString() ?? "");
  const [startedAt, setStartedAt] = useState(new Date().toISOString().slice(0, 10));
  const [currency, setCurrency] = useState<Currency>(billing.client.currency);

  const apply = useAction(async () => {
    if (currency !== billing.client.currency) await apiPatch(`/api/admin/clients/${client.id}`, { currency });
    const body: Record<string, unknown> = { plan_id: planId, price_override: override === "" ? null : Number(override) };
    if (billingDay) body.billing_day = Number(billingDay);
    if (!sub) body.started_at = startedAt;
    await apiPut(`/api/admin/clients/${client.id}/subscription`, body);
    onChanged();
  });
  const cancel = useAction(async () => {
    if (!window.confirm("Cancel this client's plan? No more invoices will be issued. Unpaid invoices stay.")) return;
    await apiDelete(`/api/admin/clients/${client.id}/subscription`);
    onChanged();
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    apply.run();
  }

  const hasInvoices = billing.invoices.length > 0;
  return (
    <form onSubmit={onSubmit} className="space-y-4">
      {sub && billing.plan ? (
        <p className="text-sm text-ink-2">
          On <strong className="text-ink">{billing.plan.name}</strong> at <strong className="text-ink">{formatMoney(billing.plan.price, billing.client.currency)}</strong> per month
          {sub.price_override !== null ? " (special price)" : ""}. Next invoice: {formatMoney(sub.next_invoice_amount, billing.client.currency)} on {formatDate(sub.next_invoice_date)}
          {sub.next_invoice_is_intro ? " (first month price)" : ""}.
        </p>
      ) : (
        <p className="text-sm text-ink-2">No plan: this client is unrestricted and isn&apos;t invoiced.</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField label={sub ? "Change plan" : "Put on plan"} value={planId} onChange={(e) => setPlanId(e.target.value)} required>
          <option value="">Choose a plan…</option>
          {plans
            .filter((p) => p.is_active || p.id === sub?.plan_id)
            .map((p) => (
              <option key={p.id} value={p.id}>
                {p.name} ({formatMoney(currency === "USD" ? p.price_usd : p.price_pkr, currency)}
                {(currency === "USD" ? p.intro_price_usd : p.intro_price_pkr) !== null ? `, first month ${formatMoney((currency === "USD" ? p.intro_price_usd : p.intro_price_pkr) ?? 0, currency)}` : ""})
              </option>
            ))}
        </SelectField>
        <SelectField
          label="Billed in"
          value={currency}
          onChange={(e) => setCurrency(e.target.value as Currency)}
          disabled={hasInvoices}
          hint={hasInvoices ? "Locked: there are invoices already." : undefined}
        >
          <option value="PKR">PKR (Rs)</option>
          <option value="USD">USD ($)</option>
        </SelectField>
        <TextField label="Invoice on day of month" type="number" min="1" max="28" value={billingDay} onChange={(e) => setBillingDay(e.target.value)} placeholder="1-28" hint="Empty = the start day." />
        <TextField label={`Special price (${currency})`} type="number" min="0" step="0.01" value={override} onChange={(e) => setOverride(e.target.value)} hint="Empty = the plan's price." />
        {!sub && <TextField label="Starts on" type="date" value={startedAt} onChange={(e) => setStartedAt(e.target.value)} hint="The first invoice is issued on the first billing day on or after this date." />}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" busy={apply.busy} disabled={!planId}>
          {sub ? "Save plan" : "Start plan"}
        </Button>
        {sub && (
          <Button variant="ghost" className="!text-bad" busy={cancel.busy} onClick={() => cancel.run()}>
            Cancel plan
          </Button>
        )}
      </div>
      {(apply.error || cancel.error) && <Message kind="error">{apply.error ?? cancel.error}</Message>}
    </form>
  );
}

function OneOffInvoiceForm({ clientId, currency, onCreated }: { clientId: string; currency: Currency; onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const create = useAction(async () => {
    await apiPost(`/api/admin/clients/${clientId}/invoices`, { description, amount: Number(amount) });
    setDescription("");
    setAmount("");
    setOpen(false);
    onCreated();
  });

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        + One-off invoice
      </Button>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        create.run();
      }}
      className="grid gap-4 rounded-lg border border-line p-4 sm:grid-cols-3"
    >
      <div className="sm:col-span-2">
        <TextField label="What is it for?" required value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Set-up fee, extra report, ..." maxLength={300} />
      </div>
      <TextField label={`Amount (${currency})`} required type="number" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
      <div className="flex gap-3 sm:col-span-3">
        <Button type="submit" variant="primary" busy={create.busy}>
          Create invoice
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {create.error && (
        <div className="sm:col-span-3">
          <Message kind="error">{create.error}</Message>
        </div>
      )}
    </form>
  );
}
