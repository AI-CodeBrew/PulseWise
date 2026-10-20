"use client";

import { useEffect, useState } from "react";

/** The value, but only once it has stopped changing for `ms` milliseconds (so typing doesn't send a request per key press). */
export function useDebounced<T>(value: T, ms = 400): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}
