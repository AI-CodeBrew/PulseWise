import type { ReactNode } from "react";

/** Big title + one-line explanation at the top of every page. */
export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-ink sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-ink-2">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/** "Load more" button under paginated tables. */
export function LoadMore({
  hasMore,
  loading,
  error,
  onClick,
}: {
  hasMore: boolean;
  loading: boolean;
  error: string | null;
  onClick: () => void;
}) {
  if (!hasMore && !error) return null;
  return (
    <div className="flex flex-col items-center gap-2 border-t border-line px-4 py-3">
      {error && <p className="text-xs text-bad">{error}</p>}
      {hasMore && (
        <button
          type="button"
          onClick={onClick}
          disabled={loading}
          className="rounded-md border border-line bg-surface px-4 py-1.5 text-sm font-medium text-ink hover:bg-surface-2 disabled:opacity-60"
        >
          {loading ? "Loading…" : "Load more"}
        </button>
      )}
    </div>
  );
}
