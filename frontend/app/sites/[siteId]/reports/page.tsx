"use client";

import { Badge } from "@/components/ui/Form";
import { Card } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { formatDay } from "@/lib/format";
import type { ListResponse, ReportListItem } from "@/lib/types";

/** Every weekly report of this website, newest first. Reports are written automatically on Monday mornings. */
export default function ReportsPage() {
  const api = useSiteApi();
  const siteHref = useSiteHref();
  const reports = useApi<ListResponse<ReportListItem>>(api("/reports"));

  return (
    <>
      <PageHeader title="Weekly reports" description="A short summary of each week, written for you. A new one arrives every Monday." />
      <Card>
        <Async query={reports} skeleton={<SkeletonRows />}>
          {(r) =>
            r.results.length === 0 ? (
              <EmptyState message="Your first report will appear here on Monday morning." />
            ) : (
              <DataTable
                rows={r.results}
                rowKey={(x) => x.id}
                rowHref={(x) => siteHref(`/reports/${x.id}`)}
                columns={[
                  { header: "Week", cell: (x) => <span className="font-medium">{formatDay(x.period_start)} – {formatDay(x.period_end)}</span> },
                  { header: "Summary", className: "hidden md:table-cell", cell: (x) => <span className="text-ink-2">{x.summary.headline}</span> },
                  { header: "Emailed", align: "right", cell: (x) => (x.emailed_at ? <Badge tone="green">Sent</Badge> : <Badge tone="gray">Not sent</Badge>) },
                ]}
              />
            )
          }
        </Async>
      </Card>
    </>
  );
}
