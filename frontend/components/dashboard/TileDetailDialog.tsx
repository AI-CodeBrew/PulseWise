"use client";

// The box that opens when a dashboard tile is clicked: the full story behind one number.
//
//   top      the number again, its period, and a "Watch recordings" button
//   trend    the number day by day
//   ranked   a few breakdowns ("which pages", "which countries"...)
//   latest   the latest visits or events behind the number, each with a Watch button when that visit was recorded
//
// It is a native <dialog>: the browser itself keeps the focus inside, closes it with Esc, and dims the page.
// The first part (trend + breakdowns) and the second (latest rows) are two requests, so neither waits for the other.

import Link from "next/link";
import { useEffect, useId, useRef } from "react";

import { BarList } from "@/components/charts/BarList";
import { DailyChart } from "@/components/charts/DailyChart";
import { DataTable } from "@/components/ui/DataTable";
import { Async, EmptyState, Skeleton, SkeletonRows } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { withDays } from "@/hooks/useDays";
import { useSiteApi, useSiteId } from "@/hooks/useSite";
import { formatDateTime, formatDay, formatDuration } from "@/lib/format";
import { formatTileValue } from "@/lib/tiles";
import type { Days, TileDetail, TileEventRow, TileRecent, TileValue, TileVisitRow } from "@/lib/types";

export function TileDetailDialog({ tile, onClose }: { tile: TileValue; onClose: () => void }) {
  const api = useSiteApi();
  const siteId = useSiteId();
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const detail = useApi<TileDetail>(api("/dashboard/tiles/detail"), { key: tile.key });
  const recent = useApi<TileRecent>(api("/dashboard/tiles/recent"), { key: tile.key });
  const days = tile.days as Days;
  const recordingsLocked = recent.data?.recordings.locked ?? null;

  // Open as a modal; keep the page behind from scrolling while it is open.
  // The cleanup must NOT close the box: while developing, React runs every effect twice (mount, clean up, mount again), and a
  // close() in the cleanup makes the browser report a "close" a moment AFTER the box was opened again, which closed it at once.
  // (Taking the <dialog> out of the page closes it by itself.)
  useEffect(() => {
    const box = dialog.current;
    if (!box) return;
    if (!box.open) box.showModal();
    const before = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = before;
    };
  }, []);

  const period = detail.data ? `${formatDay(detail.data.period.start)} – ${formatDay(detail.data.period.end)} · last ${days} days` : `Last ${days} days`;

  return (
    <dialog
      ref={dialog}
      aria-labelledby={titleId}
      onClose={(e) => {
        if (!e.currentTarget.open) onClose(); // (a late "close" report for a box that has been opened again since is not the person closing it)
      }}
      onClick={(e) => {
        if (e.target === dialog.current) dialog.current?.close(); // a click on the dimmed page behind the box
      }}
      className="m-auto w-[min(100%-1.5rem,60rem)] overflow-hidden rounded-xl border border-line bg-surface p-0 text-ink shadow-2xl backdrop:bg-black/50"
    >
      <div className="max-h-[90vh] overflow-y-auto" data-tile-detail={tile.key}>
        <header className="flex items-start justify-between gap-3 px-4 pb-3 pt-4 sm:px-5">
          <div className="min-w-0 border-l-4 border-accent pl-3">
            <h2 id={titleId} className="text-base font-semibold text-ink">
              {tile.title}
            </h2>
            <p className="mt-1 text-sm text-ink-2">{tile.description}</p>
          </div>
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            aria-label="Close"
            className="shrink-0 rounded-md px-2 py-1 text-lg leading-none text-ink-2 hover:bg-surface-2 hover:text-ink"
          >
            ✕
          </button>
        </header>

        <div className="flex flex-wrap items-end justify-between gap-3 border-y border-line bg-page px-4 py-4 sm:px-5">
          <div className="min-w-0">
            <p className={`font-semibold tracking-tight text-ink ${typeof tile.value === "string" ? "break-all text-2xl" : "text-5xl"}`}>{formatTileValue(tile.kind, tile.value)}</p>
            <p className="mt-1 text-xs text-muted">{period}</p>
          </div>
          {recordingsLocked ? (
            <p className="max-w-xs text-xs text-ink-2">
              <span aria-hidden="true">🔒 </span>
              {recordingsLocked}
            </p>
          ) : (
            <Link
              href={withDays(`/sites/${siteId}/recordings`, days)}
              className="inline-flex items-center gap-2 rounded-lg bg-accent px-3.5 py-2 text-sm font-medium text-white hover:opacity-90"
            >
              <span aria-hidden="true">▶</span> Watch recordings
            </Link>
          )}
        </div>

        <div className="space-y-6 px-4 py-5 sm:px-5">
          <Async query={detail} skeleton={<Skeleton className="h-64 rounded-lg" />}>
            {(d) => (
              <>
                <section aria-label="Trend">
                  <h3 className="mb-2 text-sm font-semibold text-ink">Day by day</h3>
                  <DailyChart points={d.series.points} kind={d.series.kind} label={d.series.label} />
                </section>
                <div className="grid gap-6 md:grid-cols-2">
                  {d.breakdowns.map((b) => (
                    <section key={b.key} aria-label={b.title}>
                      <h3 className="mb-2 flex items-baseline justify-between gap-2 text-sm font-semibold text-ink">
                        {b.title}
                        <span className="text-xs font-normal text-muted">{b.unit}</span>
                      </h3>
                      <BarList rows={b.rows} kind={b.kind} unit={b.unit} />
                    </section>
                  ))}
                </div>
              </>
            )}
          </Async>

          <Async query={recent} skeleton={<SkeletonRows rows={4} />}>{(r) => <Latest recent={r} siteId={siteId} days={days} />}</Async>
        </div>
      </div>
    </dialog>
  );
}

