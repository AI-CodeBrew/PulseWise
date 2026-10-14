"use client";

import { DAY_OPTIONS, useDays, useSetDays } from "@/hooks/useDays";

/** "7 days | 30 days | 90 days" switch. Changes ?days= in the URL for every page. */
export function DateRangeSelector() {
  const days = useDays();
  const setDays = useSetDays();

  return (
    <div role="group" aria-label="Date range" className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm">
      {DAY_OPTIONS.map((d) => (
        <button
          key={d}
          type="button"
          aria-pressed={days === d}
          aria-label={`Last ${d} days`}
          onClick={() => setDays(d)}
          className={`rounded-md px-2 py-1 sm:px-3 ${
            days === d ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:text-ink"
          }`}
        >
          {/* short labels on phones, so the website switcher has room */}
          <span className="sm:hidden">{d}d</span>
          <span className="hidden sm:inline">{d} days</span>
        </button>
      ))}
    </div>
  );
}
