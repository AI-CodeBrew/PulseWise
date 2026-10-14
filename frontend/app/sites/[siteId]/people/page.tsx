"use client";

import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { LoadMore, PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useCursorList } from "@/hooks/useCursorList";
import { useDays } from "@/hooks/useDays";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { formatDateTime, formatNumber, timeAgo } from "@/lib/format";
import type { PersonRow } from "@/lib/types";

export default function PeoplePage() {
  const api = useSiteApi();
  const days = useDays();
  const siteHref = useSiteHref();
  const list = useCursorList<PersonRow>(api("/persons"), { days, limit: 25 });

  return (
    <>
      <PageHeader
        title="People"
        description={`Visitors active in the last ${days} days, most recent first. Anonymous visitors show an ID instead of a name.`}
      />
      <Card className="pt-1">
        <Async query={list} skeleton={<div className="pt-4"><SkeletonRows rows={10} /></div>}>
          {() =>
            list.items.length === 0 ? (
              <EmptyState message="No visitors in this period." />
            ) : (
              <>
                <DataTable
                  rows={list.items}
                  rowKey={(p) => p.id}
                  rowHref={(p) => siteHref(`/people/${p.id}`)}
                  columns={[
                    {
                      header: "Person",
                      cell: (p) => <span className={p.email ? "" : "break-all font-mono text-xs"}>{p.name}</span>,
                    },
                    {
                      header: "Last seen",
                      cell: (p) => (
                        <span className="whitespace-nowrap" title={formatDateTime(p.last_seen)}>
                          {timeAgo(p.last_seen)}
                        </span>
                      ),
                    },
                    {
                      header: "First seen",
                      className: "hidden md:table-cell",
                      cell: (p) => <span className="whitespace-nowrap">{formatDateTime(p.first_seen)}</span>,
                    },
                    { header: "Pageviews", align: "right", cell: (p) => formatNumber(p.pageviews) },
                    { header: "Events", align: "right", className: "hidden sm:table-cell", cell: (p) => formatNumber(p.events) },
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
