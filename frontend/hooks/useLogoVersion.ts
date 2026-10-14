"use client";

import { useSyncExternalStore } from "react";

// A tiny shared counter: the Settings page bumps it after a logo upload/removal,
// and the top bar (which shows the logo) re-renders with a fresh picture URL.
let version = 0;
const listeners = new Set<() => void>();

export function bumpLogoVersion() {
  version = Date.now();
  listeners.forEach((l) => l());
}

export function useLogoVersion(): number {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => version,
    () => 0,
  );
}
