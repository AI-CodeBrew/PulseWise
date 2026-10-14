"use client";

import { RevenueChart } from "@/components/charts/RevenueChart";
import { KpiCard } from "@/components/KpiCard";
import { Card, CardHeader } from "@/components/ui/Card";
import { DataTable } from "@/components/ui/DataTable";
import { Badge, Message } from "@/components/ui/Form";
import { LoadMore, PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton, SkeletonRows } from "@/components/ui/States";
import { SupportLinks } from "@/components/billing/parts";
import { useAuth } from "@/components/auth/AuthProvider";
import { useApi } from "@/hooks/useApi";
import { useCursorList } from "@/hooks/useCursorList";
import { useDays } from "@/hooks/useDays";
import { useSiteApi } from "@/hooks/useSite";
import { formatCompact, formatDateTime, formatNumber, formatPercent, formatShopMoney, timeAgo } from "@/lib/format";
import type { SalesResponse, SalesSummary, ShopOrderRow } from "@/lib/types";

/** Sales from the client's Shopify store, next to what their website traffic did. */
export default function SalesPage() {
  const api = useSiteApi();
  const days = useDays();
  const sales = useApi<SalesResponse>(api("/sales"), { days });

  return (
    <>
      <PageHeader title="Sales" description={`What your online store sold in the last ${days} days, and how your website helped.`} />
      <Async query={sales} skeleton={<Skeleton className="h-96 rounded-xl" />}>
        {(s) => (s.connected ? <Connected summary={s} days={days} /> : <NotConnected />)}
      </Async>
    </>
  );
}

function NotConnected() {
  const { me } = useAuth();
  return (
    <Card className="p-6 text-center">
      <p className="text-2xl" aria-hidden="true">
        🛍️
      </p>
      <h2 className="mt-2 text-base font-semibold text-ink">Your store isn&apos;t connected yet</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">
        Once your Shopify store is connected, you&apos;ll see your sales, orders and best sellers here, next to your website visitors. Ask us and we&apos;ll set it up.
      </p>
      <SupportLinks support={me?.support} className="mt-4 justify-center" />
    </Card>
  );
}

function Connected({ summary: s, days }: { summary: SalesSummary; days: number }) {
  const api = useSiteApi();
  const orders = useCursorList<ShopOrderRow>(api("/sales/orders"), { limit: 25 });
  const money = (n: number) => formatShopMoney(n, s.currency);

  return (
    <>
      {s.sync_failing && (
        <div className="mb-4">
          <Message kind="info">We couldn&apos;t refresh your orders just now, so the newest ones may be missing. We&apos;re looking into it.</Message>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <KpiCard label="Sales" value={money(s.revenue.current)} metric={s.revenue} days={days} />
        <KpiCard label="Orders" value={formatCompact(s.orders.current)} metric={s.orders} days={days} />
        <KpiCard label="Average order" value={money(s.average_order_value.current)} metric={s.average_order_value} days={days} />
        {s.traffic ? (
          <>
            <KpiCard label="Visitors who buy" value={formatPercent(s.traffic.conversion_rate.current)} metric={s.traffic.conversion_rate} days={days} />
            <KpiCard label="Sales per website visit" value={money(s.traffic.revenue_per_session.current)} metric={s.traffic.revenue_per_session} days={days} />
          </>
        ) : (
          <KpiCard label="Units sold" value={formatCompact(s.units.current)} metric={s.units} days={days} />
        )}
      </div>
      {s.traffic && (
        <p className="mt-2 text-xs text-muted">
          &ldquo;Visitors who buy&rdquo; = orders placed on your online store ÷ website visits ({formatNumber(s.traffic.sessions.current)} visits in this period).
        </p>
      )}
      {!s.traffic && <p className="mt-2 text-xs text-muted">Website visits aren&apos;t available right now, so visitor-based numbers are hidden.</p>}

      <Card className="mt-6">
        <CardHeader
          title="Sales per day"
          subtitle={`Store: ${s.shop_name}${s.last_synced_at ? ` · updated ${timeAgo(s.last_synced_at)}` : ""}${s.refunded > 0 ? ` · ${money(s.refunded)} refunded in this period` : ""}`}
        />
        <RevenueChart data={s.daily} currency={s.currency} />
      </Card>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Best sellers" subtitle="By sales" />
          {s.top_products.length === 0 ? (
            <EmptyState message="No orders in this period." />
          ) : (
            <DataTable
              rows={s.top_products}
              rowKey={(p) => p.title}
              columns={[
                { header: "Product", cell: (p) => <span className="break-words">{p.title}</span> },
                { header: "Sold", align: "right", cell: (p) => formatNumber(p.units) },
                { header: "Sales", align: "right", cell: (p) => money(p.revenue) },
              ]}
            />
          )}
        </Card>

        <Card className="lg:col-span-1">
          <CardHeader title="Latest orders" />
          <Async query={orders} skeleton={<SkeletonRows rows={6} />}>
            {() =>
              orders.items.length === 0 ? (
                <EmptyState message="No orders yet." />
              ) : (
                <>
                  <DataTable
                    rows={orders.items}
                    rowKey={(o) => o.id}
                    columns={[
                      { header: "Order", cell: (o) => <span className="font-medium">{o.name}</span> },
                      { header: "Placed", className: "hidden sm:table-cell", cell: (o) => <span className="whitespace-nowrap">{formatDateTime(o.created_at)}</span> },
                      { header: "Status", cell: (o) => <OrderStatus order={o} /> },
                      { header: "Total", align: "right", cell: (o) => formatShopMoney(o.total, o.currency) },
                    ]}
                  />
                  <LoadMore hasMore={orders.hasMore} loading={orders.loadingMore} error={orders.moreError} onClick={orders.loadMore} />
                </>
              )
            }
          </Async>
        </Card>
      </div>
    </>
  );
}

function OrderStatus({ order }: { order: ShopOrderRow }) {
  if (order.cancelled) return <Badge tone="red">Cancelled</Badge>;
  if (order.is_test) return <Badge tone="gray">Test</Badge>;
  const paid = (order.financial_status ?? "").toUpperCase();
  if (paid === "PAID") return <Badge tone="green">Paid</Badge>;
  if (paid === "REFUNDED" || paid === "PARTIALLY_REFUNDED") return <Badge tone="amber">Refunded</Badge>;
  return <Badge tone="gray">{paid ? paid.charAt(0) + paid.slice(1).toLowerCase().replace(/_/g, " ") : "Unknown"}</Badge>;
}
