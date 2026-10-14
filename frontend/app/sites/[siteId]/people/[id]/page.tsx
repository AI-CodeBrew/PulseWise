"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Card, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { eventLabel } from "@/lib/events";
import { formatDateTime } from "@/lib/format";
import type { PersonDetail } from "@/lib/types";

// The most useful properties, shown first with friendly names.
const KEY_PROPERTIES: [string, string][] = [
  ["email", "Email"],
  ["name", "Name"],
  ["$geoip_city_name", "City"],
  ["$geoip_country_name", "Country"],
  ["$os", "Operating system"],
  ["$browser", "Browser"],
  ["$device_type", "Device"],
  ["$initial_referring_domain", "First came from"],
  ["$initial_utm_source", "First campaign"],
  ["$initial_pathname", "First page"],
];

/** PostHog writes "$direct" when there was no referrer. */
function showValue(value: unknown): string {
  return value === "$direct" ? "Direct (no referrer)" : String(value);
}

export default function PersonDetailPage() {
  const api = useSiteApi();
  const { id } = useParams<{ id: string }>();
  const siteHref = useSiteHref();
  const person = useApi<PersonDetail>(api(`/persons/${encodeURIComponent(id)}`));

  return (
    <>
      <Link href={siteHref("/people")} className="mb-3 inline-block text-sm text-accent hover:underline">
        ← All people
      </Link>

      <Async
        query={person}
        skeleton={
          <>
            <Skeleton className="mb-6 h-12 w-72" />
            <Skeleton className="h-40 rounded-xl" />
          </>
        }
      >
        {(p) => {
          const shown = KEY_PROPERTIES.filter(([key]) => p.properties[key] !== undefined);
          return (
            <>
              <PageHeader
                title={p.name}
                description={`${p.is_identified ? "Identified visitor" : "Anonymous visitor"} · first seen ${formatDateTime(p.created_at)}`}
              />

              <div className="grid gap-6 lg:grid-cols-5">
                <Card className="lg:col-span-2">
                  <CardHeader title="Details" />
                  {shown.length === 0 ? (
                    <EmptyState message="No details known about this person." />
                  ) : (
                    <dl className="px-4 pb-4 text-sm sm:px-5">
                      {shown.map(([key, label]) => (
                        <div key={key} className="flex justify-between gap-4 border-t border-line py-2">
                          <dt className="text-muted">{label}</dt>
                          <dd className="break-all text-right text-ink">{showValue(p.properties[key])}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                  {/* Everything else, folded away */}
                  <details className="border-t border-line px-4 py-3 text-sm sm:px-5">
                    <summary className="cursor-pointer text-ink-2">All properties ({Object.keys(p.properties).length})</summary>
                    <dl className="mt-2 space-y-1 text-xs">
                      {Object.entries(p.properties)
                        .sort(([a], [b]) => a.localeCompare(b))
                        .map(([key, value]) => (
                          <div key={key} className="flex justify-between gap-4">
                            <dt className="font-mono text-muted">{key}</dt>
                            <dd className="break-all text-right text-ink-2">
                              {typeof value === "object" ? JSON.stringify(value) : String(value)}
                            </dd>
                          </div>
                        ))}
                    </dl>
                  </details>
                </Card>

                <Card className="lg:col-span-3">
                  <CardHeader title="Recent activity" subtitle="Latest 100 events" />
                  {p.events.length === 0 ? (
                    <EmptyState message="No recent events." />
                  ) : (
                    <ul className="px-4 pb-4 sm:px-5">
                      {p.events.map((e) => (
                        <li key={e.id} className="flex items-baseline justify-between gap-3 border-t border-line py-2 text-sm">
                          <div className="min-w-0">
                            <span className="text-ink">{eventLabel(e.event)}</span>
                            {e.path && <span className="ml-2 break-all text-ink-2">{e.path}</span>}
                          </div>
                          <div className="shrink-0 text-right text-xs text-muted">
                            {e.session_id ? (
                              <Link href={siteHref(`/sessions/${e.session_id}`)} className="hover:text-accent hover:underline">
                                {formatDateTime(e.timestamp)}
                              </Link>
                            ) : (
                              formatDateTime(e.timestamp)
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
            </>
          );
        }}
      </Async>
    </>
  );
}
