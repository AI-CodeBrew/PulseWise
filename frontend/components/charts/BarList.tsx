"use client";

import { formatTileValue } from "@/lib/tiles";
import type { TileKind } from "@/lib/types";

/**
 * A short ranked list with a thin bar behind each row ("top pages", "countries"...).
 * Names are shown in full (long page addresses wrap instead of being cut), and every number is written out.
 */
export function BarList({ rows, kind, unit }: { rows: { name: string; value: number }[]; kind: TileKind; unit: string }) {
  if (rows.length === 0) return <p className="py-2 text-sm text-muted">No data in this period.</p>;
  const largest = Math.max(...rows.map((r) => r.value), 1);
  return (
    <ul className="space-y-2.5">
      {rows.map((row, index) => (
        <li key={`${row.name}-${index}`} title={`${row.name}: ${formatTileValue(kind, row.value)} ${unit}`}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 break-all text-ink-2">{row.name}</span>
            <span className="shrink-0 font-medium tabular-nums text-ink">{formatTileValue(kind, row.value)}</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-surface-2" aria-hidden="true">
            <div className="h-full rounded-full" style={{ width: `${Math.max(2, (row.value / largest) * 100)}%`, background: "var(--series-1)" }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
