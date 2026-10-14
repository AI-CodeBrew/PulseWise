"use client";

import Link from "next/link";
import { useState } from "react";

import { ALERTS_CHANGED } from "@/components/admin/AdminShell";
import { Card } from "@/components/ui/Card";
import { Badge, Button, Message, useAction } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { apiPost } from "@/lib/api";
import { formatDateTime, timeAgo } from "@/lib/format";
import type { AdminAlert, ListResponse } from "@/lib/types";

type Status = "open" | "resolved";

const KIND_LABEL: Record<string, string> = {
  no_events: "No data arriving",
  posthog_error: "PostHog connection",
  job_failed: "Background job",
  usage_limit: "Usage limit",
  invoice_overdue: "Overdue invoice",
};

export default function AlertsPage() {
  const [status, setStatus] = useState<Status>("open");
  const alerts = useApi<ListResponse<AdminAlert> & { open_count: number }>("/api/admin/alerts", { status, limit: 100 });
  const resolve = useAction(async (id: string) => {
    await apiPost(`/api/admin/alerts/${id}/resolve`);
    alerts.reload();
    window.dispatchEvent(new Event(ALERTS_CHANGED)); // refresh the number in the menu
  });

  return (
    <>
      <PageHeader title="Alerts" description="Things that need your attention. Most clear by themselves once the problem is fixed." />
      <div role="tablist" aria-label="Status" className="mb-4 flex gap-1">
        {(["open", "resolved"] as const).map((s) => (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={status === s}
            onClick={() => setStatus(s)}
            className={`rounded-md px-3 py-1.5 text-sm capitalize ${status === s ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-surface-2"}`}
          >
            {s}
            {s === "open" && alerts.data ? ` (${alerts.data.open_count})` : ""}
          </button>
        ))}
      </div>
      {resolve.error && (
        <div className="mb-4">
          <Message kind="error">{resolve.error}</Message>
        </div>
      )}
      <Async query={alerts} skeleton={<Card className="pt-4"><SkeletonRows rows={4} /></Card>}>
        {(a) =>
          a.results.length === 0 ? (
            <Card>
              <EmptyState message={status === "open" ? "✓ Nothing needs your attention right now." : "No resolved alerts yet."} />
            </Card>
          ) : (
            <ul className="space-y-3">
              {a.results.map((alert) => (
                <li key={alert.id}>
                  <Card className="p-4 sm:p-5">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="mb-1.5 flex flex-wrap items-center gap-2">
                          <Badge tone={alert.severity === "critical" ? "red" : alert.severity === "warning" ? "amber" : "blue"}>
                            {alert.severity === "critical" ? "Critical" : alert.severity === "warning" ? "Warning" : "Info"}
                          </Badge>
                          <span className="text-xs text-muted">{KIND_LABEL[alert.kind] ?? alert.kind}</span>
                          {alert.occurrences > 1 && <span className="text-xs text-muted">· happened {alert.occurrences} times</span>}
                        </div>
                        <p className="break-words text-sm text-ink">{alert.message}</p>
                        <p className="mt-2 text-xs text-muted">
                          {alert.client_name && alert.client_id && (
                            <>
                              <Link href={`/admin/clients/${alert.client_id}`} className="text-accent hover:underline">
                                {alert.client_name}
                              </Link>
                              {" · "}
                            </>
                          )}
                          {alert.website_name && alert.website_id && (
                            <>
                              <Link href={`/admin/websites/${alert.website_id}`} className="text-accent hover:underline">
                                {alert.website_name}
                              </Link>
                              {" · "}
                            </>
                          )}
                          {alert.status === "open"
                            ? `first seen ${alert.created_at ? timeAgo(alert.created_at) : "?"}, last ${alert.last_seen_at ? timeAgo(alert.last_seen_at) : "?"}`
                            : `resolved ${alert.resolved_at ? formatDateTime(alert.resolved_at) : ""}`}
                        </p>
                      </div>
                      {alert.status === "open" && (
                        <Button variant="secondary" busy={resolve.busy} onClick={() => resolve.run(alert.id)}>
                          Mark as dealt with
                        </Button>
                      )}
                    </div>
                  </Card>
                </li>
              ))}
            </ul>
          )
        }
      </Async>
    </>
  );
}
