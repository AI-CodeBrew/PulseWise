"use client";

// "My dashboard" (the Dashboard page, right under Overview in the menu): small tiles with one big number each (like PostHog's dashboard tiles), 
// Each person chooses their own tiles. The first time, we ask which ones they want; after that we only show those.
// The choice is saved on the server per user and website (PUT /dashboard/prefs).

import { useEffect, useId, useRef, useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Sparkline } from "@/components/charts/Sparkline";
import { Card } from "@/components/ui/Card";
import { Button, Message, TextField, useAction } from "@/components/ui/Form";
import { Async, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useSiteApi } from "@/hooks/useSite";
import { apiPut } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { baseOf, formatTileValue, tileChange } from "@/lib/tiles";
import type { MyTiles, TileCatalog, TileValue } from "@/lib/types";
import { TileDetailDialog } from "./TileDetailDialog";

const DEFAULT_TILES = ["active_users_30d", "sessions_7d", "pageviews_7d"]; // ticked for you the first time

export function MyDashboard() {
  const api = useSiteApi();
  const { me } = useAuth();
  const tiles = useApi<MyTiles>(api("/dashboard/tiles"));
  const [customizing, setCustomizing] = useState(false);
  // The tile whose box is open. Each opening gets its own number: a browser reports a box's closing a moment LATER,
  // and that late report must never close a box that was opened in the meantime.
  const [opened, setOpened] = useState<{ tile: TileValue; id: number } | null>(null);
  const openings = useRef(0);
  const readOnly = Boolean(me?.view_as); // an admin looking "as the client" can't change the client's choices

  const reload = () => {
    setCustomizing(false);
    tiles.reload();
  };

  return (
    <section aria-label="My dashboard" className="mb-8">
      <Async query={tiles} skeleton={<TileSkeletons />}>
        {(data) => {
          if (!data.configured) {
            if (readOnly) return null; // (nothing to show, and nothing they may choose)
            return <TilePicker firstTime selected={DEFAULT_TILES} onSaved={reload} />;
          }
          const keys = data.tiles.map((t) => t.key);
          return (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {!customizing && data.tiles.length > 0 && <p className="text-xs text-muted">Click a tile for the full story behind its number.</p>}
                {!readOnly && !customizing && (
                  <Button variant="secondary" className="ml-auto" onClick={() => setCustomizing(true)}>
                    Customize
                  </Button>
                )}
              </div>
              {customizing ? (
                <TilePicker selected={keys} onSaved={reload} onCancel={() => setCustomizing(false)} />
              ) : data.tiles.length === 0 ? (
                <Card className="px-4 py-6 text-center text-sm text-ink-2">
                  No tiles yet. {!readOnly && "Press Customize to add some."}
                </Card>
              ) : (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-4">
                  {data.tiles.map((tile) => (
                    <Tile
                      key={tile.base ?? tile.key}
                      tile={tile}
                      readOnly={readOnly}
                      onOpen={() => setOpened({ tile, id: ++openings.current })}
                      onRemove={() => save(keys.filter((k) => k !== tile.key))}
                      onPeriod={(days) => {
                        const other = tile.period_keys?.[String(days)];
                        if (other) save(keys.map((k) => (k === tile.key ? other : k)));
                      }}
                    />
                  ))}
                </div>
              )}
            </>
          );
        }}
      </Async>
      {opened && <TileDetailDialog key={opened.id} tile={opened.tile} onClose={() => setOpened((now) => (now?.id === opened.id ? null : now))} />}
    </section>
  );

  /** Save the changed list (a tile removed, or a tile switched to the other period), then show the new numbers. */
  function save(next: string[]) {
    void apiPut(api("/dashboard/prefs"), { tiles: next })
      .catch(() => undefined) // (if it failed, the reload below simply shows what is really saved)
      .then(() => tiles.reload());
  }
}

function TileSkeletons() {
  return (
    <div className="grid grid-cols-[repeat(auto-fill,minmax(16rem,1fr))] gap-4">
      {Array.from({ length: 4 }, (_, i) => (
        <Skeleton key={i} className="h-36 rounded-xl" />
      ))}
    </div>
  );
}

/**
 * One tile, built like a KPI card: its name (the (i) explains it), the period, a "..." menu, the big number, how it compares
 * with the period before, and a little graph of the days. The whole card is a button that opens the box with the full story
 * (the "..." menu and the (i) stay usable). Every part has a fixed place, so the numbers of one row line up.
 */
