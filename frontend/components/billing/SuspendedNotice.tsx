"use client";

import { useAuth } from "@/components/auth/AuthProvider";
import { Card } from "@/components/ui/Card";
import { useApi } from "@/hooks/useApi";
import { formatDate, formatMoney } from "@/lib/format";
import type { BillingSummary, WebsiteSummary } from "@/lib/types";
import { InvoiceStatus, PayOnlineButton, SupportLinks, invoicePdfUrl } from "./parts";

/**
 * What a client sees instead of the dashboard while their account is suspended (usually: an unpaid invoice).
 * Account owners also see which invoices are open and how to pay. Admins never see this page.
 */
export function SuspendedNotice({ site }: { site: WebsiteSummary }) {
  const { me, logout } = useAuth();
  const isOwner = site.role === "owner";
  const billing = useApi<BillingSummary>(isOwner ? `/api/clients/${site.client_id}/billing` : null);
  const b = billing.data;
  const overdue = b?.invoices.filter((i) => i.status === "open") ?? [];

  return (
    <main className="mx-auto grid min-h-screen max-w-xl place-items-center px-4 py-10">
      <Card className="w-full p-6">
        <h1 className="text-lg font-semibold text-ink">Your dashboard is paused</h1>
        <p className="mt-2 text-sm text-ink-2">
          {b?.client.suspended_reason === "overdue" || overdue.length > 0
            ? "An invoice is overdue, so access to the dashboard is paused. As soon as it's paid, everything comes back automatically."
            : "Access to this dashboard has been paused. Please contact us and we'll sort it out."}
        </p>

        {isOwner && overdue.length > 0 && b && (
          <div className="mt-5">
            <h2 className="mb-2 text-sm font-semibold text-ink">Unpaid invoices</h2>
            <ul className="divide-y divide-line rounded-lg border border-line">
              {overdue.map((i) => (
                <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                  <span>
                    <span className="font-medium">{i.number}</span> <span className="text-muted">· due {formatDate(i.due_date)}</span>
                  </span>
                  <span className="flex items-center gap-3">
                    <InvoiceStatus invoice={i} />
                    {b.online_payments && <PayOnlineButton clientId={b.client.id} invoiceId={i.id} />}
                    <span className="font-medium tabular-nums">{formatMoney(i.balance, i.currency)}</span>
                    <a href={invoicePdfUrl(b.client.id, i.id)} target="_blank" rel="noopener noreferrer" className="text-xs font-medium text-accent hover:underline">
                      PDF
                    </a>
                  </span>
                </li>
              ))}
            </ul>
            {b.payment_instructions && (
              <>
                <h2 className="mb-1 mt-5 text-sm font-semibold text-ink">How to pay</h2>
                <p className="whitespace-pre-line text-sm text-ink-2">{b.payment_instructions}</p>
              </>
            )}
          </div>
        )}
        {!isOwner && <p className="mt-4 text-sm text-ink-2">Please ask the account owner to check the billing page.</p>}

        <SupportLinks support={b?.support ?? me?.support} className="mt-6" />
        <button type="button" onClick={logout} className="mt-5 text-sm text-ink-2 hover:text-ink hover:underline">
          Log out
        </button>
      </Card>
    </main>
  );
}
