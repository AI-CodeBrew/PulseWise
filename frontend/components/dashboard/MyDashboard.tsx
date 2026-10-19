"use client";

// "My dashboard" (the Dashboard page, right under Overview in the menu): small tiles with one big number each (like PostHog's dashboard tiles), 
// Each person chooses their own tiles. The first time, we ask which ones they want; after that we only show those.
// The choice is saved on the server per user and website (PUT /dashboard/prefs).

import { useState } from "react";

import { useAuth } from "@/components/auth/AuthProvider";
import { Card } from "@/components/ui/Card";
import { Button, Message, TextField, useAction } from "@/components/ui/Form";
import { Async, Skeleton } from "@/components/ui/States";
import { useApi } from "@/hooks/useApi";
import { useSiteApi } from "@/hooks/useSite";
import { apiPut } from "@/lib/api";
import { formatDuration, formatNumber } from "@/lib/format";
import type { MyTiles, TileCatalog, TileKind, TileValue } from "@/lib/types";

const DEFAULT_TILES = ["active_users_30d", "sessions_7d", "pageviews_7d"]; // ticked for you the first time
const eventKey = (name: string, days: 7 | 30) => `event:${name}:${days}`;

export function formatTileValue(kind: TileKind, value: number | string): string {
  if (typeof value === "string") return value;
  if (kind === "percent") return `${value}%`;
  if (kind === "duration") return formatDuration(value);
  if (kind === "decimal") return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return formatNumber(value);
}

export function MyDashboard() {
  const api = useSiteApi();
  const { me } = useAuth();
  const tiles = useApi<MyTiles>(api("/dashboard/tiles"));
  const [customizing, setCustomizing] = useState(false);
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
              <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
                {!readOnly && !customizing && (
                  <Button variant="secondary" onClick={() => setCustomizing(true)}>
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
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                  {data.tiles.map((tile) => (
                    <Tile key={tile.key} tile={tile} readOnly={readOnly} onRemove={() => removeTile(keys, tile.key, reload)} />
                  ))}
                </div>
              )}
            </>
          );
        }}
      </Async>
    </section>
  );

  function removeTile(keys: string[], key: string, done: () => void) {
    void apiPut(api("/dashboard/prefs"), { tiles: keys.filter((k) => k !== key) }).then(done);
  }
}

function TileSkeletons() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 3 }, (_, i) => (
        <Skeleton key={i} className="h-40 rounded-lg" />
      ))}
    </div>
  );
}

/** One tile: title with an (i) for the explanation, a "…" menu, and the big number. */
function Tile({ tile, readOnly, onRemove }: { tile: TileValue; readOnly: boolean; onRemove: () => void }) {
  const text = formatTileValue(tile.kind, tile.value);
  return (
    <div className="flex min-h-40 flex-col overflow-hidden rounded-lg border border-line bg-surface" data-tile={tile.key}>
      <div className="flex items-start justify-between gap-2 border-b border-line px-3 py-3">
        <div className="min-w-0 border-l-4 border-accent pl-3">
          <h3 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
            <span className="min-w-0 break-words">{tile.title}</span>
            <span title={tile.description} aria-label={tile.description} role="img" className="cursor-help text-xs font-normal text-muted">
              ⓘ
            </span>
          </h3>
          <p className="mt-1 text-xs text-ink-2">{tile.description}</p>
        </div>
        {!readOnly && (
          <details className="relative shrink-0">
            <summary aria-label={`Options for ${tile.title}`} className="cursor-pointer list-none rounded-md px-2 py-0.5 text-lg leading-none text-ink-2 hover:bg-surface-2">
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
      <div className="grid flex-1 place-items-center px-3 py-5">
        <p className={`text-center font-semibold tracking-tight text-ink ${typeof tile.value === "string" ? "break-all text-xl" : "text-5xl"}`} aria-label={`${tile.title}: ${text}`}>
          {text}
        </p>
      </div>
    </div>
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
  const toggle = (key: string) => setChosen((c) => (c.includes(key) ? c.filter((k) => k !== key) : [...c, key]));

  return (
    <Card>
      <div className="px-4 pt-4 sm:px-5">
        <h2 className="text-base font-semibold text-ink">{firstTime ? "Choose what you want to see on your dashboard" : "Customize your dashboard"}</h2>
        <p className="mt-1 text-sm text-ink-2">
          Tick the numbers you care about. {firstTime ? "You can change this any time with the Customize button." : "Untick the ones you don't need."}
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
                          <input type="checkbox" checked={chosen.includes(t.key)} onChange={() => toggle(t.key)} className="mt-0.5 h-4 w-4 accent-[var(--accent)]" />
                          <span>
                            <span className="font-medium text-ink">{t.title}</span>
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
                        <li key={e.event} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-sm">
                          <span className="min-w-0">
                            <span className="break-all font-medium text-ink">{e.event}</span>
                            <span className="ms-2 text-xs text-muted">{formatNumber(e.count)} in the last 30 days</span>
                          </span>
                          <span className="flex gap-4">
                            {([7, 30] as const).map((days) => (
                              <label key={days} className="flex items-center gap-1.5 text-ink-2">
                                <input
                                  type="checkbox"
                                  checked={chosen.includes(eventKey(e.event, days))}
                                  onChange={() => toggle(eventKey(e.event, days))}
                                  aria-label={`${e.event}, last ${days} days`}
                                  className="h-4 w-4 accent-[var(--accent)]"
                                />
                                {days} days
                              </label>
                            ))}
                          </span>
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
