// Shared helpers for the dashboard tiles and the box that opens when a tile is clicked.

import { formatDuration, formatNumber } from "./format";
import type { TileKind, TileValue } from "./types";

/** A tile's number as text: 612 -> "612", 17.2 (percent) -> "17.2%", 93 (duration) -> "1m 33s", text stays text. */
export function formatTileValue(kind: TileKind, value: number | string): string {
  if (typeof value === "string") return value;
  if (kind === "percent") return `${value}%`;
  if (kind === "duration") return formatDuration(value);
  if (kind === "decimal") return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return formatNumber(value);
}

/** The tile a saved key belongs to, without its period: "sessions_30d" -> "sessions", "event:form_submit:7" -> "event:form_submit". */
export function baseOf(key: string): string {
  return key.startsWith("event:") ? key.replace(/:(7|30)$/, "") : key.replace(/_(7|30)d$/, "");
}

/** How a tile compares with the period just before it. The arrow and the words say it, so it never depends on colour alone. */
export interface TileChange {
  arrow: "▲" | "▼" | "–";
  /** "12%", "3.5 pts", "was 0" or "no change" */
  text: string;
  /** What it was compared with, in words: "vs previous 7 days" */
  suffix: string;
  /** "good" = went the way that is good news (more visitors, or FEWER people leaving after one page) */
  tone: "good" | "bad" | "flat";
  /** For screen readers: "Up 12% compared with the previous 7 days" */
  spoken: string;
}

export function tileChange(tile: TileValue): TileChange | null {
  if (tile.empty || typeof tile.value !== "number" || tile.previous === null) return null;
  const difference = tile.value - tile.previous;
  const period = `the previous ${tile.days} days`;
  const same = (text: string): TileChange => ({ arrow: "–", text, suffix: `vs previous ${tile.days} days`, tone: "flat", spoken: `No change compared with ${period}` });
  let text: string;
  let suffix = `vs previous ${tile.days} days`;
  if (tile.kind === "percent") {
    // a share changes in percentage points ("3.5 pts"), not in percent of a percent
    text = `${Math.abs(difference).toFixed(1)} pts`;
    if (Math.abs(difference) < 0.05) return same("no change");
  } else if (tile.previous === 0) {
    if (tile.value === 0) return same("no change");
    text = "was 0"; // it grew from nothing: a percentage of zero means nothing, so say what it was
    suffix = `in ${period}`;
  } else {
    const percent = Math.abs(difference / tile.previous) * 100;
    if (percent < 0.5) return same("no change");
    text = `${percent < 10 ? percent.toFixed(1) : Math.round(percent)}%`;
  }
  const up = difference > 0;
  const good = up === (tile.better === "up");
  return {
    arrow: up ? "▲" : "▼",
    text,
    suffix,
    tone: good ? "good" : "bad",
    spoken: tile.previous === 0 ? `Up from 0 in ${period}` : `${up ? "Up" : "Down"} ${text} compared with ${period}`,
  };
}
