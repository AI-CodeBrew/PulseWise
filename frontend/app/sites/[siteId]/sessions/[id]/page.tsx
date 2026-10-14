"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Card, CardHeader } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, EmptyState, Skeleton, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { eventKind, eventLabel } from "@/lib/events";
import { formatDateTime, formatDuration, formatTime } from "@/lib/format";
import type { SessionDetail, SessionEvent } from "@/lib/types";

export default function SessionDetailPage() {
  const api = useSiteApi();
  const { id } = useParams<{ id: string }>();
  const siteHref = useSiteHref();
  const detail = useApi<SessionDetail>(api(`/sessions/${encodeURIComponent(id)}`));

  return (
    <>
      <Link href={siteHref("/sessions")} className="mb-3 inline-block text-sm text-accent hover:underline">
        ← All sessions
      </Link>
      <PageHeader title="Session" description="Everything this visitor did, in order." />

      <Async
        query={detail}
        skeleton={
          <>
            <Skeleton className="h-24 rounded-xl" />
            <Card className="mt-6 pt-4">
              <SkeletonRows rows={8} />
            </Card>
          </>
        }
      >
        {(d) => (
          <>
            {d.session && (
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-4">
                <Fact label="Started" value={formatDateTime(d.session.started_at)} />
                <Fact label="Length" value={formatDuration(d.session.duration)} />
                <Fact label="Pages viewed" value={String(d.session.pageviews)} />
                <Fact
                  label="Came from"
                  value={
                    d.session.referrer === d.session.channel
                      ? d.session.channel
                      : `${d.session.channel} · ${d.session.referrer}`
                  }
                />
                <Fact label="Entry page" value={d.session.entry_page} />
                <Fact label="Exit page" value={d.session.exit_page} />
                <Fact label="Bounced" value={d.session.is_bounce ? "Yes (one page only)" : "No"} />
                <Fact label="Events" value={String(d.events.length)} />
              </dl>
            )}

            <Card className="mt-6">
              <CardHeader title="Timeline" subtitle="Time is shown in your timezone" />
              {d.events.length === 0 ? (
                <EmptyState message="No events recorded for this session." />
              ) : (
                <Timeline events={d.events} />
              )}
            </Card>
          </>
        )}
      </Async>
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface px-4 py-3">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 break-all text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}

const DOT: Record<ReturnType<typeof eventKind>, string> = {
  page: "bg-accent",
  error: "bg-bad",
  custom: "bg-ink-2",
  other: "bg-surface-2 ring-1 ring-line",
};

/** Vertical list of events with "+2m 10s" offsets from the start of the session. */
function Timeline({ events }: { events: SessionEvent[] }) {
  const start = new Date(events[0].timestamp).getTime();
  return (
    <ol className="px-4 pb-4 sm:px-5">
      {events.map((e, i) => {
        const offset = (new Date(e.timestamp).getTime() - start) / 1000;
        const kind = eventKind(e.event);
        return (
          <li key={e.id} className="relative flex gap-3 pb-3">
            {/* the vertical line connecting the dots */}
            {i < events.length - 1 && <span className="absolute left-[5px] top-4 h-full w-px bg-line" aria-hidden="true" />}
            <span className={`relative mt-1.5 h-[11px] w-[11px] shrink-0 rounded-full ${DOT[kind]}`} aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-ink">
                <span className={kind === "page" || kind === "error" ? "font-medium" : ""}>{eventLabel(e.event)}</span>
                {kind === "error" && <span className="ml-2 text-xs text-bad">error</span>}
                {e.path && <span className="ml-2 break-all text-ink-2">{e.path}</span>}
              </p>
              <p className="text-xs text-muted tabular-nums">
                {formatTime(e.timestamp)} · +{formatDuration(offset)}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
