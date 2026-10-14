"use client";

import {
  Bar,
  BarChart,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";

import { formatNumber } from "@/lib/format";

export interface BarDatum {
  name: string;
  value: number;
}

const ROW_HEIGHT = 34;

/**
 * Horizontal bar chart for "top N" breakdowns (browsers, channels, ...).
 * The value is written at the end of each bar, so nobody has to hover to read it.
 */
export function HBarChart({
  data,
  valueLabel,
  maxRows = 8,
}: {
  data: BarDatum[];
  valueLabel: string; // e.g. "Visitors", shown in the hover box
  maxRows?: number;
}) {
  const rows = data.slice(0, maxRows);
  if (rows.length === 0) return <p className="px-4 pb-6 pt-2 text-sm text-muted sm:px-5">No data in this period.</p>;

  return (
    <div className="px-2 pb-3 sm:px-3">
      <ResponsiveContainer width="100%" height={rows.length * ROW_HEIGHT + 8}>
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 56, bottom: 4, left: 4 }}>
          <XAxis type="number" hide domain={[0, "dataMax"]} />
          <YAxis
            type="category"
            dataKey="name"
            width={120}
            interval={0}
            tickLine={false}
            axisLine={{ stroke: "var(--axis)" }}
            tick={{ fill: "var(--ink-2)", fontSize: 12 }}
            tickFormatter={truncate}
          />
          <Tooltip
            cursor={{ fill: "var(--surface-2)" }}
            content={(props: TooltipContentProps) => <BarTooltip {...props} valueLabel={valueLabel} />}
          />
          <Bar
            dataKey="value"
            fill="var(--series-1)"
            radius={[0, 4, 4, 0]} // rounded at the value end, square at the baseline
            barSize={18}
            activeBar={{ fillOpacity: 0.8 }}
            isAnimationActive={false}
          >
            <LabelList
              dataKey="value"
              position="right"
              formatter={(v) => formatNumber(Number(v))}
              style={{ fill: "var(--ink-2)", fontSize: 12 }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function truncate(name: string): string {
  return name.length > 16 ? `${name.slice(0, 15)}…` : name;
}

function BarTooltip({ active, payload, valueLabel }: TooltipContentProps & { valueLabel: string }) {
  if (!active || !payload?.length) return null;
  const datum = payload[0].payload as BarDatum;
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="mb-0.5 max-w-64 break-words text-muted">{datum.name}</p>
      <p>
        <span className="font-semibold tabular-nums text-ink">{formatNumber(datum.value)}</span>{" "}
        <span className="text-ink-2">{valueLabel}</span>
      </p>
    </div>
  );
}