// ------------------------------------------------------------------ the latest visits / events

function Latest({ recent, siteId, days }: { recent: TileRecent; siteId: string; days: Days }) {
  const watch = (sessionId: string | null, has: boolean | null) => <WatchCell siteId={siteId} days={days} sessionId={sessionId} has={has} />;
  return (
    <section aria-label={recent.title}>
      <h3 className="mb-2 text-sm font-semibold text-ink">{recent.title}</h3>
      {recent.locked ? (
        <p className="rounded-lg border border-line bg-page px-4 py-3 text-sm text-ink-2">
          <span aria-hidden="true">🔒 </span>
          {recent.locked}
        </p>
      ) : recent.rows.length === 0 ? (
        <div className="rounded-lg border border-line">
          <EmptyState message={recent.kind === "sessions" ? "No visits in this period." : "Nothing happened in this period."} />
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-line">
          {recent.kind === "sessions" ? (
            <DataTable
              rows={recent.rows as TileVisitRow[]}
              rowKey={(r) => r.session_id}
              columns={[
                { header: "Started", cell: (r) => <span className="whitespace-nowrap">{formatDateTime(r.started_at)}</span> },
                { header: "Visitor", className: "hidden sm:table-cell", cell: (r) => <span className="break-all text-xs">{r.visitor}</span> },
                { header: "Pages", align: "right", cell: (r) => r.pageviews },
                { header: "Length", align: "right", cell: (r) => formatDuration(r.duration) },
                { header: "Landed on", className: "hidden md:table-cell", cell: (r) => <span className="break-all">{r.entry_page}</span> },
                { header: "Recording", align: "right", cell: (r) => watch(r.session_id, r.has_recording) },
              ]}
            />
          ) : (
            <DataTable
              rows={recent.rows as TileEventRow[]}
              rowKey={(r) => r.id}
              columns={[
                { header: "When", cell: (r) => <span className="whitespace-nowrap">{formatDateTime(r.timestamp)}</span> },
                { header: "What happened", cell: (r) => <span className="break-words">{r.event}</span> },
                { header: "Page", className: "hidden md:table-cell", cell: (r) => <span className="break-all">{r.page}</span> },
                { header: "Visitor", className: "hidden sm:table-cell", cell: (r) => <span className="break-all text-xs">{r.visitor}</span> },
                { header: "Recording", align: "right", cell: (r) => watch(r.session_id, r.has_recording) },
              ]}
            />
          )}
        </div>
      )}
      {!recent.locked && recent.rows.length > 0 && recent.recordings.checked && (
        <p className="mt-2 text-xs text-muted">A Watch button appears when that visit was recorded.</p>
      )}
    </section>
  );
}

/** The recording button of one row: a link to the replay when the visit was recorded, a plain note when it wasn't. */
function WatchCell({ siteId, days, sessionId, has }: { siteId: string; days: Days; sessionId: string | null; has: boolean | null }) {
  if (has === null) return <span className="text-xs text-muted">—</span>; // plan without recordings, or we couldn't find out
  if (!has || !sessionId) return <span className="whitespace-nowrap text-xs text-muted">No recording</span>;
  return (
    <Link
      href={withDays(`/sites/${siteId}/recordings/${sessionId}`, days)}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-white hover:opacity-90"
    >
      <span aria-hidden="true">▶</span> Watch
    </Link>
  );
}
