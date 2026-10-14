import type { Metric } from "@/lib/types";

/**
 * One KPI tile: label, big value, and the change vs the previous period.
 * The change shows an arrow + text (not just a color), and is green when the
 * change is GOOD - for bounce rate that means going DOWN.
 */
export function KpiCard({
  label,
  value,
  metric,
  days,
  goodWhen = "up",
}: {
  label: string;
  value: string;
  metric: Metric;
  days: number;
  goodWhen?: "up" | "down";
}) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-xs font-medium text-ink-2">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      <Delta metric={metric} days={days} goodWhen={goodWhen} />
    </div>
  );
}

function Delta({ metric, days, goodWhen }: { metric: Metric; days: number; goodWhen: "up" | "down" }) {
  const pct = metric.change_pct;
  if (pct === null) {
    return <p className="mt-1 text-xs text-muted">No data for the {days} days before</p>;
  }
  if (pct === 0) {
    return <p className="mt-1 text-xs text-muted">No change vs previous {days} days</p>;
  }
  const up = pct > 0;
  const good = up === (goodWhen === "up");
  return (
    <p className="mt-1 text-xs">
      <span className={`font-medium ${good ? "text-good" : "text-bad"}`}>
        <span aria-hidden="true">{up ? "▲" : "▼"}</span> {up ? "+" : ""}
        {pct}%
      </span>{" "}
      <span className="text-muted">vs previous {days} days</span>
    </p>
  );
}
