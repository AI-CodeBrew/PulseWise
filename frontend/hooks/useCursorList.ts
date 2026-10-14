"use client";

import { useState } from "react";

import { ApiError, apiGet, type QueryParams } from "@/lib/api";
import type { Paged } from "@/lib/types";
import { useApi, type ApiState } from "./useApi";

interface ExtraPages<T> {
  baseKey: string; // which list (path + params) these pages belong to
  items: T[];
  cursor: string | null;
}

export interface CursorListState<T> extends ApiState<Paged<T>> {
  items: T[]; // first page + every "load more" page
  hasMore: boolean;
  loadMore: () => void;
  loadingMore: boolean;
  moreError: string | null;
}

/**
 * A paginated list with a "Load more" button.
 *
 * The backend returns `next_cursor`; sending it back as `?cursor=` returns the next
 * page. (PostHog doesn't allow page numbers with our kind of API key.)
 * When the params change (e.g. a new date range), the list starts over.
 */
export function useCursorList<T>(path: string, params: QueryParams): CursorListState<T> {
  const first = useApi<Paged<T>>(path, params);
  const baseKey = `${path}|${JSON.stringify(params)}`;

  const [extra, setExtra] = useState<ExtraPages<T> | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [moreError, setMoreError] = useState<string | null>(null);

  // Extra pages only count if they belong to the current list and the first page is fresh.
  const extraValid = extra !== null && extra.baseKey === baseKey && !first.loading;
  const items = [...(first.data?.results ?? []), ...(extraValid ? extra.items : [])];
  const nextCursor = extraValid ? extra.cursor : (first.data?.next_cursor ?? null);

  async function loadMore() {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    setMoreError(null);
    try {
      const page = await apiGet<Paged<T>>(path, { ...params, cursor: nextCursor });
      setExtra((prev) => ({
        baseKey,
        items: [...(prev && prev.baseKey === baseKey ? prev.items : []), ...page.results],
        cursor: page.next_cursor,
      }));
    } catch (err) {
      setMoreError(err instanceof ApiError ? err.message : "Could not load more.");
    } finally {
      setLoadingMore(false);
    }
  }

  return {
    ...first,
    reload: () => {
      setExtra(null);
      first.reload();
    },
    items,
    hasMore: Boolean(nextCursor),
    loadMore,
    loadingMore,
    moreError,
  };
}
