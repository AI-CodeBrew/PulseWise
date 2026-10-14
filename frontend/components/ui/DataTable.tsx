"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  align?: "left" | "right";
  className?: string; // e.g. "hidden md:table-cell" to hide a column on phones
}

/**
 * A simple table. If `rowHref` is given, every row is clickable and the first
 * cell is a real link (so keyboard users can Tab to it).
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowHref,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  rowHref?: (row: T) => string;
}) {
  const router = useRouter();

  return (
    // Only the table scrolls sideways on small screens, never the whole page.
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-y border-line text-xs text-muted">
            {columns.map((col) => (
              <th
                key={col.header}
                scope="col"
                className={`px-4 py-2 font-medium first:pl-4 sm:first:pl-5 last:pr-4 sm:last:pr-5 ${
                  col.align === "right" ? "text-right" : "text-left"
                } ${col.className ?? ""}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const href = rowHref?.(row);
            return (
              <tr
                key={rowKey(row)}
                onClick={href ? () => router.push(href) : undefined}
                className={`border-b border-line last:border-b-0 ${href ? "cursor-pointer hover:bg-surface-2" : ""}`}
              >
                {columns.map((col, i) => (
                  <td
                    key={col.header}
                    className={`px-4 py-2.5 align-top first:pl-4 sm:first:pl-5 last:pr-4 sm:last:pr-5 ${
                      col.align === "right" ? "text-right tabular-nums" : "text-left"
                    } ${col.className ?? ""}`}
                  >
                    {i === 0 && href ? (
                      <Link href={href} className="hover:underline" onClick={(e) => e.stopPropagation()}>
                        {col.cell(row)}
                      </Link>
                    ) : (
                      col.cell(row)
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** A thin bar inside a table cell showing a value relative to the largest one. */
export function ShareBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="mt-1 h-1 w-full max-w-48 rounded-full bg-surface-2" aria-hidden="true">
      <div className="h-1 rounded-full bg-accent" style={{ width: `${pct}%` }} />
    </div>
  );
}
