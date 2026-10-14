"use client";

import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { LoadMore, PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useCursorList } from "@/hooks/useCursorList";
import { useDays } from "@/hooks/useDays";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { SessionRow } from "@/lib/types";

export default function SessionsPage() {
  const api = useSiteApi();
  const days = useDays();
  const siteHref = useSiteHref();
  const list = useCursorList<SessionRow>(api("/sessions"), { days, limit: 25 });

  return (
    <>
      <PageHeader title="Sessions" description="Each visit to your website, newest first. Click one to see what happened." />
      <Card className="pt-1">
        <Async query={list} skeleton={<div className="pt-4"><SkeletonRows rows={10} /></div>}>
          {() =>
            list.items.length === 0 ? (
              <EmptyState message="No sessions in this period." />
            ) : (
              <>
                <DataTable
                  rows={list.items}
                  rowKey={(s) => s.session_id}
                  rowHref={(s) => siteHref(`/sessions/${s.session_id}`)}
                  columns={[
                    { header: "Started", cell: (s) => <span className="whitespace-nowrap">{formatDateTime(s.started_at)}</span> },
                    { header: "Length", align: "right", cell: (s) => formatDuration(s.duration) },
                    { header: "Pages", align: "right", cell: (s) => s.pageviews },
                    { header: "Entry page", className: "hidden md:table-cell", cell: (s) => <span className="break-all">{s.entry_page}</span> },
                    { header: "Exit page", className: "hidden lg:table-cell", cell: (s) => <span className="break-all">{s.exit_page}</span> },
                    { header: "Channel", className: "hidden sm:table-cell", cell: (s) => s.channel },
                    { header: "Bounced", cell: (s) => <BounceBadge bounced={s.is_bounce} /> },
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

/** "Yes"/"No" chip. A bounce = the visitor saw one page and left. */
function BounceBadge({ bounced }: { bounced: boolean }) {
  return bounced ? (
    <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs text-ink-2">Yes</span>
  ) : (
    <span className="px-2 py-0.5 text-xs text-muted">No</span>
  );
}
