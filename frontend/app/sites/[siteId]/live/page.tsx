"use client";

import { useState } from "react";

import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useDays } from "@/hooks/useDays";
import { useSiteApi } from "@/hooks/useSite";
import { eventKind, eventLabel } from "@/lib/events";
import { formatDateTime, formatNumber, formatTime, timeAgo } from "@/lib/format";
import type { CustomEventRow, ListResponse, LiveEvent } from "@/lib/types";

const REFRESH_MS = 10_000;

export default function LivePage() {
  const api = useSiteApi();
  const days = useDays();
  const [paused, setPaused] = useState(false);
  // Re-fetches every 10 seconds (the backend caches this for 10s too).
  const live = useApi<ListResponse<LiveEvent>>(api("/events/live"), undefined, { refreshMs: REFRESH_MS, paused });
  const custom = useApi<ListResponse<CustomEventRow>>(api("/events/custom"), { days });

  return (
    <>
      <PageHeader
        title="Live events"
        description="The latest things visitors did on your website."
        action={
          <div className="flex items-center gap-3 text-xs text-ink-2">
            <span className="flex items-center gap-1.5">
              <span
                className={`h-2 w-2 rounded-full ${paused ? "bg-muted" : "animate-pulse bg-good"}`}
                aria-hidden="true"
              />
              {paused ? "Paused" : "Updating every 10 seconds"}
            </span>
            <button
              type="button"
              onClick={() => setPaused((p) => !p)}
              className="rounded-md border border-line bg-surface px-2.5 py-1 font-medium text-ink hover:bg-surface-2"
            >
              {paused ? "Resume" : "Pause"}
            </button>
          </div>
        }
      />

      <Card>
        <CardHeader title="Latest 50 events" subtitle="From the last 7 days" />
        <Async query={live} skeleton={<SkeletonRows rows={10} />}>
          {(l) =>
            l.results.length === 0 ? (
              <EmptyState message="No events in the last 7 days. Visit your website and they'll appear here." />
            ) : (
              <ul>
                {l.results.map((e) => (
                  <li key={e.id} className="flex gap-3 border-t border-line px-4 py-2.5 text-sm sm:px-5">
                    <span
                      className="w-16 shrink-0 text-xs text-muted tabular-nums sm:w-20"
                      title={formatDateTime(e.timestamp)}
                    >
                      {timeAgo(e.timestamp)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-ink">
                        <span className={eventKind(e.event) === "error" ? "font-medium text-bad" : "font-medium"}>
                          {eventLabel(e.event)}
                        </span>
                        {e.path && <span className="ml-2 break-all text-ink-2">{e.path}</span>}
                      </p>
                      <p className="mt-0.5 text-xs text-muted">
                        {[e.person, [e.city, e.country].filter(Boolean).join(", "), e.device, e.browser]
                          .filter(Boolean)
                          .join(" · ")}
                        <span className="hidden sm:inline"> · {formatTime(e.timestamp)}</span>
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )
          }
        </Async>
      </Card>

      <Card className="mt-6">
        <CardHeader
          title="Your custom events"
          subtitle={`Events your website sends on purpose (e.g. button clicks), last ${days} days`}
        />
        <Async query={custom} skeleton={<SkeletonRows />}>
          {(c) =>
            c.results.length === 0 ? (
              <EmptyState message="No custom events yet. They appear here once your site sends them." />
            ) : (
              <DataTable
                rows={c.results}
                rowKey={(r) => r.event}
                columns={[
                  { header: "Event", cell: (r) => <span className="font-mono text-xs">{r.event}</span> },
                  { header: "Times", align: "right", cell: (r) => formatNumber(r.count) },
                  { header: "Visitors", align: "right", cell: (r) => formatNumber(r.visitors) },
                  {
                    header: "Last seen",
                    className: "hidden sm:table-cell",
                    cell: (r) => <span title={formatDateTime(r.last_seen)}>{timeAgo(r.last_seen)}</span>,
                  },
                ]}
              />
            )
          }
        </Async>
      </Card>
    </>
  );
}
