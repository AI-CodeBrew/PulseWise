"use client";

import { useParams } from "next/navigation";
import { useCallback } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import type { WebsiteSummary } from "@/lib/types";
import { useDays, withDays } from "./useDays";

/** The website id from the URL: /sites/<siteId>/... */
export function useSiteId(): string {
  const { siteId } = useParams<{ siteId: string }>();
  return siteId;
}

/** The current website (name, client, role), or null if the user can't see it. */
export function useCurrentSite(): WebsiteSummary | null {
  const siteId = useSiteId();
  const { me } = useAuth();
  return me?.websites.find((w) => w.id === siteId) ?? null;
}

/** Backend URL for the current website: api("/overview") -> "/api/websites/<id>/overview" */
export function useSiteApi(): (path: string) => string {
  const siteId = useSiteId();
  return useCallback((path: string) => `/api/websites/${siteId}${path}`, [siteId]);
}

/** Dashboard link for the current website, keeping the date range:
 *  siteHref("/pages") -> "/sites/<id>/pages?days=7" */
export function useSiteHref(): (path?: string) => string {
  const siteId = useSiteId();
  const days = useDays();
  return useCallback((path = "") => withDays(`/sites/${siteId}${path}`, days), [siteId, days]);
}

// Remember the last website, so "/" opens it next time. (Per browser; may be unavailable.)
const LAST_SITE_KEY = "lastSiteId";

export function rememberSite(siteId: string) {
  try {
    localStorage.setItem(LAST_SITE_KEY, siteId);
  } catch {
    // private mode / storage blocked: not important
  }
}

export function lastSite(): string | null {
  try {
    return localStorage.getItem(LAST_SITE_KEY);
  } catch {
    return null;
  }
}
