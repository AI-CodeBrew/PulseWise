"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { HBarChart } from "@/components/charts/HBarChart";
import { TrendChart } from "@/components/charts/TrendChart";
import { KpiCard } from "@/components/KpiCard";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Form";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { API_URL } from "@/lib/api";
import { formatCompact, formatDay, formatDuration, formatNumber, formatPercent, formatShopMoney } from "@/lib/format";
import type { ReportDetail } from "@/lib/types";

/** One weekly report: the written summary on top, then the numbers behind it. */
export default function ReportPage() {
  const { rid } = useParams<{ rid: string }>();
  const api = useSiteApi();
  const siteHref = useSiteHref();
  const report = useApi<ReportDetail>(api(`/reports/${encodeURIComponent(rid)}`));

  return (
    <>
      <Link href={siteHref("/reports")} className="mb-3 inline-block text-sm text-accent hover:underline">
        ← All reports
      </Link>
      <Async query={report} skeleton={<Skeleton className="h-96 rounded-xl" />}>
        {(r) => {
          const d = r.data;
          const rtl = r.language === "ur"; // Urdu is written right to left
          return (
            <>
              <PageHeader
                title={`Week of ${formatDay(r.period_start)} – ${formatDay(r.period_end)}`}
                description={r.website_name}
                action={
                  <a
                    href={`${API_URL}${api(`/reports/${r.id}/pdf`)}`}
                    className="rounded-lg border border-line bg-surface px-3.5 py-2 text-sm font-medium text-ink hover:bg-surface-2"
                  >
                    Download PDF
                  </a>
                }
              />

              <Card>
                <div dir={rtl ? "rtl" : "ltr"} className="space-y-3 px-4 py-5 sm:px-5">
                  <h2 className="text-lg font-semibold text-ink">{r.summary.headline}</h2>
                  {r.summary.bullets.length > 0 && (
                    <ul className="list-disc space-y-1.5 ps-5 text-sm text-ink">
                      {r.summary.bullets.map((b) => (
                        <li key={b}>{b}</li>
                      ))}
                    </ul>
                  )}
                  <p className="rounded-lg bg-accent-soft px-3 py-2 text-sm text-ink">
                    <strong>This week: </strong>
                    {r.summary.recommendation}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5 text-xs text-muted sm:px-5">
                  {r.summary_source === "ai" ? <Badge tone="blue">Written by AI from your numbers</Badge> : <Badge tone="gray">Automatic summary</Badge>}
                  <span>Compared with the 7 days before.</span>
                </div>
              </Card>

              <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
                <KpiCard label="Visitors" value={formatCompact(d.kpis.visitors.current)} metric={d.kpis.visitors} days={7} />
                <KpiCard label="Pageviews" value={formatCompact(d.kpis.pageviews.current)} metric={d.kpis.pageviews} days={7} />
                <KpiCard label="Sessions" value={formatCompact(d.kpis.sessions.current)} metric={d.kpis.sessions} days={7} />
                <KpiCard label="Avg. visit length" value={formatDuration(d.kpis.avg_session_duration.current)} metric={d.kpis.avg_session_duration} days={7} />
                <KpiCard label="Bounce rate" value={formatPercent(d.kpis.bounce_rate.current)} metric={d.kpis.bounce_rate} days={7} goodWhen="down" />
              </div>

              {d.sales && (
                <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
                  <KpiCard label="Orders" value={formatCompact(d.sales.orders.current)} metric={d.sales.orders} days={7} />
                  <KpiCard label="Sales" value={formatShopMoney(d.sales.revenue.current, d.sales.currency)} metric={d.sales.revenue} days={7} />
                  <KpiCard label="Average order" value={formatShopMoney(d.sales.average_order_value.current, d.sales.currency)} metric={d.sales.average_order_value} days={7} />
                  <div className="rounded-xl border border-line bg-surface p-4">
                    <p className="text-xs font-medium text-ink-2">Best seller</p>
                    <p className="mt-1.5 break-words text-base font-semibold text-ink">{d.sales.top_product?.title ?? "No orders"}</p>
                    {d.sales.top_product && <p className="mt-1 text-xs text-muted">{formatNumber(d.sales.top_product.units)} sold</p>}
                  </div>
                </div>
              )}

              <Card className="mt-6">
                <CardHeader title="Visitors and pageviews" subtitle="Per day, Monday to Sunday" />
                <TrendChart data={d.daily} />
              </Card>

              <div className="mt-6 grid gap-6 lg:grid-cols-2">
                <Card>
                  <CardHeader title="Top pages" />
                  {d.top_pages.length === 0 ? (
                    <EmptyState message="No pageviews this week." />
                  ) : (
                    <DataTable
                      rows={d.top_pages}
                      rowKey={(p) => p.path}
                      columns={[
                        { header: "Page", cell: (p) => <span className="break-all">{p.path}</span> },
                        { header: "Visitors", align: "right", cell: (p) => formatNumber(p.visitors) },
                        { header: "Views", align: "right", cell: (p) => formatNumber(p.views) },
                      ]}
                    />
                  )}
                </Card>
                <Card>
                  <CardHeader title="Where visitors came from" subtitle="Visits by source" />
                  <HBarChart data={d.sources.map((s) => ({ name: s.name, value: s.sessions }))} valueLabel="Visits" />
                </Card>
                <Card>
                  <CardHeader title="Countries" />
                  <HBarChart data={d.countries.map((c) => ({ name: c.name, value: c.visitors }))} valueLabel="Visitors" />
                </Card>
                <Card>
                  <CardHeader title="Devices" />
                  <HBarChart data={d.devices.map((x) => ({ name: x.name, value: x.visitors }))} valueLabel="Visitors" />
                </Card>
              </div>

              {d.custom_events.length > 0 && (
                <Card className="mt-6">
                  <CardHeader title="Actions people took" subtitle="Events you track, such as clicks and sign-ups" />
                  <DataTable
                    rows={d.custom_events}
                    rowKey={(e) => e.event}
                    columns={[
                      { header: "Action", cell: (e) => e.event },
                      { header: "Times", align: "right", cell: (e) => formatNumber(e.count) },
                    ]}
                  />
                </Card>
              )}
            </>
          );
        }}
      </Async>
    </>
  );
}
