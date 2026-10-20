"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipContentProps } from "recharts";

import { formatCompact, formatDay, formatDuration } from "@/lib/format";
import { formatTileValue } from "@/lib/tiles";
import type { TileKind } from "@/lib/types";
import { ViewToggle } from "./TrendChart";

const AXIS_TICK = { fill: "var(--muted)", fontSize: 12 };

function axisText(kind: TileKind, value: number): string {
  if (kind === "percent") return `${value}%`;
  if (kind === "duration") return formatDuration(value);
  if (kind === "decimal") return String(value);
  return formatCompact(value);
}

/** One number per day as a single line (one measure, one axis), with a "Table" view of the same numbers. */
export function DailyChart({ points, kind, label }: { points: { date: string; value: number }[]; kind: TileKind; label: string }) {
  const [view, setView] = useState<"chart" | "table">("chart");

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2">
        <p className="flex items-center gap-1.5 text-xs text-ink-2">
          <span className="h-0.5 w-4 rounded-full" style={{ background: "var(--series-1)" }} aria-hidden="true" />
          {label}
        </p>
        <ViewToggle value={view} onChange={setView} />
      </div>

      {view === "chart" ? (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis dataKey="date" tickFormatter={formatDay} tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={28} />
            <YAxis allowDecimals={kind !== "number"} tickFormatter={(v: number) => axisText(kind, v)} tick={AXIS_TICK} tickLine={false} axisLine={false} width={52} />
            <Tooltip content={(props) => <DayTooltip {...props} kind={kind} seriesLabel={label} />} cursor={{ stroke: "var(--axis)", strokeWidth: 1 }} />
            <Line
              type="linear"
              dataKey="value"
              stroke="var(--series-1)"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={false}
              activeDot={{ r: 4, fill: "var(--series-1)", stroke: "var(--surface)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="max-h-56 overflow-y-auto rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface text-xs text-muted">
              <tr>
                <th className="px-4 py-2 text-left font-medium">Day</th>
                <th className="px-4 py-2 text-right font-medium">{label}</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {[...points].reverse().map((p) => (
                <tr key={p.date} className="border-t border-line">
                  <td className="px-4 py-1.5">{formatDay(p.date)}</td>
                  <td className="px-4 py-1.5 text-right">{formatTileValue(kind, p.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function DayTooltip({ active, payload, label: day, kind, seriesLabel }: TooltipContentProps & { kind: TileKind; seriesLabel: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="mb-1 text-muted">{formatDay(String(day))}</p>
      <p>
        <span className="font-semibold tabular-nums text-ink">{formatTileValue(kind, Number(payload[0].value ?? 0))}</span>{" "}
        <span className="text-ink-2">{seriesLabel}</span>
      </p>
    </div>
  );
}
