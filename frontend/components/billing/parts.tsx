"use client";

// Small pieces shared by the client Billing page, the "account paused" page and the admin billing screens.

import type { ReactNode } from "react";

import { Badge, Message, useAction } from "@/components/ui/Form";
import { DataTable } from "@/components/ui/DataTable";
import { API_URL, apiPost } from "@/lib/api";
import { formatDate, formatMoney, formatNumber } from "@/lib/format";
import type { InvoiceRow, SupportInfo } from "@/lib/types";

export function invoicePdfUrl(clientId: string, invoiceId: string): string {
  return `${API_URL}/api/clients/${clientId}/invoices/${invoiceId}/pdf`;
}

/** "Pay online": asks the backend to start a payment with the chosen gateway, then sends the client to the gateway's page. */
export function PayOnlineButton({ clientId, invoiceId }: { clientId: string; invoiceId: string }) {
  const pay = useAction(async () => {
    const { url } = await apiPost<{ url: string }>(`/api/clients/${clientId}/invoices/${invoiceId}/checkout`);
    window.location.assign(url);
  });
  return (
    <>
      <button
        type="button"
        onClick={() => pay.run()}
        disabled={pay.busy}
        className="whitespace-nowrap rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-white hover:opacity-90 disabled:opacity-60"
      >
        {pay.busy ? "Please wait…" : "Pay online"}
      </button>
      {pay.error && <Message kind="error">{pay.error}</Message>}
    </>
  );
}

export function adminInvoicePdfUrl(invoiceId: string): string {
  return `${API_URL}/api/admin/invoices/${invoiceId}/pdf`;
}

/** "Paid" / "Open" / "Overdue" / "Cancelled" with a symbol, so it never depends on colour alone. */
export function InvoiceStatus({ invoice }: { invoice: Pick<InvoiceRow, "status" | "overdue"> }) {
  if (invoice.status === "paid") return <Badge tone="green">Paid</Badge>;
  if (invoice.status === "void") return <Badge tone="gray">Cancelled</Badge>;
  return invoice.overdue ? <Badge tone="red">Overdue</Badge> : <Badge tone="amber">Open</Badge>;
}

/** A labelled progress bar, e.g. "Events this month: 250 of 1,000 (25%)". The wording carries the state, not just the colour. */
export function UsageMeter({ label, used, limit }: { label: string; used: number; limit: number | null }) {
  const percent = limit ? (used / limit) * 100 : 0;
  const state = !limit ? null : percent >= 100 ? "over" : percent >= 80 ? "close" : "ok";
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="text-ink-2">{label}</span>
        <span className="font-medium tabular-nums text-ink">
          {formatNumber(used)}
          {limit ? ` of ${formatNumber(limit)}` : " (no limit)"}
        </span>
      </div>
      {limit ? (
        <>
          <div
            className="mt-1.5 h-2 overflow-hidden rounded-full bg-surface-2"
            role="progressbar"
            aria-label={label}
            aria-valuemin={0}
            aria-valuemax={limit}
            aria-valuenow={Math.min(used, limit)}
          >
            <div className={`h-full rounded-full ${state === "over" ? "bg-bad" : "bg-accent"}`} style={{ width: `${Math.min(percent, 100)}%` }} />
          </div>
          <p className={`mt-1 text-xs ${state === "ok" ? "text-muted" : "text-ink"}`}>
            {state === "over" ? "✕ Over the limit: " : state === "close" ? "▲ Close to the limit: " : ""}
            {percent.toFixed(percent < 10 ? 1 : 0)}% used
          </p>
        </>
      ) : null}
    </div>
  );
}

/**
 * Events or recordings against the plan, as three plain numbers (Total / Used / Left) and a bar.
 * With no limit there is no "left": it says "No limit" instead. The words carry the state, not just the colour.
 */