function Tile({
  tile,
  readOnly,
  onOpen,
  onRemove,
  onPeriod,
}: {
  tile: TileValue;
  readOnly: boolean;
  onOpen: () => void;
  onRemove: () => void;
  onPeriod: (days: number) => void;
}) {
  const isText = typeof tile.value === "string";
  const text = tile.empty && !isText ? "—" : formatTileValue(tile.kind, tile.value);
  const quiet = tile.empty || tile.value === 0; // nothing to see yet: a calm colour instead of a headline
  const change = tileChange(tile);
  const nothingHappened = tile.value === 0 && tile.previous === 0;
  const tone = { good: "text-good", bad: "text-bad", flat: "text-muted" };
  return (
    <div
      className="group relative flex min-h-36 flex-col gap-3 rounded-xl border border-line bg-surface p-4 transition-shadow hover:border-accent/60 hover:shadow-md"
      data-tile={tile.key}
    >
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Open details: ${tile.title}`}
        className="absolute inset-0 z-0 cursor-pointer rounded-xl focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
      />
      <div className="pointer-events-none relative z-[1] flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-0.5">
          <h3 className="truncate text-sm font-medium text-ink-2">{tile.label}</h3>
          <InfoTip name={tile.label} text={tile.description} />
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <PeriodSwitch tile={tile} readOnly={readOnly} onPick={onPeriod} />
          {!readOnly && (
            <details className="pointer-events-auto relative z-[2] opacity-60 transition-opacity group-hover:opacity-100 open:opacity-100 focus-within:opacity-100">
              <summary aria-label={`Options for ${tile.title}`} className="cursor-pointer list-none rounded-md px-1.5 text-lg leading-6 text-ink-2 hover:bg-surface-2">
                …
              </summary>
              <div className="absolute right-0 z-10 mt-1 w-48 rounded-lg border border-line bg-surface p-1 shadow-lg">
                <button type="button" onClick={onRemove} className="block w-full rounded-md px-3 py-1.5 text-left text-sm text-ink hover:bg-surface-2">
                  Remove from dashboard
                </button>
              </div>
            </details>
          )}
        </div>
      </div>
      <div className="pointer-events-none relative z-[1] mt-auto flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="flex min-h-10 items-center">
            <p
              className={`font-semibold tabular-nums tracking-tight ${quiet ? "text-muted" : "text-ink"} ${isText ? "line-clamp-2 break-all text-xl leading-7" : "text-4xl leading-10"}`}
              aria-label={`${tile.title}: ${text}`}
            >
              {text}
            </p>
          </div>
          <p className="mt-1 min-h-4 text-xs">
            {tile.empty && !isText ? (
              <span className="text-muted">No visits in the last {tile.days} days</span>
            ) : nothingHappened ? (
              <span className="text-muted">Nothing recorded in the last {tile.days} days</span>
            ) : change ? (
              <>
                <span className={`font-medium ${tone[change.tone]}`}>
                  <span aria-hidden="true">{change.arrow}</span> {change.text}
                </span>{" "}
                <span className="text-muted">{change.suffix}</span>
                <span className="sr-only">. {change.spoken}</span>
              </>
            ) : null}
          </p>
        </div>
        {tile.series && !tile.empty && <Sparkline values={tile.series} className="h-9 w-24 shrink-0" />}
      </div>
    </div>
  );
}

/**
 * "7d | 30d": the period a tile shows. One tile, switched here (never one tile per period); the choice is saved with the tile.
 * Somebody who only looks (an admin viewing as the client) sees the period, without the switch.
 */
function PeriodSwitch({ tile, readOnly, onPick }: { tile: TileValue; readOnly: boolean; onPick: (days: number) => void }) {
  const periods = Object.keys(tile.period_keys ?? {}).map(Number).sort((a, b) => a - b);
  if (readOnly || periods.length === 0) {
    return (
      <span title={`Last ${tile.days} days`} className="rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-ink-2">
        {tile.days}d
      </span>
    );
  }
  return (
    <div role="group" aria-label={`Period of ${tile.label}`} className="pointer-events-auto inline-flex rounded-full bg-surface-2 p-0.5 text-[11px] font-medium">
      {periods.map((days) => (
        <button
          key={days}
          type="button"
          aria-pressed={tile.days === days}
          aria-label={`Last ${days} days`}
          title={`Last ${days} days`}
          onClick={() => tile.days !== days && onPick(days)}
          className={`rounded-full px-2 py-0.5 ${tile.days === days ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}
        >
          {days}d
        </button>
      ))}
    </div>
  );
}

/**
 * The little (i) next to a tile's name: what the number means, in plain words.
 * A mouse pointer shows it while it rests on the (i). A click (or a tap, phones have no hover) PINS it open: it then stays
 * until the next click on the (i), a click anywhere else, or Esc. (Without the pin, a click on a hover-opened tip closed it.)
 */
function InfoTip({ name, text }: { name: string; text: string }) {
  const [hovered, setHovered] = useState(false);
  const [pinned, setPinned] = useState(false);
  const open = hovered || pinned;
  const box = useRef<HTMLSpanElement>(null);
  const id = useId();

  useEffect(() => {
    if (!pinned) return;
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setPinned(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [pinned]);

  return (
    <span
      ref={box}
      className="pointer-events-auto relative shrink-0"
      onPointerEnter={(event) => event.pointerType === "mouse" && setHovered(true)}
      onPointerLeave={(event) => event.pointerType === "mouse" && setHovered(false)}
    >
      <button
        type="button"
        aria-label={`What is “${name}”?`}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setPinned((now) => !now)}
        onBlur={() => setPinned(false)} // (tabbing away closes it, too)
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setPinned(false);
            setHovered(false);
          }
        }}
        className="grid h-5 w-5 place-items-center rounded-full text-xs text-muted hover:bg-surface-2 hover:text-ink focus-visible:outline-2 focus-visible:outline-accent"
      >
        ⓘ
      </button>
      {open && (
        <span id={id} role="tooltip" className="absolute left-0 top-full z-30 mt-1 w-60 rounded-lg border border-line bg-surface p-2.5 text-xs leading-relaxed text-ink-2 shadow-lg">
          {text}
        </span>
      )}
    </span>
  );
}

