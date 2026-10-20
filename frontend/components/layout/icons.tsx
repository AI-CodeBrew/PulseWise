// Small line icons for the sidebar and the form buttons (24x24, drawn with strokes, color = current text color).

const PATHS: Record<string, string[]> = {
  overview: ["M4 4h6v6H4z", "M14 4h6v6h-6z", "M4 14h6v6H4z", "M14 14h6v6h-6z"],
  dashboard: ["M5 20V11", "M12 20V4", "M19 20v-6", "M3 20h18"],
  pages: ["M7 3h7l5 5v13H7z", "M14 3v5h5", "M10 13h6", "M10 17h6"],
  sources: ["M4 12h13", "M12 6l6 6-6 6"],
  audience: ["M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18", "M3 12h18", "M12 3c3 3.5 3 14.5 0 18", "M12 3c-3 3.5-3 14.5 0 18"],
  sessions: ["M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18", "M12 7v5l3 2"],
  people: ["M12 4a4 4 0 1 0 0 8a4 4 0 1 0 0-8", "M4 21c0-4 3.6-6 8-6s8 2 8 6"],
  live: ["M3 12h4l3-7 4 14 3-7h4"],
  recordings: ["M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18", "M10 8.5v7l5.5-3.5z"],
  reports: ["M7 3h10v18H7z", "M10 8h4", "M10 12h4", "M10 16h2"],
  settings: ["M4 7h10", "M18 7h2", "M4 17h2", "M10 17h10", "M14 5v4h4V5z", "M6 15v4h4v-4z"],
  billing: ["M3 7h18v10H3z", "M3 11h18", "M7 15h3"],
  help: ["M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18", "M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7", "M12 17h.01"],
  menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
  close: ["M6 6l12 12", "M18 6L6 18"],
  eye: ["M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z", "M12 9.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5"],
  eyeOff: ["M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z", "M12 9.5a2.5 2.5 0 1 0 0 5a2.5 2.5 0 1 0 0-5", "M4 4l16 16"],
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = "h-5 w-5" }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
