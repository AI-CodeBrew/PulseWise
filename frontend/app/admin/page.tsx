"use client";

import Link from "next/link";

import { Card, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { auditLabel } from "@/lib/audit";
import { formatDateTime } from "@/lib/format";
import { formatMoney, formatNumber, formatUsd } from "@/lib/format";
import type { AdminOverview, AdminUsage, BusinessOverview } from "@/lib/types";

export default function AdminHomePage() {
  const overview = useApi<AdminOverview>("/api/admin/overview");
  const usage = useApi<AdminUsage>("/api/admin/usage");
  const business = useApi<BusinessOverview>("/api/admin/business");

  return (
    <>
      <PageHeader title="Admin overview" description="Your clients, at a glance." />

      <Async
        query={overview}
        skeleton={
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        }
      >
        {(o) => (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Clients" value={o.clients.total} note={`${o.clients.active} active · ${o.clients.suspended} suspended`} href="/admin/clients" />
              <Stat label="Websites" value={o.websites} note="being tracked" href="/admin/clients" />
              <Stat
                label="Open alerts"
                value={o.open_alerts}
                note={o.open_alerts === 0 ? "✓ all good" : "need your attention"}
                href="/admin/alerts"
              />
              <Stat label="Client users" value={o.users} note={`${o.admins} admin${o.admins === 1 ? "" : "s"} besides`} href="/admin/users" />
            </div>

            {business.data && <BusinessCards b={business.data} />}

            <Link href="/admin/usage" className="mt-3 block rounded-xl border border-line bg-surface p-4 hover:bg-surface-2">
              <p className="text-xs font-medium text-ink-2">This month at PostHog</p>
              {usage.data ? (
                <p className="mt-1.5 text-sm text-ink">
                  <span className="text-2xl font-semibold tracking-tight">{formatNumber(usage.data.totals.events)}</span> events so far ·{" "}
                  about <span className="font-semibold">{formatUsd(usage.data.cost.total_usd)}</span> so far, projected{" "}
                  <span className="font-semibold">{formatUsd(usage.data.cost.projected_total_usd)}</span> (estimate)
                </p>
              ) : (
                <p className="mt-1.5 text-sm text-muted">Loading…</p>
              )}
            </Link>

            <Card className="mt-6">
              <CardHeader title="Recent activity" action={<Link href="/admin/audit" className="text-xs font-medium text-accent hover:underline">Full audit log →</Link>} />
              {o.recent_activity.length === 0 ? (
                <p className="px-5 pb-5 text-sm text-muted">Nothing yet.</p>
              ) : (
                <ul>
                  {o.recent_activity.map((e) => (
                    <li key={e.id} className="flex flex-wrap items-baseline justify-between gap-2 border-t border-line px-5 py-2 text-sm">
                      <span className="text-ink">
                        {auditLabel(e.action)} <span className="text-muted">· {e.actor ?? "system"}</span>
                      </span>
                      <span className="text-xs text-muted">{e.created_at ? formatDateTime(e.created_at) : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </>
        )}
      </Async>
    </>
  );
}

function Stat({ label, value, note, href }: { label: string; value: number; note: string; href: string }) {
  return (
    <Link href={href} className="rounded-xl border border-line bg-surface p-4 hover:bg-surface-2">
      <p className="text-xs font-medium text-ink-2">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      <p className="mt-1 text-xs text-muted">{note}</p>
    </Link>
  );
}

function BusinessCards({ b }: { b: BusinessOverview }) {
  const both = (v: { PKR: number; USD: number }) => [v.PKR ? formatMoney(v.PKR, "PKR") : null, v.USD ? formatMoney(v.USD, "USD") : null].filter(Boolean).join(" + ") || formatMoney(0, "PKR");
  return (
    <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Link href="/admin/clients" className="rounded-xl border border-line bg-surface p-4 hover:bg-surface-2">
        <p className="text-xs font-medium text-ink-2">Monthly income (MRR)</p>
        <p className="mt-1.5 text-xl font-semibold tracking-tight text-ink">{formatMoney(b.mrr.total_pkr, "PKR")}</p>
        <p className="mt-1 text-xs text-muted">
          {b.clients.paying} paying client{b.clients.paying === 1 ? "" : "s"} · {both(b.mrr)}
        </p>
      </Link>
      <Link href="/admin/invoices" className="rounded-xl border border-line bg-surface p-4 hover:bg-surface-2">
        <p className="text-xs font-medium text-ink-2">Unpaid invoices</p>
        <p className="mt-1.5 text-xl font-semibold tracking-tight text-ink">{b.unpaid.count}</p>
        <p className="mt-1 text-xs text-muted">
          {both(b.unpaid)} owed{b.unpaid.overdue_count > 0 ? ` · ✕ ${b.unpaid.overdue_count} overdue` : ""}
        </p>
      </Link>
      <div className="rounded-xl border border-line bg-surface p-4">
        <p className="text-xs font-medium text-ink-2">Received this month</p>
        <p className="mt-1.5 text-xl font-semibold tracking-tight text-ink">{both(b.received_this_month)}</p>
        <p className="mt-1 text-xs text-muted">payments you recorded</p>
      </div>
      <Link href="/admin/usage" className="rounded-xl border border-line bg-surface p-4 hover:bg-surface-2">
        <p className="text-xs font-medium text-ink-2">Estimated margin / month</p>
        <p className="mt-1.5 text-xl font-semibold tracking-tight text-ink">{formatMoney(Math.round(b.estimated_margin_pkr), "PKR")}</p>
        <p className="mt-1 text-xs text-muted">income minus ~{formatUsd(b.posthog_cost_usd.projected)} PostHog</p>
      </Link>
    </div>
  );
}
