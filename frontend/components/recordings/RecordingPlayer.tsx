"use client";

// Plays a session recording inside our own dashboard (no PostHog login, no PostHog branding).
//
// How it works:
//   1. The backend gives us the list of data "blocks" of the recording.
//   2. We download the blocks (3 per request, 3 requests at a time) with a progress bar.
//      The backend unpacks PostHog's compression, so we receive plain "rrweb" events.
//   3. The `rrweb-player` library rebuilds the visitor's page from those events and replays
//      every mouse move, click and scroll, skipping the idle stretches.

import "rrweb-player/dist/style.css";

import type RRWebPlayer from "rrweb-player";
import { useEffect, useRef, useState } from "react";

import { ErrorState } from "@/components/ui/States";
import { ApiError, apiGet } from "@/lib/api";
import type { RecordingBlock } from "@/lib/types";

// rrweb events are plain objects: { type, timestamp, data }. type 2 = full page snapshot, 4 = page size.
type RrwebEvent = { type: number; timestamp: number; data: unknown };

const BLOCKS_PER_REQUEST = 3; // the backend allows up to 4
const PARALLEL_REQUESTS = 3; // PostHog allows 3 queries at once per project
const MAX_BLOCKS = 150; // refuse absurdly long recordings instead of freezing the browser

// Rules added to the replayed page. A replay has no JavaScript, so anything a page's scripts used to reveal stays hidden.
// Shopify themes (Dawn and every theme built on it) fade/slide their sections in with `animate--*` classes, and the
// recording stores that animation rule broken (the browser can't write `animation: var(--x)` back out as text), so
// products, banners and whole sections would stay almost invisible (opacity .01). Show them in their final state.
const REPLAY_STYLE_RULES = [
  ".scroll-trigger.animate--fade-in, .scroll-trigger.animate--slide-in, .scroll-trigger.animate--zoom-in, .scroll-trigger.animate--ambient { opacity: 1 !important; transform: none !important; animation: none !important; }",
];

type Phase = { name: "loading"; done: number; total: number } | { name: "ready" } | { name: "error"; message: string };

export function RecordingPlayer({ eventsPath, blocks }: { eventsPath: string; blocks: RecordingBlock[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>({ name: "loading", done: 0, total: blocks.length });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const controller = new AbortController();
    let player: RRWebPlayer | null = null;

    async function run(target: HTMLDivElement) {
      if (blocks.length === 0) return setPhase({ name: "error", message: "This recording has no data (it may have expired)." });
      if (blocks.length > MAX_BLOCKS) return setPhase({ name: "error", message: "This recording is too long to play in the browser." });
      setPhase({ name: "loading", done: 0, total: blocks.length });

      // --- 1. Download all blocks, a few at a time
      const keys = blocks.map((b) => b.key).sort((a, b) => a - b);
      const groups: [number, number][] = [];
      for (let i = 0; i < keys.length; i += BLOCKS_PER_REQUEST) {
        const group = keys.slice(i, i + BLOCKS_PER_REQUEST);
        groups.push([group[0], group[group.length - 1]]);
      }
      const results: RrwebEvent[][] = new Array(groups.length);
      let nextGroup = 0;
      let blocksDone = 0;
      async function worker() {
        while (nextGroup < groups.length) {
          const index = nextGroup++;
          const [start, end] = groups[index];
          const response = await apiGet<{ events: RrwebEvent[] }>(eventsPath, { start, end }, controller.signal);
          results[index] = response.events;
          blocksDone += end - start + 1;
          setPhase({ name: "loading", done: Math.min(blocksDone, blocks.length), total: blocks.length });
        }
      }
      await Promise.all(Array.from({ length: Math.min(PARALLEL_REQUESTS, groups.length) }, worker));
      if (controller.signal.aborted) return;

      const events = results.flat().sort((a, b) => a.timestamp - b.timestamp);
      if (!events.some((e) => e.type === 2) || events.length < 2) {
        return setPhase({ name: "error", message: "This recording can't be played (it has no page snapshot)." });
      }

      // --- 2. Start the player, sized to the recorded window
      const meta = events.find((e) => e.type === 4)?.data as { width?: number; height?: number } | undefined;
      const recordedWidth = meta?.width || 1280;
      const recordedHeight = meta?.height || 720;
      const width = Math.max(320, Math.min(target.clientWidth, 1200));
      const height = Math.round(Math.min((width * recordedHeight) / recordedWidth, window.innerHeight * 0.7));

      const { default: Player } = await import("rrweb-player");
      if (controller.signal.aborted) return;
      target.innerHTML = "";
      player = new Player({
        target,
        props: {
          events: events as never, // our events match rrweb's eventWithTime shape
          width,
          height,
          autoPlay: false,
          skipInactive: true, // jump over the stretches where the visitor did nothing
          speedOption: [1, 2, 4, 8],
          showController: true,
          insertStyleRules: REPLAY_STYLE_RULES,
        },
      });
      setPhase({ name: "ready" });
    }

    run(container).catch((err: unknown) => {
      if (controller.signal.aborted) return;
      setPhase({
        name: "error",
        message: err instanceof ApiError ? err.message : "Something went wrong while loading the recording.",
      });
    });

    return () => {
      controller.abort();
      // $destroy() is a Svelte method that rrweb-player's bundled types don't declare.
      (player as unknown as { $destroy?: () => void } | null)?.$destroy?.();
      container.innerHTML = "";
    };
  }, [eventsPath, blocks, attempt]);

  return (
    <div>
      {phase.name === "loading" && (
        <div className="px-5 py-10 text-center" role="status">
          <p className="text-sm text-ink-2">
            Loading recording… {phase.total > 0 ? Math.round((phase.done / phase.total) * 100) : 0}%
          </p>
          <div className="mx-auto mt-3 h-1.5 w-64 max-w-full overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full rounded-full bg-accent transition-all"
              style={{ width: `${phase.total > 0 ? (phase.done / phase.total) * 100 : 0}%` }}
            />
          </div>
          {phase.total > 20 && <p className="mt-3 text-xs text-muted">This one is long, so it takes a little while.</p>}
        </div>
      )}
      {phase.name === "error" && (
        <div className="pt-3">
          <ErrorState message={phase.message} onRetry={() => setAttempt((n) => n + 1)} />
        </div>
      )}
      {/* The player draws itself in here. Kept mounted so we can measure its width. */}
      <div ref={containerRef} className={`flex justify-center ${phase.name === "ready" ? "pb-4" : "h-0 overflow-hidden"}`} />
    </div>
  );
}
