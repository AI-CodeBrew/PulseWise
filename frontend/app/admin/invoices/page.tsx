"use client";

import Link from "next/link";
import { useState } from "react";

import { InvoiceActions } from "@/components/admin/InvoiceActions";
import { PayInvoicePanel } from "@/components/admin/PayInvoicePanel";
import { InvoiceStatus, adminInvoicePdfUrl } from "@/components/billing/parts";
import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { LoadMore, PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useCursorList } from "@/hooks/useCursorList";
import { formatDate, formatMoney } from "@/lib/format";
import type { InvoiceRow } from "@/lib/types";

const FILTERS = [
  { value: "all", label: "All" },
  { value: "open", label: "Unpaid" },
  { value: "overdue", label: "Overdue" },
  { value: "paid", label: "Paid" },
  { value: "void", label: "Cancelled" },
];

export default function InvoicesPage() {
  const [status, setStatus] = useState("all");
  const [paying, setPaying] = useState<InvoiceRow | null>(null);
  const list = useCursorList<InvoiceRow>("/api/admin/invoices", { status, limit: 30 });

  return (
    <>
      <PageHeader title="Invoices" description="Every bill you've issued. Invoices are created automatically on each client's billing day; add a one-off one on the client's page." />
      <div role="tablist" aria-label="Status" className="mb-4 flex flex-wrap gap-1">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            role="tab"
            aria-selected={status === f.value}
            onClick={() => setStatus(f.value)}
            className={`rounded-md px-3 py-1.5 text-sm ${status === f.value ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-surface-2"}`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {paying && (
        <div className="mb-4">
          <PayInvoicePanel
            invoice={paying}
            onCancel={() => setPaying(null)}
            onDone={() => {
              setPaying(null);
              list.reload();
            }}
          />
        </div>
      )}

      <Card className="pt-1">
        <Async query={list} skeleton={<div className="pt-4"><SkeletonRows rows={8} /></div>}>
          {() =>
            list.items.length === 0 ? (
              <EmptyState message={status === "all" ? "No invoices yet. They appear once a client is on a plan." : "No invoices match."} />
            ) : (
              <>
                <DataTable
                  rows={list.items}
                  rowKey={(i) => i.id}
                  columns={[
                    { header: "Invoice", cell: (i) => <span className="whitespace-nowrap font-medium">{i.number}</span> },
                    {
                      header: "Client",
                      cell: (i) =>
                        i.client_id ? (
                          <Link href={`/admin/clients/${i.client_id}`} className="hover:text-accent hover:underline">
                            {i.client_name}
                          </Link>
                        ) : (
                          i.client_name
                        ),
                    },
                    { header: "Due", className: "hidden sm:table-cell", cell: (i) => <span className="whitespace-nowrap">{formatDate(i.due_date)}</span> },
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
                            href={adminInvoicePdfUrl(i.id)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="whitespace-nowrap rounded-md border border-line px-2.5 py-1 text-xs font-medium text-accent hover:bg-surface-2"
                          >
                            PDF ↓
                          </a>
                          <InvoiceActions invoice={i} onPay={setPaying} onChanged={list.reload} />
                        </div>
                      ),
                    },
                  ]}
                />
                <LoadMore hasMore={list.hasMore} loading={list.loadingMore} error={list.moreError} onClick={list.loadMore} />
              </>
            )
          }
        </Async>
      </Card>
    </>
  );
}