/** Choose the tiles. Shown first thing for someone who never chose, and behind "Customize" afterwards. */
function TilePicker({ selected, firstTime = false, onSaved, onCancel }: { selected: string[]; firstTime?: boolean; onSaved: () => void; onCancel?: () => void }) {
  const api = useSiteApi();
  const catalog = useApi<TileCatalog>(api("/dashboard/tiles/catalog"));
  const [chosen, setChosen] = useState<string[]>(selected);
  const [search, setSearch] = useState("");
  const save = useAction(async () => {
    await apiPut(api("/dashboard/prefs"), { tiles: chosen });
    onSaved();
  });
  // ONE tile per thing: "Sessions" on 7 days and "Sessions" on 30 days are the same tile (its period is switched on the card).
  const isChosen = (base: string) => chosen.some((k) => baseOf(k) === base);
  const toggle = (base: string, startKey: string) => setChosen((c) => (isChosen(base) ? c.filter((k) => baseOf(k) !== base) : [...c, startKey]));

  return (
    <Card>
      <div className="px-4 pt-4 sm:px-5">
        <h2 className="text-base font-semibold text-ink">{firstTime ? "Choose what you want to see on your dashboard" : "Customize your dashboard"}</h2>
        <p className="mt-1 text-sm text-ink-2">
          Tick the numbers you care about. Every number can show the last 7 or the last 30 days: you switch that on the number itself.{" "}
          {firstTime ? "You can change all this any time with the Customize button." : "Untick the ones you don't need."}
        </p>
      </div>
      <Async query={catalog} skeleton={<Skeleton className="m-5 h-40" />}>
        {(c) => {
          const groups = [...new Set(c.tiles.map((t) => t.group))];
          const events = c.events.filter((e) => e.event.toLowerCase().includes(search.trim().toLowerCase()));
          return (
            <div className="space-y-5 px-4 py-4 sm:px-5">
              {groups.map((group) => (
                <fieldset key={group}>
                  <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{group}</legend>
                  <div className="grid gap-2 sm:grid-cols-2">
                    {c.tiles
                      .filter((t) => t.group === group)
                      .map((t) => (
                        <label key={t.key} className="flex cursor-pointer items-start gap-2 rounded-lg border border-line p-2.5 text-sm hover:bg-surface-2">
                          <input type="checkbox" checked={isChosen(baseOf(t.key))} onChange={() => toggle(baseOf(t.key), t.key)} className="mt-0.5 h-4 w-4 accent-[var(--accent)]" />
                          <span>
                            <span className="font-medium text-ink">{t.label ?? t.title}</span>
                            <span className="block text-xs text-ink-2">{t.description}</span>
                          </span>
                        </label>
                      ))}
                  </div>
                </fieldset>
              ))}

              <fieldset>
                <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted">Your tracked events</legend>
                {c.events.length === 0 ? (
                  <p className="text-sm text-ink-2">Your website hasn&apos;t sent any events of its own yet (clicks on buttons, sign-ups and so on). They will show up here.</p>
                ) : (
                  <>
                    {c.events.length > 8 && (
                      <div className="mb-2 max-w-xs">
                        <TextField label="Find an event" value={search} onChange={(e) => setSearch(e.target.value)} />
                      </div>
                    )}
                    <ul className="divide-y divide-line rounded-lg border border-line">
                      {events.map((e) => (
                        <li key={e.event}>
                          <label className="flex cursor-pointer flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-surface-2">
                            <span className="min-w-0">
                              <span className="break-all font-medium text-ink">{e.event}</span>
                              <span className="ms-2 text-xs text-muted">{formatNumber(e.count)} in the last 30 days</span>
                            </span>
                            <input
                              type="checkbox"
                              checked={isChosen(`event:${e.event}`)}
                              onChange={() => toggle(`event:${e.event}`, e.key ?? `event:${e.event}:30`)}
                              aria-label={e.event}
                              className="h-4 w-4 accent-[var(--accent)]"
                            />
                          </label>
                        </li>
                      ))}
                      {events.length === 0 && <li className="px-3 py-2 text-sm text-muted">No event matches.</li>}
                    </ul>
                  </>
                )}
              </fieldset>
            </div>
          );
        }}
      </Async>
      <div className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-3 sm:px-5">
        <Button variant="primary" busy={save.busy} onClick={() => save.run()}>
          {firstTime ? "Show my dashboard" : "Save"}
        </Button>
        {onCancel && (
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <span className="text-xs text-muted">{chosen.length} chosen</span>
      </div>
      {save.error && (
        <div className="px-4 pb-4 sm:px-5">
          <Message kind="error">{save.error}</Message>
        </div>
      )}
    </Card>
  );
}
