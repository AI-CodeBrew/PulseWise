"use client";

import { PlanChoices } from "@/components/billing/PlanChoices";
import { InvoiceTable, QuotaMeter, SupportLinks, UsageMeter } from "@/components/billing/parts";
import { Card, CardHeader } from "@/components/ui/Card";
import { Message } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useCurrentSite } from "@/hooks/useSite";
import { FEATURE_LABELS } from "@/lib/features";
import { formatDate, formatMoney, timeAgo } from "@/lib/format";
import type { BillingSummary, FeatureName } from "@/lib/types";

/** The client's own plan, usage and invoices. Only account owners (and admins) can open it. */
export default function BillingPage() {
  const site = useCurrentSite();
  const canSee = site?.role === "owner" || site?.role === "admin";
  const billing = useApi<BillingSummary>(canSee && site ? `/api/clients/${site.client_id}/billing` : null);

  if (!site) return null;
  if (!canSee) {
    return (
      <>
        <PageHeader title="Billing" />
        <Card>
          <EmptyState message="Only the account owner can see billing. Ask them if you need an invoice." />
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader title="Billing" description="Your plan, how much of it you've used, and your invoices." />
      <Async query={billing} skeleton={<Skeleton className="h-64 rounded-xl" />}>
        {(b) => {
          const money = (n: number) => formatMoney(n, b.client.currency);
          return (
            <div className="space-y-6">
              {b.outstanding.count > 0 && (
                <Message kind={b.outstanding.overdue_count > 0 ? "error" : "info"}>
                  {b.outstanding.overdue_count > 0
                    ? `You have ${b.outstanding.overdue_count} overdue invoice${b.outstanding.overdue_count > 1 ? "s" : ""}. `
                    : `You have ${b.outstanding.count} unpaid invoice${b.outstanding.count > 1 ? "s" : ""}. `}
                  Total to pay: <strong>{money(b.outstanding.amount)}</strong>. See how to pay below.
                </Message>
              )}

              <div className="grid gap-6 lg:grid-cols-2">
                <Card>
                  <CardHeader title="Your plan" />
                  <div className="px-4 pb-5 sm:px-5">
                    {b.plan && b.subscription ? (
                      <>
                        <p className="text-xl font-semibold text-ink">{b.plan.name}</p>
                        <p className="mt-0.5 text-sm text-ink-2">{money(b.plan.price)} per month</p>
                        <p className="mt-0.5 text-sm text-ink-2" data-next-invoice>
                          {b.subscription.next_invoice_amount > 0 ? (
                            <>
                              Next invoice: <strong className="text-ink">{money(b.subscription.next_invoice_amount)}</strong> on {formatDate(b.subscription.next_invoice_date)}
                              {b.subscription.next_invoice_is_intro && ` (first month price, then ${money(b.plan.price)} a month)`}
                            </>
                          ) : (
                            "Nothing to pay for now."
                          )}
                        </p>
                        <ul className="mt-4 grid grid-cols-1 gap-1.5 text-sm sm:grid-cols-2">
                          {(Object.keys(FEATURE_LABELS) as FeatureName[]).map((f) => (
                            <li key={f} className={b.plan?.features[f] ? "text-ink" : "text-muted"}>
                              <span aria-hidden="true">{b.plan?.features[f] ? "✓" : "✕"}</span> {FEATURE_LABELS[f]}
                              <span className="sr-only">{b.plan?.features[f] ? " (included)" : " (not included)"}</span>
                            </li>
                          ))}
                        </ul>
                        <p className="mt-4 text-xs text-muted">Want more? Ask us to move you to a bigger plan.</p>
                        <SupportLinks support={b.support} className="mt-3" />
                      </>
                    ) : (
                      <p className="text-sm text-ink-2">Your account has no paid plan. Everything is included and nothing is billed.</p>
                    )}
                  </div>
                </Card>

                <Card>
                  <CardHeader
                    title="This month's usage"
                    subtitle={`Resets on the 1st${b.usage.updated_at ? ` · counted ${timeAgo(b.usage.updated_at)}` : ""}`}
                  />
                  <div className="space-y-6 px-4 pb-5 sm:px-5">
                    <QuotaMeter
                      label="Visitor events"
                      hint="Page views, clicks and the other things your visitors do"
                      used={b.usage.events}
                      limit={b.usage.event_limit}
                      remaining={b.usage.event_remaining}
                      over={b.usage.event_over}
                    />
                    {b.features.recordings ? (
                      <QuotaMeter
                        label="Recordings (videos)"
                        hint="Each recorded visit counts as one video"
                        used={b.usage.recordings}
                        limit={b.usage.recording_limit}
                        remaining={b.usage.recording_remaining}
                        over={b.usage.recording_over}
                      />
                    ) : (
                      <p className="text-sm text-muted">Recordings (videos of visits) are not part of your plan.</p>
                    )}
                    <UsageMeter label="Websites" used={b.usage.websites} limit={b.usage.max_websites} />
                    <UsageMeter label="People with access" used={b.usage.members} limit={b.usage.max_members} />
                    <p className="text-xs text-muted">Going over a limit doesn&apos;t switch anything off. We&apos;ll just get in touch about a better-fitting plan.</p>
                  </div>
                </Card>
              </div>

              {b.available_plans && (
                <PlanChoices plans={b.available_plans} currentPlanId={b.plan?.id ?? null} currency={b.client.currency} businessName={b.client.name} support={b.support} />
              )}

              <Card>
                <CardHeader title="Invoices" />
                {b.invoices.length === 0 ? (
                  <EmptyState message="No invoices yet." />
                ) : (
                  <InvoiceTable invoices={b.invoices} clientId={b.client.id} payOnline={b.online_payments} />
                )}
              </Card>

              {b.payment_instructions && (
                <Card>
                  <CardHeader title="How to pay" />
                  <p className="whitespace-pre-line px-4 pb-5 text-sm text-ink sm:px-5">{b.payment_instructions}</p>
                  <p className="px-4 pb-5 text-xs text-muted sm:px-5">After paying, send us the payment reference so we can mark the invoice as paid.</p>
                </Card>
              )}
            </div>
          );
        }}
      </Async>
    </>
  );
}
