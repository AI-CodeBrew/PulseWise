// Formatting helpers so numbers, durations and dates look the same everywhere.

const numberFormat = new Intl.NumberFormat("en-US");
const compactFormat = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

/** 1234 -> "1,234" */
export function formatNumber(n: number): string {
  return numberFormat.format(n);
}

/** 1234 -> "1,234", 12900 -> "12.9K" (compact only for big numbers) */
export function formatCompact(n: number): string {
  return Math.abs(n) >= 10_000 ? compactFormat.format(n) : numberFormat.format(n);
}

/** 34.56 -> "34.6%" */
export function formatPercent(n: number): string {
  return `${n.toFixed(1)}%`;
}

/** Seconds -> "45s", "2m 14s", "1h 05m" */
export function formatDuration(totalSeconds: number): string {
  const s = Math.max(0, Math.round(totalSeconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}h ${String(m).padStart(2, "0")}m`;
}

/** "2026-10-10" -> "Oct 10" (a calendar day, no timezone shift) */
export function formatDay(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** "2026-10-10T12:35:40Z" -> "Oct 10, 5:35 PM" (in the viewer's timezone) */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Time of day with seconds: "5:35:40 PM" */
export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", second: "2-digit" });
}

/** "just now", "5 min ago", "3 h ago", "2 days ago" */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.round((now - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/** 12.5 -> "$12.50", 1234.5 -> "$1,234.50" */
export function formatUsd(n: number): string {
  return n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

/** "2026-10" -> "October 2026" */
export function formatMonth(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

/** Move a "YYYY-MM" month forwards or backwards. */
export function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split("-").map(Number);
  const d = new Date(y, m - 1 + by, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** 8000 PKR -> "Rs 8,000", 29 USD -> "$29.00", 2500.5 PKR -> "Rs 2,500.50" */
export function formatMoney(amount: number, currency: "PKR" | "USD"): string {
  if (currency === "USD") return amount.toLocaleString("en-US", { style: "currency", currency: "USD" });
  const whole = Number.isInteger(amount);
  return `Rs ${amount.toLocaleString("en-PK", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 })}`;
}

/** "2026-10-21" -> "21 Oct 2026" (a calendar day, no timezone shift) */
export function formatDate(isoDate: string): string {
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** Money in ANY currency (a Shopify store's own): 12500 + "PKR" -> "PKR 12,500". Falls back to plain text for odd codes. */
export function formatShopMoney(amount: number, currency: string | null | undefined): string {
  const code = (currency || "").toUpperCase();
  const digits = Number.isInteger(amount) ? 0 : 2;
  try {
    if (code) return amount.toLocaleString("en-US", { style: "currency", currency: code, minimumFractionDigits: digits, maximumFractionDigits: 2 });
  } catch {
    // not a currency code the browser knows: fall through
  }
  return `${code} ${amount.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: 2 })}`.trim();
}
