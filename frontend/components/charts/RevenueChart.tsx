"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from "recharts";

import { formatCompact, formatDay, formatNumber, formatShopMoney } from "@/lib/format";
import type { SalesDay } from "@/lib/types";
import { ViewToggle } from "./TrendChart";

const AXIS_TICK = { fill: "var(--muted)", fontSize: 12 };

/** Sales per day as bars (one measure, one axis), with a "Table" view of the same numbers (orders and visits too). */
export function RevenueChart({ data, currency }: { data: SalesDay[]; currency: string | null }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const hasSessions = data.some((d) => d.sessions !== undefined);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-2 sm:px-5">
        <p className="flex items-center gap-1.5 text-xs text-ink-2">
          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--series-1)" }} aria-hidden="true" />
          Sales per day
        </p>
        <ViewToggle value={view} onChange={setView} />
      </div>

      {view === "chart" ? (
        <div className="px-2 pb-3 sm:px-3">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis dataKey="date" tickFormatter={formatDay} tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={28} />
              <YAxis tickFormatter={formatCompact} tick={AXIS_TICK} tickLine={false} axisLine={false} width={52} />
              <Tooltip content={(props) => <SalesTooltip {...props} currency={currency} />} cursor={{ fill: "var(--surface-2)" }} />
              <Bar dataKey="revenue" name="Sales" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={28} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="max-h-[276px] overflow-y-auto border-t border-line">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr>
                <th className="px-5 py-2 text-left font-medium">Day</th>
                <th className="px-5 py-2 text-right font-medium">Orders</th>
                <th className="px-5 py-2 text-right font-medium">Sales</th>
                {hasSessions && <th className="px-5 py-2 text-right font-medium">Website visits</th>}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {[...data].reverse().map((d) => (
                <tr key={d.date} className="border-t border-line">
                  <td className="px-5 py-1.5">{formatDay(d.date)}</td>
                  <td className="px-5 py-1.5 text-right">{formatNumber(d.orders)}</td>
                  <td className="px-5 py-1.5 text-right">{formatShopMoney(d.revenue, currency)}</td>
                  {hasSessions && <td className="px-5 py-1.5 text-right">{formatNumber(d.sessions ?? 0)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SalesTooltip({ active, payload, label, currency }: TooltipContentProps & { currency: string | null }) {
  if (!active || !payload?.length) return null;
  const day = payload[0].payload as SalesDay;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="mb-1 text-muted">{formatDay(String(label))}</p>
      <p>
        <span className="font-semibold tabular-nums text-ink">{formatShopMoney(day.revenue, currency)}</span> <span className="text-ink-2">sales</span>
      </p>
      <p>
        <span className="font-semibold tabular-nums text-ink">{formatNumber(day.orders)}</span> <span className="text-ink-2">{day.orders === 1 ? "order" : "orders"}</span>
      </p>
    </div>
  );
}
