// A tiny line with no axes or labels: the shape of the last days at a glance (used on the dashboard tiles).
// It is decorative on purpose: the number and the change next to it already say the same in words.

const WIDTH = 96;
const HEIGHT = 36;
const PAD = 3;

export function Sparkline({ values, className = "" }: { values: number[]; className?: string }) {
  if (values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const flat = max === min; // all days equal (often all zero): a plain line in the middle, in a quiet colour
  const x = (index: number) => PAD + (index / (values.length - 1)) * (WIDTH - 2 * PAD);
  const y = (value: number) => (flat ? HEIGHT / 2 : PAD + (1 - (value - min) / (max - min)) * (HEIGHT - 2 * PAD));
  const points = values.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`);
  const line = `M${points.join(" L")}`;
  const last = values.length - 1;

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className={className} aria-hidden="true" focusable="false">
      {!flat && <path d={`${line} L${x(last).toFixed(1)},${HEIGHT} L${x(0).toFixed(1)},${HEIGHT} Z`} fill="var(--accent-soft)" />}
      <path d={line} fill="none" stroke={flat ? "var(--axis)" : "var(--series-1)"} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      {!flat && <circle cx={x(last)} cy={y(values[last])} r="2.5" fill="var(--series-1)" stroke="var(--surface)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />}
    </svg>
  );
}
