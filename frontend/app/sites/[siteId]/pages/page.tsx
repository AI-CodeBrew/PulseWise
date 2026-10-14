"use client";

import { Card } from "@/components/ui/Card";
import { DataTable, ShareBar } from "@/components/ui/DataTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useDays } from "@/hooks/useDays";
import { useSiteApi } from "@/hooks/useSite";
import { formatNumber } from "@/lib/format";
import type { ListResponse, PageRow } from "@/lib/types";

export default function PagesPage() {
  const api = useSiteApi();
  const days = useDays();
  const pages = useApi<ListResponse<PageRow>>(api("/top-pages"), { days, limit: 100 });

  return (
    <>
      <PageHeader title="Pages" description="Which pages people look at most." />
      <Card className="pt-1">
        <Async query={pages} skeleton={<div className="pt-4"><SkeletonRows rows={10} /></div>}>
          {(p) => {
            if (p.results.length === 0) return <EmptyState message="No pageviews in this period." />;
            const maxViews = Math.max(...p.results.map((r) => r.views));
            return (
              <DataTable
                rows={p.results}
                rowKey={(r) => r.path}
                columns={[
                  {
                    header: "Page",
                    cell: (r) => (
                      <div className="min-w-48">
                        <span className="break-all">{r.path}</span>
                        <ShareBar value={r.views} max={maxViews} />
                      </div>
                    ),
                  },
                  { header: "Visitors", align: "right", cell: (r) => formatNumber(r.visitors) },
                  { header: "Views", align: "right", cell: (r) => formatNumber(r.views) },
                  {
                    header: "Views per visitor",
                    align: "right",
                    className: "hidden sm:table-cell",
                    cell: (r) => (r.visitors ? (r.views / r.visitors).toFixed(1) : "–"),
                  },
                ]}
              />
            );
          }}
        </Async>
      </Card>
    </>
  );
}
