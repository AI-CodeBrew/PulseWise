"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { RecordingPlayer } from "@/components/recordings/RecordingPlayer";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Async, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useSiteApi, useSiteHref } from "@/hooks/useSite";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { RecordingDetail } from "@/lib/types";

export default function RecordingPage() {
  const { recId } = useParams<{ recId: string }>();
  const api = useSiteApi();
  const siteHref = useSiteHref();
  const detail = useApi<RecordingDetail>(api(`/recordings/${encodeURIComponent(recId)}`));

  return (
    <>
      <Link href={siteHref("/recordings")} className="mb-3 inline-block text-sm text-accent hover:underline">
        ← All recordings
      </Link>
      <PageHeader title="Recording" description="A replay of one visit. Quiet stretches are skipped automatically." />

      <Async query={detail} skeleton={<Skeleton className="h-96 rounded-xl" />}>
        {(r) => (
          <>
            <p className="mb-4 text-sm text-ink-2">
              {formatDateTime(r.start_time)} · {formatDuration(r.duration)} long ·{" "}
              <span className="break-all font-mono text-xs">{r.person}</span>
            </p>
            <Card>
              <RecordingPlayer eventsPath={api(`/recordings/${encodeURIComponent(recId)}/events`)} blocks={r.blocks} />
            </Card>
          </>
        )}
      </Async>
    </>
  );
}
