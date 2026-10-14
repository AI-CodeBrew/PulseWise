"use client";

import { usePathname, useRouter } from "next/navigation";

import { useAuth } from "@/components/auth/AuthProvider";
import { ClientLogo } from "./ClientLogo";
import { useDays, withDays } from "@/hooks/useDays";
import { useCurrentSite } from "@/hooks/useSite";
import { useLogoVersion } from "@/hooks/useLogoVersion";
import type { WebsiteSummary } from "@/lib/types";

/** Dropdown to switch between the websites this user can see (just a name if there's one). */
export function WebsiteSwitcher() {
  const { me } = useAuth();
  const site = useCurrentSite();
  const router = useRouter();
  const pathname = usePathname();
  const days = useDays();
  const websites = me?.websites ?? [];
  const logoVersion = useLogoVersion();

  if (!site) return null;
  const logo = site.client_has_logo ? <ClientLogo clientId={site.client_id} version={logoVersion} /> : null;

  if (websites.length <= 1) {
    return (
      <div className="flex min-w-0 items-center gap-2">
        {logo}
        <p className="min-w-0 truncate text-sm font-medium text-ink">{site.name}</p>
      </div>
    );
  }

  function switchTo(websiteId: string) {
    // Stay on the same section (e.g. /sessions) but drop detail ids like a session id:
    // they belong to the old website. Path: /sites/<id>/<section>/<detail>
    const section = pathname.split("/")[3];
    router.push(withDays(`/sites/${websiteId}${section ? `/${section}` : ""}`, days));
  }

  // Group by client when the user (e.g. an admin) sees several clients' websites.
  const groups = new Map<string, WebsiteSummary[]>();
  for (const w of websites) groups.set(w.client_name, [...(groups.get(w.client_name) ?? []), w]);

  return (
    <label className="flex min-w-0 items-center gap-2">
      {logo}
      <span className="sr-only">Website</span>
      <select
        value={site.id}
        onChange={(e) => switchTo(e.target.value)}
        className="w-full max-w-64 truncate rounded-lg border border-line bg-surface py-1.5 pl-2.5 pr-8 text-sm font-medium text-ink"
      >
        {groups.size > 1
          ? [...groups].map(([clientName, sites]) => (
              <optgroup key={clientName} label={clientName}>
                {sites.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </optgroup>
            ))
          : websites.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
      </select>
    </label>
  );
}
