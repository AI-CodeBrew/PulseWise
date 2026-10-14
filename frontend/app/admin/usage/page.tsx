"use client";

import Link from "next/link";
import { useState } from "react";

import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable, ShareBar } from "@/components/ui/DataTable";
import { Button, Message, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiPost } from "@/lib/api";
import { formatDateTime, formatMonth, formatNumber, formatUsd, shiftMonth, timeAgo } from "@/lib/format";
import type { AdminUsage } from "@/lib/types";

export default function UsagePage() {
  const [month, setMonth] = useState<string | undefined>(undefined); // undefined = this month
  const usage = useApi<AdminUsage>("/api/admin/usage", { month });
  const current = usage.data?.month;

  const syncNow = useAction(async () => {
    await apiPost("/api/admin/jobs/usage_sync/run");
    setTimeout(usage.reload, 8000); // the job takes a few seconds
  });

  return (
    <>
      <PageHeader
        title="Usage & cost"
        description="How many events each website sends, and what that costs you at PostHog."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" disabled={!current} onClick={() => current && setMonth(shiftMonth(current, -1))} aria-label="Previous month">
              ←
            </Button>
            <span className="min-w-36 text-center text-sm font-medium text-ink">{current ? formatMonth(current) : "…"}</span>
            <Button variant="secondary" disabled={!current || !usage.data?.in_progress} onClick={() => current && setMonth(shiftMonth(current, 1))} aria-label="Next month">
              →
            </Button>
          </div>
        }
      />

      <Async
        query={usage}
        skeleton={
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-24 rounded-xl" />
            ))}
          </div>
        }
      >
        {(u) => (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Events so far" value={formatNumber(u.totals.events)} note={`${u.days_elapsed} of ${u.days_in_month} days`} />
              <Stat label={u.in_progress ? "Projected for the month" : "Events in the month"} value={formatNumber(u.totals.projected_events)} note={u.in_progress ? "if traffic stays like this" : "final"} />
              <Stat label="Cost so far (estimate)" value={formatUsd(u.cost.total_usd)} note={`first ${formatNumber(u.cost.free_events)} events are free`} />
              <Stat label={u.in_progress ? "Projected cost" : "Cost"} value={formatUsd(u.cost.projected_total_usd)} note="estimate" />
            </div>
            <p className="mt-3 text-xs text-muted">
              {u.cost.note}{" "}
              {u.last_synced_at ? `Counts updated ${timeAgo(u.last_synced_at)} (${formatDateTime(u.last_synced_at)}); they refresh every hour.` : "Counts have not been collected yet."}{" "}
              <button type="button" className="text-accent hover:underline" onClick={() => syncNow.run()} disabled={syncNow.busy}>
                {syncNow.busy ? "Starting…" : "Refresh now"}
              </button>
            </p>
            {syncNow.error && (
              <div className="mt-2">
                <Message kind="error">{syncNow.error}</Message>
              </div>
            )}

            <Card className="mt-6">
              <CardHeader title="By client" subtitle="Who costs you the most" />
              {u.clients.length === 0 ? (
                <EmptyState message="No data yet." />
              ) : (
                <DataTable
                  rows={u.clients}
                  rowKey={(c) => c.client_id}
                  rowHref={(c) => `/admin/clients/${c.client_id}`}
                  columns={[
                    { header: "Client", cell: (c) => <span className="font-medium">{c.client_name}</span> },
                    {
                      header: "Events",
                      align: "right",
                      cell: (c) => formatNumber(c.events),
                    },
                    { header: "Recordings", align: "right", className: "hidden sm:table-cell", cell: (c) => formatNumber(c.recordings) },
                    { header: "Est. cost", align: "right", cell: (c) => formatUsd(c.estimated_cost_usd) },
                  ]}
                />
              )}
            </Card>

            <Card className="mt-6">
              <CardHeader title="By website" />
              {u.websites.length === 0 ? (
                <EmptyState message="No websites yet." />
              ) : (
                <DataTable
                  rows={u.websites}
                  rowKey={(w) => w.website_id}
                  rowHref={(w) => `/admin/websites/${w.website_id}`}
                  columns={[
                    {
                      header: "Website",
                      cell: (w) => (
                        <div className="min-w-40">
                          <span className="font-medium">{w.website_name}</span>
                          <span className="block text-xs text-muted">{w.client_name}</span>
                          <ShareBar value={w.events} max={Math.max(...u.websites.map((x) => x.events), 1)} />
                        </div>
                      ),
                    },
                    { header: "Events", align: "right", cell: (w) => formatNumber(w.events) },
                    { header: "Share", align: "right", className: "hidden sm:table-cell", cell: (w) => `${(w.share_of_events * 100).toFixed(1)}%` },
                    { header: "Projected", align: "right", className: "hidden md:table-cell", cell: (w) => formatNumber(w.projected_events) },
                    { header: "Est. cost", align: "right", cell: (w) => formatUsd(w.estimated_cost_usd) },
                  ]}
                />
              )}
            </Card>
            <p className="mt-4 text-sm text-ink-2">
              Silent or broken websites show up on the{" "}
              <Link href="/admin/alerts" className="text-accent hover:underline">
                Alerts
              </Link>{" "}
              page.
            </p>
          </>
        )}
      </Async>
    </>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-xs font-medium text-ink-2">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      <p className="mt-1 text-xs text-muted">{note}</p>
    </div>
  );
}
