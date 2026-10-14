"use client";

import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { LoadMore, PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useCursorList } from "@/hooks/useCursorList";
import { useDays } from "@/hooks/useDays";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { formatDateTime, formatDuration, formatNumber } from "@/lib/format";
import type { Recording } from "@/lib/types";

export default function RecordingsPage() {
  const api = useSiteApi();
  const siteHref = useSiteHref();
  const days = useDays();
  const list = useCursorList<Recording>(api("/recordings"), { days, limit: 25 });

  return (
    <>
      <PageHeader title="Recordings" description="Watch what visitors did on your website. Click a row to play it." />
      <Card className="pt-1">
        <Async query={list} skeleton={<div className="pt-4"><SkeletonRows rows={8} /></div>}>
          {() =>
            list.items.length === 0 ? (
              <EmptyState message="No recordings in this period." />
            ) : (
              <>
                <DataTable
                  rows={list.items}
                  rowKey={(r) => r.id}
                  rowHref={(r) => siteHref(`/recordings/${r.id}`)}
                  columns={[
                    { header: "Started", cell: (r) => <span className="whitespace-nowrap">{formatDateTime(r.start_time)}</span> },
                    { header: "Length", align: "right", cell: (r) => formatDuration(r.duration) },
                    { header: "Active", align: "right", className: "hidden sm:table-cell", cell: (r) => formatDuration(r.active_seconds) },
                    { header: "Clicks", align: "right", className: "hidden sm:table-cell", cell: (r) => formatNumber(r.clicks) },
                    {
                      header: "Person",
                      className: "hidden md:table-cell",
                      cell: (r) => <span className="break-all font-mono text-xs">{r.person}</span>,
                    },
                    {
                      header: "First page",
                      className: "hidden lg:table-cell",
                      cell: (r) => <span className="break-all">{r.start_url ? safePath(r.start_url) : "–"}</span>,
                    },
                    { header: "", align: "right", cell: () => <span className="whitespace-nowrap text-xs font-medium text-accent">▶ Play</span> },
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

/** "http://shop.com/products/x?y=1" -> "/products/x" */
function safePath(url: string): string {
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
}
