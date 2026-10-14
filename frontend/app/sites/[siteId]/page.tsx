"use client";

import Link from "next/link";

import { HBarChart } from "@/components/charts/HBarChart";
import { TrendChart } from "@/components/charts/TrendChart";
import { KpiCard } from "@/components/KpiCard";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useDays } from "@/hooks/useDays";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { formatCompact, formatDuration, formatNumber, formatPercent } from "@/lib/format";
import type { ListResponse, Overview, PageRow, Sources, Trends } from "@/lib/types";

export default function OverviewPage() {
  const api = useSiteApi();
  const days = useDays();
  const siteHref = useSiteHref();

  // Four requests run in parallel; each card shows its own loading/error state.
  const overview = useApi<Overview>(api("/overview"), { days });
  const trends = useApi<Trends>(api("/trends"), { days });
  const topPages = useApi<ListResponse<PageRow>>(api("/top-pages"), { days, limit: 5 });
  const sources = useApi<Sources>(api("/sources"), { days });

  return (
    <>
      <PageHeader title="Overview" description={`How your website did in the last ${days} days.`} />

      {/* KPI cards */}
      <Async
        query={overview}
        skeleton={
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-[106px] rounded-xl" />
            ))}
          </div>
        }
      >
        {(o) => (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <KpiCard label="Visitors" value={formatCompact(o.visitors.current)} metric={o.visitors} days={days} />
            <KpiCard label="Pageviews" value={formatCompact(o.pageviews.current)} metric={o.pageviews} days={days} />
            <KpiCard label="Sessions" value={formatCompact(o.sessions.current)} metric={o.sessions} days={days} />
            <KpiCard
              label="Avg. visit length"
              value={formatDuration(o.avg_session_duration.current)}
              metric={o.avg_session_duration}
              days={days}
            />
            <KpiCard
              label="Bounce rate"
              value={formatPercent(o.bounce_rate.current)}
              metric={o.bounce_rate}
              days={days}
              goodWhen="down"
            />
          </div>
        )}
      </Async>

      {/* Visitors & pageviews over time */}
      <Card className="mt-6">
        <CardHeader title="Visitors and pageviews" subtitle="Per day" />
        <Async query={trends} skeleton={<Skeleton className="mx-5 mb-5 h-[260px]" />}>
          {(t) => <TrendChart data={t.series} />}
        </Async>
      </Card>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {/* Top pages */}
        <Card>
          <CardHeader title="Top pages" action={<ViewAll href={siteHref("/pages")} />} />
          <Async query={topPages} skeleton={<SkeletonRows />}>
            {(p) =>
              p.results.length === 0 ? (
                <EmptyState message="No pageviews in this period." />
              ) : (
                <DataTable
                  rows={p.results}
                  rowKey={(r) => r.path}
                  columns={[
                    { header: "Page", cell: (r) => <span className="break-all">{r.path}</span> },
                    { header: "Visitors", align: "right", cell: (r) => formatNumber(r.visitors) },
                    { header: "Views", align: "right", cell: (r) => formatNumber(r.views) },
                  ]}
                />
              )
            }
          </Async>
        </Card>

        {/* Top sources */}
        <Card>
          <CardHeader
            title="Top sources"
            subtitle="Visits by referring website"
            action={<ViewAll href={siteHref("/sources")} />}
          />
          <Async query={sources} skeleton={<SkeletonRows />}>
            {(s) => (
              <HBarChart
                data={s.referrers.slice(0, 5).map((r) => ({ name: r.name, value: r.sessions }))}
                valueLabel="Visits"
              />
            )}
          </Async>
        </Card>
      </div>
    </>
  );
}

function ViewAll({ href }: { href: string }) {
  return (
    <Link href={href} className="text-xs font-medium text-accent hover:underline">
      View all →
    </Link>
  );
}
