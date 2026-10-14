"use client";

import { API_URL } from "@/lib/api";

/**
 * The client's own logo (if they uploaded one), fetched from our backend.
 * `version` changes after an upload so the browser doesn't show the old picture from its cache.
 */
export function ClientLogo({ clientId, version = 0, className = "h-8 w-8" }: { clientId: string; version?: number; className?: string }) {
  return (
    // A plain <img>: the picture comes from our API with the login cookie, so next/image can't optimise it.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`${API_URL}/api/clients/${clientId}/logo?v=${version}`}
      alt=""
      className={`shrink-0 rounded-md bg-surface-2 object-contain ${className}`}
    />
  );
}
