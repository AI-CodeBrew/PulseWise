"use client";

import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import { formatCompact, formatDay, formatNumber } from "@/lib/format";
import type { TrendPoint } from "@/lib/types";

// Two series on ONE axis (both are counts). Colors come from the CSS tokens in globals.css.
const SERIES = [
  { key: "visitors", label: "Visitors", color: "var(--series-1)" },
  { key: "pageviews", label: "Pageviews", color: "var(--series-2)" },
] as const;

const AXIS_TICK = { fill: "var(--muted)", fontSize: 12 };

/** Daily visitors + pageviews line chart, with a "Table" view of the same numbers. */
export function TrendChart({ data }: { data: TrendPoint[] }) {
  const [view, setView] = useState<"chart" | "table">("chart");

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-2 sm:px-5">
        {/* Legend: a short line in the series color + the name in normal text color */}
        <ul className="flex gap-4 text-xs text-ink-2">
          {SERIES.map((s) => (
            <li key={s.key} className="flex items-center gap-1.5">
              <span className="h-0.5 w-4 rounded-full" style={{ background: s.color }} aria-hidden="true" />
              {s.label}
            </li>
          ))}
        </ul>
        <ViewToggle value={view} onChange={setView} />
      </div>

      {view === "chart" ? (
        <div className="px-2 pb-3 sm:px-3">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis
                dataKey="date"
                tickFormatter={formatDay}
                tick={AXIS_TICK}
                tickLine={false}
                axisLine={{ stroke: "var(--axis)" }}
                minTickGap={28}
              />
              <YAxis
                allowDecimals={false}
                tickFormatter={formatCompact}
                tick={AXIS_TICK}
                tickLine={false}
                axisLine={false}
                width={44}
              />
              <Tooltip content={TrendTooltip} cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} />
              {SERIES.map((s) => (
                <Line
                  key={s.key}
                  type="linear"
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  dot={false}
                  activeDot={{ r: 4, fill: s.color, stroke: "var(--surface)", strokeWidth: 2 }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="max-h-[276px] overflow-y-auto border-t border-line">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr>
                <th className="px-5 py-2 text-left font-medium">Day</th>
                <th className="px-5 py-2 text-right font-medium">Visitors</th>
                <th className="px-5 py-2 text-right font-medium">Pageviews</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {[...data].reverse().map((d) => (
                <tr key={d.date} className="border-t border-line">
                  <td className="px-5 py-1.5">{formatDay(d.date)}</td>
                  <td className="px-5 py-1.5 text-right">{formatNumber(d.visitors)}</td>
                  <td className="px-5 py-1.5 text-right">{formatNumber(d.pageviews)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Hover box: the date, then every series' value (value first, name second). */
function TrendTooltip({ active, payload, label }: TooltipContentProps) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="mb-1 text-muted">{formatDay(String(label))}</p>
      {SERIES.map((s) => {
        const item = payload.find((p) => p.dataKey === s.key);
        return (
          <div key={s.key} className="flex items-center gap-2 py-0.5">
            <span className="h-0.5 w-3 rounded-full" style={{ background: s.color }} aria-hidden="true" />
            <span className="font-semibold tabular-nums text-ink">{formatNumber(Number(item?.value ?? 0))}</span>
            <span className="text-ink-2">{s.label}</span>
          </div>
        );
      })}
    </div>
  );
}

export function ViewToggle({ value, onChange }: { value: "chart" | "table"; onChange: (v: "chart" | "table") => void }) {
  return (
    <div className="inline-flex rounded-md border border-line p-0.5 text-xs" role="group" aria-label="View as">
      {(["chart", "table"] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={`rounded px-2 py-0.5 capitalize ${
            value === v ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink"
          }`}
        >
          {v}
        </button>
      ))}
    </div>
  );
}
