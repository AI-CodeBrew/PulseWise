"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from "recharts";

import { formatCompact, formatDay, formatNumber } from "@/lib/format";
import type { UsagePoint } from "@/lib/types";

const AXIS_TICK = { fill: "var(--muted)", fontSize: 12 };

/** Events per day for one website (one series, so no legend: the card title says what it is). */
export function UsageChart({ data }: { data: UsagePoint[] }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const total = data.reduce((sum, p) => sum + p.events, 0);

  return (
    <div>
      <div className="flex items-center justify-between px-4 pb-2 sm:px-5">
        <p className="text-sm text-ink-2">
          <span className="font-semibold text-ink">{formatNumber(total)}</span> events in {data.length} days
        </p>
        <div className="inline-flex rounded-md border border-line p-0.5 text-xs" role="group" aria-label="View as">
          {(["chart", "table"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={view === v}
              onClick={() => setView(v)}
              className={`rounded px-2 py-0.5 capitalize ${view === v ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink"}`}
            >
              {v}
            </button>
          ))}
        </div>
      </div>
      {view === "chart" ? (
        <div className="px-2 pb-3 sm:px-3">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis dataKey="date" tickFormatter={formatDay} tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={28} />
              <YAxis allowDecimals={false} tickFormatter={formatCompact} tick={AXIS_TICK} tickLine={false} axisLine={false} width={44} />
              <Tooltip cursor={{ fill: "var(--surface-2)" }} content={(props: TooltipContentProps) => <UsageTooltip {...props} />} />
              <Bar dataKey="events" fill="var(--series-1)" radius={[4, 4, 0, 0]} maxBarSize={24} isAnimationActive={false} activeBar={{ fillOpacity: 0.8 }} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="max-h-60 overflow-y-auto border-t border-line">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr>
                <th className="px-5 py-2 text-left font-medium">Day</th>
                <th className="px-5 py-2 text-right font-medium">Events</th>
                <th className="px-5 py-2 text-right font-medium">Pageviews</th>
                <th className="px-5 py-2 text-right font-medium">Recordings</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {[...data].reverse().map((p) => (
                <tr key={p.date} className="border-t border-line">
                  <td className="px-5 py-1.5">{formatDay(p.date)}</td>
                  <td className="px-5 py-1.5 text-right">{formatNumber(p.events)}</td>
                  <td className="px-5 py-1.5 text-right">{formatNumber(p.pageviews)}</td>
                  <td className="px-5 py-1.5 text-right">{formatNumber(p.recordings)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function UsageTooltip({ active, payload, label }: TooltipContentProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="mb-1 text-muted">{formatDay(String(label))}</p>
      <p>
        <span className="font-semibold tabular-nums text-ink">{formatNumber(Number(payload[0].value ?? 0))}</span> <span className="text-ink-2">events</span>
      </p>
    </div>
  );
}
