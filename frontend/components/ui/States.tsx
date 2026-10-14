"use client";

import type { ReactNode } from "react";

import type { ApiState } from "@/hooks/useApi";
import { LockedState } from "./Locked";

/** A grey placeholder block shown while data loads for the first time. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-surface-2 ${className}`} aria-hidden="true" />;
}

/** Placeholder rows for tables and lists. */
export function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3 px-4 pb-4 sm:px-5" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-5 w-full" />
      ))}
    </div>
  );
}

/** Friendly error box with a "Try again" button. */
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="mx-4 mb-4 mt-3 rounded-lg bg-bad-soft px-4 py-3 text-sm sm:mx-5">
      <p className="font-medium text-ink">Couldn&apos;t load this</p>
      <p className="mt-0.5 text-ink-2">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-md border border-line bg-surface px-3 py-1 text-xs font-medium text-ink hover:bg-surface-2"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/** Shown when a request worked but there is nothing to display. */
export function EmptyState({ message }: { message: string }) {
  return <p className="px-4 pb-6 pt-2 text-sm text-muted sm:px-5">{message}</p>;
}

/**
 * Handles the three states of a request in one place:
 *   error   -> ErrorState with retry
 *   no data -> the skeleton you pass in
 *   data    -> your content (dimmed while newer data is loading)
 */
export function Async<T>({
  query,
  skeleton,
  children,
}: {
  query: ApiState<T>;
  skeleton: ReactNode;
  children: (data: T) => ReactNode;
}) {
  // 403 = "your plan doesn't include this" (or the account is paused): explain it instead of offering "Try again".
  if (query.error?.status === 403) return <LockedState message={query.error.message} />;
  if (query.error) return <ErrorState message={query.error.message} onRetry={query.reload} />;
  if (query.data === null) return <>{skeleton}</>;
  return (
    <div aria-busy={query.loading} className={`transition-opacity ${query.loading ? "opacity-50" : ""}`}>
      {children(query.data)}
    </div>
  );
}