export function QuotaMeter({
  label,
  hint,
  used,
  limit,
  remaining,
  over,
}: {
  label: string;
  hint?: string;
  used: number;
  limit: number | null;
  remaining: number | null;
  over: number;
}) {
  const percent = limit ? (used / limit) * 100 : 0;
  const state = !limit ? null : over > 0 ? "over" : percent >= 80 ? "close" : "ok";
  const stats = [
    { name: "Total", value: limit ? formatNumber(limit) : "No limit" },
    { name: "Used", value: formatNumber(used) },
    { name: over > 0 ? "Over by" : "Left", value: !limit ? "—" : formatNumber(over > 0 ? over : (remaining ?? 0)), tone: state },
  ];
  return (
    <div role="group" aria-label={label} data-quota={label}>
      <h3 className="text-sm font-medium text-ink">{label}</h3>
      {hint && <p className="text-xs text-muted">{hint}</p>}
      <dl className="mt-2 grid grid-cols-3 gap-3">
        {stats.map((stat) => (
          <div key={stat.name} className="min-w-0">
            <dt className="text-xs text-muted">{stat.name}</dt>
            <dd className={`break-words text-lg font-semibold tabular-nums ${stat.tone === "over" ? "text-bad" : "text-ink"}`}>{stat.value}</dd>
          </div>
        ))}
      </dl>
      {limit ? (
        <>
          <div
            className="mt-2 h-2 overflow-hidden rounded-full bg-surface-2"
            role="progressbar"
            aria-label={`${label} used`}
            aria-valuemin={0}
            aria-valuemax={limit}
            aria-valuenow={Math.min(used, limit)}
          >
            <div className={`h-full rounded-full ${state === "over" ? "bg-bad" : "bg-accent"}`} style={{ width: `${Math.min(percent, 100)}%` }} />
          </div>
          <p className={`mt-1 text-xs ${state === "ok" ? "text-muted" : "text-ink"}`}>
            {state === "over" ? "✕ Over the limit: " : state === "close" ? "▲ Close to the limit: " : ""}
            {percent.toFixed(percent < 10 ? 1 : 0)}% used
          </p>
        </>
      ) : null}
    </div>
  );
}

export function InvoiceTable({
  invoices,
  clientId,
  actions,
  adminLinks = false,
  payOnline = false,
}: {
  invoices: InvoiceRow[];
  clientId: string;
  /** Extra buttons per row (the admin's "Mark as paid"...). */
  actions?: (invoice: InvoiceRow) => ReactNode;
  adminLinks?: boolean;
  /** Show "Pay online" on open invoices (only when a payment gateway is switched on). */
  payOnline?: boolean;
}) {
  return (
    <DataTable
      rows={invoices}
      rowKey={(i) => i.id}
      columns={[
        { header: "Invoice", cell: (i) => <span className="whitespace-nowrap font-medium">{i.number}</span> },
        { header: "Issued", className: "hidden sm:table-cell", cell: (i) => formatDate(i.issue_date) },
        { header: "Due", cell: (i) => <span className="whitespace-nowrap">{formatDate(i.due_date)}</span> },
        {
          header: "Amount",
          align: "right",
          cell: (i) => (
            <span className="whitespace-nowrap">
              {formatMoney(i.amount, i.currency)}
              {i.status === "open" && i.paid_amount > 0 && <span className="block text-xs text-muted">{formatMoney(i.balance, i.currency)} left</span>}
            </span>
          ),
        },
        { header: "Status", cell: (i) => <InvoiceStatus invoice={i} /> },
        {
          header: "",
          align: "right",
          cell: (i) => (
            <div className="flex flex-wrap justify-end gap-2">
              <a
                href={adminLinks ? adminInvoicePdfUrl(i.id) : invoicePdfUrl(clientId, i.id)}
                target="_blank"
                rel="noopener noreferrer"
                className="whitespace-nowrap rounded-md border border-line px-2.5 py-1 text-xs font-medium text-accent hover:bg-surface-2"
              >
                PDF ↓
              </a>
              {payOnline && i.status === "open" && <PayOnlineButton clientId={clientId} invoiceId={i.id} />}
              {actions?.(i)}
            </div>
          ),
        },
      ]}
    />
  );
}

/** "Contact us" buttons built from the support number / email an admin saved in Settings. */
export function SupportLinks({ support, className = "" }: { support: SupportInfo | undefined; className?: string }) {
  if (!support || (!support.whatsapp && !support.email)) return null;
  const digits = support.whatsapp.replace(/\D/g, "");
  return (
    <div className={`flex flex-wrap gap-2 ${className}`}>
      {digits && (
        <a href={`https://wa.me/${digits}`} target="_blank" rel="noopener noreferrer" className="rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white hover:opacity-90">
          Chat on WhatsApp
        </a>
      )}
      {support.email && (
        <a href={`mailto:${support.email}`} className="rounded-lg border border-line px-3.5 py-2 text-sm font-medium text-ink hover:bg-surface-2">
          Email {support.email}
        </a>
      )}
    </div>
  );
}
