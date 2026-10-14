"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import type { Days } from "@/lib/types";

export const DAY_OPTIONS: Days[] = [7, 30, 90];
const DEFAULT_DAYS: Days = 30;

/**
 * The selected date range lives in the URL (?days=30), so it:
 *  - applies to every page (links keep it, see useSiteHref),
 *  - survives a page refresh,
 *  - can be shared as a link.
 */
export function useDays(): Days {
  const searchParams = useSearchParams();
  const value = Number(searchParams.get("days"));
  return (DAY_OPTIONS as number[]).includes(value) ? (value as Days) : DEFAULT_DAYS;
}

/** Add ?days= to a link (left out for the default, to keep URLs short). */
export function withDays(path: string, days: Days): string {
  return days === DEFAULT_DAYS ? path : `${path}?days=${days}`;
}

/** Change the date range for the current page. */
export function useSetDays(): (days: Days) => void {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  return (days: Days) => {
    const params = new URLSearchParams(searchParams.toString());
    if (days === DEFAULT_DAYS) params.delete("days");
    else params.set("days", String(days));
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };
}
