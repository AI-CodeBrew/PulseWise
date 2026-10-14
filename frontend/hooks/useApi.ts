"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, apiGet, type QueryParams } from "@/lib/api";

export interface ApiState<T> {
  data: T | null; // last successful response (kept while a new one loads)
  error: ApiError | null;
  loading: boolean; // true while a request is in flight
  reload: () => void;
}

interface Result<T> {
  key: string | null; // which request this result belongs to
  data: T | null;
  error: ApiError | null;
}

/**
 * Fetch a backend endpoint and re-fetch whenever `path` or `params` change.
 *
 * - While new data loads, the OLD data stays on screen (shown dimmed by <Async>),
 *   so changing the date range doesn't flash empty skeletons.
 * - `refreshMs` re-fetches on a timer (used by the live feed). It pauses while
 *   the browser tab is hidden, so we don't spend queries nobody sees.
 * - Pass `path = null` to skip fetching.
 */
export function useApi<T>(
  path: string | null,
  params?: QueryParams,
  options?: { refreshMs?: number; paused?: boolean },
): ApiState<T> {
  const [tick, setTick] = useState(0); // bump to re-fetch
  const [result, setResult] = useState<Result<T>>({ key: null, data: null, error: null });

  const paramsKey = JSON.stringify(params ?? {});
  const requestKey = path ? `${path}|${paramsKey}|${tick}` : null;

  useEffect(() => {
    if (!path || !requestKey) return;
    const controller = new AbortController();
    apiGet<T>(path, JSON.parse(paramsKey) as QueryParams, controller.signal)
      .then((data) => setResult({ key: requestKey, data, error: null }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return; // superseded by a newer request
        const error = err instanceof ApiError ? err : new ApiError(0, "Something went wrong. Please try again.");
        setResult({ key: requestKey, data: null, error });
      });
    // Cancel the request if the inputs change or the component unmounts.
    return () => controller.abort();
  }, [path, paramsKey, requestKey]);

  // Optional auto-refresh.
  const refreshMs = options?.refreshMs;
  const paused = options?.paused;
  useEffect(() => {
    if (!refreshMs || paused) return;
    const id = setInterval(() => {
      if (!document.hidden) setTick((t) => t + 1);
    }, refreshMs);
    return () => clearInterval(id);
  }, [refreshMs, paused]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  return {
    data: result.data,
    error: result.key === requestKey ? result.error : null,
    loading: requestKey !== null && result.key !== requestKey,
    reload,
  };
}
